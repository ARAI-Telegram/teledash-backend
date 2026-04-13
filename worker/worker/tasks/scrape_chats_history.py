import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from random import randrange
from typing import List, Optional

import celery
from celery.utils.log import get_task_logger
from elasticsearch.dsl import Q, Query
from pyrogram.client import Client as TgClient

from common.database.models.chat import Chat
from common.database.models.message.scraping_mode import ScrapingMode
from common.settings import settings
from common.utils import get_or_create_event_loop, naive_utcnow
from worker import tasks
from worker.database.database import Database
from worker.main import app
from worker.scraping.managers.client_manager import ClientManager
from worker.scraping.managers.message_processor import (
    add_storage_refs_to_message,
    parse_and_validate_message,
    set_message_metadata,
    valid_message_attachment,
)
from worker.scraping.managers.metric_manager import add_message_metric
from worker.scraping.services.attachment_service import (
    attachment_download_enabled,
    download_single_attachment_from_telegram,
    get_attachment_max_date,
)
from worker.scraping.telegram_api.client import fetch_chat_history
from worker.utils.containers import ResultsContainer, StorageFileCache
from worker.utils.helpers import add_users_if_enabled

logger = get_task_logger(__name__)
TMP_PATH = Path().cwd().joinpath("tmp")


@app.task(bind=True, name="scraping.scrape_chats_history")
def scrape_chats_history(
    self: celery.Task,
    client_id: str,
    chat_ids: List[int],
    live_scraping_start_time: Optional[datetime],
):
    loop = get_or_create_event_loop()
    return loop.run_until_complete(
        scrape_chats_history_async(self, client_id, chat_ids, live_scraping_start_time)
    )


async def scrape_chats_history_async(
    task: celery.Task,
    client_id: str,
    chat_ids: List[int],
    live_scraping_start_time: Optional[datetime],
) -> Optional[dict]:
    """
    Asynchronously scrape historical messages (oldest to newest) from
    a list of Telegram chats.

    Args:
        task: Celery task instance.
        client_id: The unique identifier of the Telegram client.
        chat_ids: List of Telegram chat IDs to scrape.
        live_scraping_start_time: Upper time boundary for history scraping.
            Marks when live scraping began. History scraper fetches older messages
            to avoid overlap. None if live scraping is disabled.

    Returns:
        None

    Raises:
        ValueError: If client_id or chat_ids is empty.
    """
    if not client_id or not chat_ids:
        raise ValueError("Invalid task arguments")

    logger.info(f"Scraping chats for client {client_id} with {len(chat_ids)} chat IDs")

    # Setup
    database = Database()
    dynamic_keys = ["users", "chats", "metrics"] + [
        f"messages_{chat_id}" for chat_id in chat_ids
    ]
    container = ResultsContainer(size=1000, keys=dynamic_keys, database=database)

    scrape_chats_max_date = _calculate_scrape_dates()

    # Initialize client
    client_manager = ClientManager(database)
    db_client_doc = client_manager.get_active_client_by_id(client_id)

    # Fetch chat documents
    response = database.chats.find(
        filter=Q(
            "ids", values=[str(chat_id) for chat_id in chat_ids]
        ),  # i think i dont need str()
        fields={"includes": ["language", "language_other", "history_updated_at"]},
    )
    db_chat_docs = {int(chat.id): chat for chat in response if chat is not None}

    # Create Telegram client
    tg_client = ClientManager.create_telegram_client(
        db_client_doc=db_client_doc, takeout=True, no_updates=True
    )
    logger.info(f"Initializing Telegram client {db_client_doc.title}")

    # Scraping
    attachment_counter = 0
    file_cache = StorageFileCache()
    total_chats = len(db_chat_docs)
    success_count = 0
    error_count = 0

    async with tg_client:
        for index, (tg_chat_id, db_chat_doc) in enumerate(
            db_chat_docs.items(), start=1
        ):
            logger.info(f"Starting to scrape chat {tg_chat_id} ({index}/{total_chats})")
            try:
                attachment_counter = await _scrape_single_chat_history(
                    db_chat_doc=db_chat_doc,
                    tg_client=tg_client,
                    task=task,
                    database=database,
                    container=container,
                    client_id=client_id,
                    live_scraping_start_time=live_scraping_start_time,
                    scrape_chats_max_date=scrape_chats_max_date,
                    file_cache=file_cache,
                    attachment_counter=attachment_counter,
                )
                success_count += 1
            except Exception as e:
                logger.error(
                    f"Error while scraping history for chat {tg_chat_id}: {e}",
                    exc_info=True,
                )
                error_count += 1
                continue

            await asyncio.sleep(3 + randrange(20) / 10)

    # Cleanup
    logger.info(
        "Scraping chats finished. Client %s: %d chats successful, %d chats failed, %d attachments downloaded",
        client_id,
        success_count,
        error_count,
        attachment_counter,
    )
    file_cache.clear()
    database.close()


