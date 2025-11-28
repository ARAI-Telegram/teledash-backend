from celery.utils.log import get_task_logger

from common.utils import get_or_create_event_loop
from worker.database.database import Database
from worker.main import app
from worker.scraping.managers.client_manager import ClientManager
from worker.scraping.services.chat_service import ChatService
from worker.utils.containers import ResultsContainer

logger = get_task_logger(__name__)


@app.task(name="scraping.update_chats")
def update_chats() -> None:
    loop = get_or_create_event_loop()
    return loop.run_until_complete(update_chats_async())


async def update_chats_async() -> None:
    """Update chat information for all active Telegram clients.

    This function retrieves all active Telegram clients, fetches their
    associated chats from Telegram, and updates the chat documents and
    metrics in the database.

    Returns:
         None
    """
    database = Database()
    client_manager = ClientManager(database)
    chat_service = ChatService(database)

    container = ResultsContainer(
        size=1000,
        keys=["chats", "metrics"],
        database=database,
    )

    # Get all active clients
    active_client_docs = client_manager.get_active_clients()
    if not active_client_docs:
        logger.info("No active clients found")
        database.close()
        return

    success_count = 0
    error_count = 0

    # Process each client
    for client_doc in active_client_docs:
        try:
            tg_client = ClientManager.create_telegram_client(
                client_doc, takeout=False, no_updates=True
            )

            async with tg_client:
                await chat_service.update_client_chats(
                    tg_client=tg_client,
                    client_doc=client_doc,
                    container=container,
                )
                success_count += 1
                logger.info(f"Successfully updated chats for client {client_doc.id}")

        except Exception as e:
            logger.error(
                f"Error updating chats for client {client_doc.id}: {e}", exc_info=True
            )
            error_count += 1
            # Continue with next client

    # Save all updates to database
    if container.count():  # also here we dont continue if errors
        container.save_to_database(refresh="false")
        container.clear_data()

    database.close()

    logger.info(
        f"Update chats completed: {success_count} successful, {error_count} errors"
    )

    # Fail task if ALL clients failed
    if success_count == 0 and error_count > 0:
        raise RuntimeError(f"Failed to update chats for all {error_count} clients")
