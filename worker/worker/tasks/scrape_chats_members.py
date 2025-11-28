from typing import List

from celery.utils.log import get_task_logger
from elasticsearch.dsl import Q

from common.utils import get_or_create_event_loop
from worker.database.database import Database
from worker.main import app
from worker.scraping.managers.client_manager import ClientManager
from worker.scraping.managers.metric_manager import add_chat_metric
from worker.scraping.telegram_api.client import fetch_chat_members
from worker.utils.containers import ResultsContainer
from worker.utils.helpers import add_users_if_enabled

logger = get_task_logger(__name__)


@app.task(name="scraping.scrape_chat_members")
def scrape_chat_members():
    loop = get_or_create_event_loop()
    return loop.run_until_complete(scrape_chat_members_async())


async def scrape_chat_members_async() -> None:
    """
    Asynchronously scrapes chat members and recommended chats.
    Steps:
    1. Retrieve active client documents and their associated chats from the database.
    2. For each client, initialize a Telegram client session.
    3. For each chat, fetch chat members (if accessible) and update in database.
    4. Collect and batch-store user data into the database using a results container.

    Exceptions during Telegram client initialization, chat member fetching, or database updates
    are logged and skipped to ensure the process continues for other clients and chats.

    Raises:
        None. All exceptions related to Telegram client initialization, chat member fetching,
        and database updates are caught and logged to ensure continued execution.

    Returns:
        None
    """
    database = Database()
    container = ResultsContainer(
        size=1000,
        keys=["users"],
        database=database,
    )

    success_count = 0
    error_count = 0

    # get all client documents and collect chat ids to scrape
    filter = Q(
        "bool", filter=[Q("term", is_active=True), Q("exists", field="session_hash")]
    )
    client_docs = database.clients.find(filter=filter)

    client_manager = ClientManager(database)

    for client_doc in client_docs:
        # continue if client has no chat refs yet
        if not client_doc.chats:
            logger.info(f"Client {client_doc.id} has no chat references, skipping")
            continue

        try:
            tg_client = client_manager.create_telegram_client(
                db_client_doc=client_doc, takeout=False, no_updates=True
            )
            logger.info(f"Initializing Telegram client {tg_client}")
        except Exception as e:
            logger.error(
                f"Error while initializing Telegram client: {e}", exc_info=True
            )
            continue

        # Get chat ids from client doc
        # In the worker we don't validate the objects returned from db, so the linter doesn't know
        # that the nested chat_refs are dicts, but they are, thats why we can safely add a type ignore.
        chat_ids = [chat_ref["id"] for chat_ref in client_doc.chats]  # type: ignore[attr-defined]

        # Get chat docs from chat ids
        filter = Q(
            "bool",
            filter=[
                Q("ids", values=chat_ids),
            ],
        )
        chat_docs = database.chats.find(filter=filter)

        try:
            async with tg_client:
                for chat in chat_docs:
                    chat_users = []
                    logger.info(f"Fetching users for chat {chat.id}")
                    try:
                        chat_users = await fetch_chat_members(
                            tg_client, chat.id, client_doc.id
                        )
                    except Exception as e:
                        logger.error(
                            f"Error while fetching chat members: {e}", exc_info=True
                        )
                        error_count += 1
                        continue

                    if chat_users:
                        chat_user_refs: List[dict] = [
                            user.create_ref().model_dump(
                                exclude_none=True,
                            )
                            for user in chat_users
                        ]
                        logger.info(f"Collected {len(chat_user_refs)} users")

                        # update chat doc
                        filter = Q("ids", values=[str(chat.id)])
                        update_query = {"members": chat_user_refs}
                        try:
                            database.chats.update_one(
                                filter=filter, update=update_query
                            )
                        except Exception as e:
                            logger.error(
                                f"Error while updating chat members: {e}", exc_info=True
                            )
                            error_count += 1
                            continue

                        add_users_if_enabled(chat_users, container)

                        if container.is_full:
                            container.save_to_database(refresh="false")
                            container.clear_data()

                    add_chat_metric(chat, container)

                    # Count success only after all steps completed
                    success_count += 1

            logger.info(f"Successfully processed members for client {client_doc.id}")

        except Exception as e:
            logger.error(f"Error processing client {client_doc.id}: {e}", exc_info=True)
            # Continue with next client

    if container.count():
        container.save_to_database(refresh="false")

    database.close()

    logger.info(
        f"Scrape chat members completed: {success_count} chats successful, {error_count} chats failed"
    )
