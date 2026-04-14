"""Service for orchestrating scraping operations."""

from typing import List, Optional, Set, Tuple

from celery.utils.log import get_task_logger
from elasticsearch.dsl import Q

from common.database.models.chat import Chat
from common.database.models.client import Client
from worker.database.database import Database
from worker.scraping.managers.chat_manager import ChatManager
from worker.scraping.managers.client_manager import ClientManager
from worker.scraping.managers.index_manager import IndexManager
from worker.utils.helpers import exclude_duplicate_chat_ids

logger = get_task_logger(__name__)

ClientChatMap = List[Tuple[str, Set[int]]]


class ScrapingService:
    """High-level service for coordinating scraping operations.

    This service orchestrates the scraping workflow by coordinating
    ClientManager, ChatManager, and IndexManager to prepare clients
    and chats for scraping tasks.
    """

    def __init__(self, database: Database) -> None:
        """Initialize ScrapingService with database and core managers.

        Args:
            database: Database instance for all operations.
        """
        self.database = database
        self.client_manager = ClientManager(database)
        self.chat_manager = ChatManager(database)
        self.index_manager = IndexManager(database)

    async def ensure_chat_ready(
        self,
        tg_client,
        client_doc: Client,
        chat_id: int,
    ) -> Optional[Chat]:
        """Ensure a single chat is ready for scraping using provided client.

        Args:
            tg_client: Active Telegram client connection.
            client_doc: Client document for the operation.
            chat_id: Telegram chat ID to prepare.

        Returns:
            Chat document if successfully prepared, None if failed.
        """
        # Fetch existing chat document
        db_chat_doc = self.database.chats.find_one(
            filter=Q("ids", values=[str(chat_id)]),
            fields={"includes": ["language"]},
        )

        # Check if preparation needed
        if not self.index_manager.chat_indices_need_preparation(chat_id, db_chat_doc):
            return db_chat_doc

        # Prepare chat indices
        success = await self.index_manager.prepare_chat_indices_for_scraping(
            tg_client=tg_client,
            tg_chat_id=chat_id,
            client_doc=client_doc,
            chat_manager=self.chat_manager,
            db_chat_doc=db_chat_doc,
        )

        if not success:
            logger.error(f"Failed to prepare chat {chat_id}")
            return None

        # Fetch updated chat document
        db_chat_doc = self.database.chats.find_one(
            filter=Q("ids", values=[str(chat_id)]),
            fields={"includes": ["language"]},
        )

        if not db_chat_doc:
            logger.error(f"Chat {chat_id} not found after preparation")
            return None

        return db_chat_doc

    async def ensure_chats_ready(
        self,
        tg_client,
        tg_chat_ids: List[int],
        client_doc: Client,
    ) -> List[int]:
        """Prepare multiple chats for scraping using existing client.

        Loops over chat IDs and ensures each is ready for scraping,
        which means the chat and its messages index is prepared.

        Args:
            tg_client: Active Pyrogram client connection.
            tg_chat_ids: List of Telegram chat IDs to prepare.
            client_doc: Client document for the operation.

        Returns:
            List of successfully prepared chat IDs.
        """
        prepared_chat_ids = []
        for tg_chat_id in tg_chat_ids:
            db_chat_doc = await self.ensure_chat_ready(
                tg_client=tg_client,
                client_doc=client_doc,
                chat_id=tg_chat_id,
            )
            if db_chat_doc:
                prepared_chat_ids.append(tg_chat_id)
            else:
                logger.error(f"Skipping chat {tg_chat_id} due to preparation failure")
        return prepared_chat_ids

    def _filter_available_chats(
        self,
        prepared_chat_ids: List[int],
        active_history_chat_ids: List[int],
    ) -> List[int]:
        """Filter out chats that are already being scraped.

        Args:
            prepared_chat_ids: List of chat IDs with prepared indices.
            active_history_chat_ids: List of chat IDs currently being scraped.

        Returns:
            List of chat IDs available for scraping.
        """
        return [
            chat_id
            for chat_id in prepared_chat_ids
            if chat_id not in active_history_chat_ids
        ]

    async def prepare_client_for_scraping(
        self,
        client_doc: Client,
        active_history_chat_ids: List[int],
        client_has_active_live_task: bool = False,
    ) -> Tuple[str, Set[int]]:
        """Prepare a single client for scraping operations.

        This method:
        1. Initializes the Telegram client
        2. Joins pending chats
        3. Fetches and updates chat references
        4. Ensures all indices for all chats exist for scraping
        5. Filters out chats already being scraped
        6. If live is already running, filters out chats already fully scraped

        Args:
            client_doc: Client document to prepare.
            active_history_chat_ids: List of chat IDs currently being scraped
                                    by history scrapers (to exclude).
            client_has_active_live_task: If True, skip chats that already have
                                        history_updated_at set (live handles new
                                        messages; history is not needed).

        Returns:
            Tuple of (client_id, set of chat_ids ready for scraping).
            Returns empty set if preparation fails.
        """
        try:
            tg_client = ClientManager.create_telegram_client(
                client_doc, takeout=False, no_updates=True
            )
        except Exception as e:
            logger.error(f"Failed to initialize client {client_doc.id}: {e}")
            return (str(client_doc.id), set())

        try:
            async with tg_client:
                # Join pending chats
                await self.client_manager.join_pending_chats(client_doc, tg_client)

                # Fetch and update chat references
                chat_refs = await self.chat_manager.fetch_and_update_chat_references(
                    tg_client, client_doc
                )

                if not chat_refs:
                    logger.info(f"No chat references found for client {client_doc.id}")
                    return (str(client_doc.id), set())

                # Extract chat IDs from references
                tg_chat_ids = [ref["id"] for ref in chat_refs]

                # If live is already running, skip chats that have been fully scraped
                if client_has_active_live_task:
                    tg_chat_ids = self.chat_manager.get_unscraped_chat_ids(tg_chat_ids)
                    if not tg_chat_ids:
                        logger.info(
                            f"All chats already scraped for client {client_doc.id}, "
                            f"live is running — skipping history"
                        )
                        return (str(client_doc.id), set())

                # Prepare indices for all chats
                prepared_chat_ids = await self.ensure_chats_ready(
                    tg_client, tg_chat_ids, client_doc
                )

                # Filter out chats already being scraped
                available_chat_ids = self._filter_available_chats(
                    prepared_chat_ids, active_history_chat_ids
                )

                if not available_chat_ids:
                    logger.info(
                        f"No available chats for historical scraping for client {client_doc.id}"
                    )
                    return (str(client_doc.id), set())

                logger.info(
                    f"Client {client_doc.id} prepared with {len(available_chat_ids)} "
                    f"chats ready for scraping"
                )
                return (str(client_doc.id), set(available_chat_ids))

        except Exception as e:
            logger.error(
                f"Error preparing client {client_doc.id} for scraping: {e}",
                exc_info=True,
            )
            return (str(client_doc.id), set())

    def deduplicate_client_chat_map(
        self, client_chat_map: ClientChatMap
    ) -> ClientChatMap:
        """Remove duplicate chat IDs across different clients.

        Ensures each chat ID is assigned to only one client.

        Args:
            client_chat_map: List of (client_id, chat_ids_set) tuples.

        Returns:
            Deduplicated client_chat_map with unique chat IDs per client.
        """
        return exclude_duplicate_chat_ids(client_chat_map)
