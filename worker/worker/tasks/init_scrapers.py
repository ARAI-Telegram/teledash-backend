from typing import List

import celery
from celery import group
from celery.utils.log import get_task_logger

from common.settings import settings
from common.utils import flatten, get_or_create_event_loop, naive_utcnow
from worker import tasks
from worker.database.database import Database
from worker.main import app
from worker.scraping.services.scraping_service import ScrapingService
from worker.utils.celery_queue_manager import get_active_tasks, task_already_reserved

logger = get_task_logger(__name__)


@app.task(bind=True, name="scraping.enqueue_init_scrapers")
def enqueue_init_scrapers(self):
    if task_already_reserved("scraping.init_scrapers"):
        logger.info("init_scrapers already queued; skipping enqueue")
        return
    init_scrapers.apply_async()


@app.task(bind=True, name="scraping.init_scrapers")
def init_scrapers(
    self: celery.Task,
) -> None:
    loop = get_or_create_event_loop()
    return loop.run_until_complete(init_scrapers_async(self))


async def init_scrapers_async(
    self: celery.Task,
) -> None:
    """Initialize and queue scraping tasks for all active clients.

    This function:
    1. Identifies active history and live scraping tasks
    2. Retrieves active Telegram clients
    3. Prepares each valid client for scraping (joins chats, fetches references, prepares indices)
    4. Queues live scraping tasks for eligible clients
    5. Queues history scraping tasks with deduplicated chat lists

    Returns:
        None
    """
    database = Database()
    scraping_service = ScrapingService(database)

    client_chat_map_history = []
    client_list_live: List[str] = []

    # Check for active scraping tasks
    logger.info("Checking for active scraping tasks")
    active_history_tasks = get_active_tasks(["scraping.scrape_chats_history"])
    active_history_client_ids: List[str] = [
        task["kwargs"]["client_id"]
        for task in active_history_tasks
        if "client_id" in task["kwargs"]
    ]
    active_history_chat_ids: List[int] = flatten(
        [
            task["kwargs"]["chat_ids"]
            for task in active_history_tasks
            if "chat_ids" in task["kwargs"]
        ]
    )

    # Check for active live tasks
    if settings.live_updates:
        active_live_tasks = get_active_tasks(["live.scrape_chats_live"])
        active_live_client_ids: List[str] = flatten(
            [
                task["kwargs"]["client_id"]
                for task in active_live_tasks
                if "client_id" in task["kwargs"]
            ]
        )
    else:
        active_live_client_ids = []

    # Get all active clients
    active_client_docs = scraping_service.client_manager.get_active_clients()
    if not active_client_docs:
        return

    # Process each client
    for client_doc in active_client_docs:
        # Skip clients that already have active tasks
        if client_doc.id in active_history_client_ids and (
            not settings.live_updates or client_doc.id in active_live_client_ids
        ):
            continue

        # Prepare client for scraping
        client_id, chat_ids = await scraping_service.prepare_client_for_scraping(
            client_doc=client_doc,
            active_history_chat_ids=active_history_chat_ids,
        )

        # Add to history scraping list if has chats
        if chat_ids:
            client_chat_map_history.append((client_id, chat_ids))

        # Add to live list if not already active
        if client_id not in active_live_client_ids and settings.live_updates:
            client_list_live.append(client_id)

    # Queue live scraping tasks
    live_scraping_start_time = None
    live_jobs = group(
        [
            tasks.scrape_chats_live.s(client_id=client_id)
            for client_id in client_list_live
        ]
    )
    if live_jobs:
        live_jobs.apply_async()
        logger.info("Starting live scraping..")
        live_scraping_start_time = naive_utcnow()
        logger.info("Live scraping started at: %s", live_scraping_start_time)
    else:
        logger.info("No live scrapers started")

    # Queue history scraping tasks with deduplicated chat IDs
    client_chat_map_history = scraping_service.deduplicate_client_chat_map(
        client_chat_map_history
    )

    history_jobs = group(
        [
            tasks.scrape_chats_history.s(
                client_id=client_id,
                chat_ids=list(chat_ids),
                live_scraping_start_time=live_scraping_start_time,
            )
            for client_id, chat_ids in client_chat_map_history
            if chat_ids
        ]
    )

    if history_jobs:
        history_jobs.apply_async()
        logger.info("Starting history scraping..")
    else:
        logger.info("No history scrapers started")

    database.close()