def _calculate_scrape_dates():
    """Calculate date boundaries for history scraping.

    Returns:
        datetime: Maximum date threshold for scraping (messages older than this are skipped).
    """
    scrape_chats_max_days = settings.scrape_chats_max_days
    return (
        naive_utcnow() - timedelta(days=scrape_chats_max_days)
        if scrape_chats_max_days > 0
        else datetime.min
    )


def _build_history_filter(
    db_chat_doc: Chat,
    live_scraping_start_time: Optional[datetime],
) -> Query:
    """Build Elasticsearch filter for finding the last scraped message.

    Args:
        db_chat_doc: Chat document to build filter for.
        live_scraping_start_time: Upper time boundary (exclude messages newer than this).

    Returns:
        Elasticsearch Query object.
    """
    filter_query = Q("term", **{"chat.id": int(db_chat_doc.id)})
    if live_scraping_start_time is not None:
        filter_query &= Q("range", date={"lt": live_scraping_start_time})

    # If history_updated_at is not yet set, only look for HISTORY mode messages
    has_history_updated_at = (
        hasattr(db_chat_doc, "history_updated_at")
        and db_chat_doc.history_updated_at is not None
    )
    if not has_history_updated_at:
        filter_query &= Q("term", scraping_mode="HISTORY")

    return filter_query


def _get_last_message_id(
    database: Database, tg_chat_id: int, filter_query
) -> Optional[int]:
    """Get the last processed message ID (i.e. most recent) for a chat.

    Args:
        database: Database instance.
        tg_chat_id: Chat ID to query.
        filter_query: Elasticsearch filter.

    Returns:
        Last message ID or None if no messages found.
    """
    sorting = [{"field": "date", "order": "desc"}]
    collection = database.get_messages_collection(tg_chat_id)
    latest_message = collection.find_one(
        filter=filter_query,
        sort=sorting,
        fields=None,
    )
    return latest_message.id_in_chat if latest_message else None


def _save_container_and_process_attachments(
    container: ResultsContainer,
    downloaded_attachments: List[dict],
    tg_chat_id: int,
    session_dir: Path,
) -> None:
    """Save container to database and process attachments.

    Args:
        container: Results container to save.
        downloaded_attachments: List of attachments to process.
        tg_chat_id: Chat ID for processing.
        session_dir: Session directory to clean up.
    """
    if container.count():
        container.save_to_database(refresh="true")

    if len(downloaded_attachments) > 0:
        tasks.process_attachments.s(downloaded_attachments, tg_chat_id).apply_async()

    if session_dir.exists() and session_dir.is_dir():
        try:
            session_dir.rmdir()
        except OSError as e:
            logger.error(f"Error removing directory {session_dir}: {e}")


async def _scrape_single_chat_history(
    db_chat_doc: Chat,
    tg_client: TgClient,
    task: celery.Task,
    database: Database,
    container: ResultsContainer,
    client_id: str,
    live_scraping_start_time: Optional[datetime],
    scrape_chats_max_date: datetime,
    file_cache: StorageFileCache,
    attachment_counter: int,
) -> int:
    """Scrape history for a single chat.

    Args:
        db_chat_doc: Chat document.
        tg_client: Telegram client.
        task: Celery task.
        database: Database instance.
        container: ResultsContainer.
        client_id: Client ID.
        live_scraping_start_time: Upper time boundary.
        scrape_chats_max_date: Lower time boundary.
        file_cache: File cache.
        attachment_counter: Current attachment count.

    Returns:
        Updated attachment_counter.
    """
    tg_chat_id = int(db_chat_doc.id)
    session_dir = TMP_PATH.joinpath("sessions", task.request.id, str(tg_chat_id))
    downloaded_attachments = []

    # Build query and get last message ID
    filter_query = _build_history_filter(db_chat_doc, live_scraping_start_time)
    last_message_id = _get_last_message_id(database, tg_chat_id, filter_query)

    # Determine attachment settings
    download_attachments = attachment_download_enabled()
    max_attachment_date = get_attachment_max_date()

    logger.info(
        f"Fetching messages for chat {tg_chat_id} (max_date: {scrape_chats_max_date}, last_message_id: {last_message_id})"
    )

    # Get chat language
    chat_language = db_chat_doc.language if hasattr(db_chat_doc, "language") else None

    # Iterate through chat messages
    async for tg_message in fetch_chat_history(
        tg_client,
        tg_chat_id,
        reverse=True,
        min_id=(last_message_id + 1) if last_message_id else 0,
    ):
        # Skip old messages
        if tg_message.date and tg_message.date < scrape_chats_max_date:
            continue

        # Parse and validate message
        result = parse_and_validate_message(tg_message, client_id)
        if not result:
            continue

        new_users, new_message = result

        # Set message metadata
        set_message_metadata(new_message, chat_language, ScrapingMode.HISTORY)

        # Create metric
        add_message_metric(new_message, container)

        # Handle attachment download
        if download_attachments and valid_message_attachment(
            new_message, max_attachment_date
        ):
            try:
                downloaded_attachment = await download_single_attachment_from_telegram(
                    session_dir=session_dir,
                    tg_client=tg_client,
                    parsed_message=new_message,
                    tg_message_or_file_id=tg_message,
                    file_cache=file_cache,
                )

                if downloaded_attachment:
                    if downloaded_attachment.get("already_exists"):
                        add_storage_refs_to_message(new_message, downloaded_attachment)
                    else:
                        downloaded_attachments.append(downloaded_attachment)
                        attachment_counter += 1
            except Exception as e:
                logger.error(
                    f"Error downloading attachment for message {new_message.id}: {e}",
                    exc_info=True,
                )

        # Add users if enabled
        add_users_if_enabled(new_users, container)

        # Add message to container
        container.add(f"messages_{tg_chat_id}", new_message)

        # Save when container is full
        if container.is_full:
            logger.info(
                "Container is full, saving to database. Downloaded attachments: %d",
                len(downloaded_attachments),
            )
            try:
                _save_container_and_process_attachments(
                    container, downloaded_attachments, tg_chat_id, session_dir
                )
                container.clear_data()
                downloaded_attachments.clear()
            except Exception as e:
                logger.error(
                    f"Error saving container for chat {tg_chat_id}: {e}",
                    exc_info=True,
                )
                container.clear_data()
                downloaded_attachments.clear()
                raise  # Exit chat loop

    # Save remaining results
    logger.info(
        "Saving remaining results to database. Downloaded attachments: %d",
        len(downloaded_attachments),
    )
    try:
        _save_container_and_process_attachments(
            container, downloaded_attachments, tg_chat_id, session_dir
        )
        container.clear_data()
    except Exception as e:
        logger.error(
            f"Error saving final container for chat {tg_chat_id}: {e}",
            exc_info=True,
        )
        container.clear_data()
        raise  # Exit chat loop

    # Update history_updated_at
    filter_query = Q("ids", values=[str(tg_chat_id)])
    database.chats.update_one(
        filter=filter_query, update={"history_updated_at": naive_utcnow()}
    )
    logger.info(f"Finished fetching messages for chat {tg_chat_id}")

    return attachment_counter
