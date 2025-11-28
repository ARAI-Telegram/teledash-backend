"""Index management for Elasticsearch operations."""

import time
from typing import Optional

from celery.utils.log import get_task_logger
from pydantic import ValidationError
from pyrogram.client import Client as TelegramClient

from common.database.models.chat import Chat, ChatType
from common.database.models.client import Client
from common.settings import settings
from worker.database import dynamic_messages_indexing
from worker.database.database import Database
from worker.scraping.managers.chat_manager import ChatManager
from worker.scraping.managers.metric_manager import add_chat_metric
from worker.scraping.telegram_api.client import fetch_chat_from_telegram
from worker.utils.containers import ResultsContainer

logger = get_task_logger(__name__)


class IndexManager:
    """Manages Elasticsearch index operations for chats and messages.

    This class provides methods to ensure chat and message indices exist
    and are properly configured for scraping operations.
    """

    def __init__(self, database: Database) -> None:
        """Initialize IndexManager with a database connection.

        Args:
            database: Database instance for index operations.
        """
        self.database = database

    def chat_indices_need_preparation(
        self, chat_id: int, db_chat_doc: Optional[Chat] = None
    ) -> bool:
        """Check if a chat needs preparation for scraping.
        Preparation is needed if:
        - Chat document does not exist
        - Chat document exists but language is not set
        - Messages index for the chat does not exist

        Args:
            chat_id: Telegram chat ID to check.
            db_chat_doc: Optional existing chat document from database.

        Returns:
            True if preparation is needed, False if ready.
        """
        return (
            not db_chat_doc
            or not db_chat_doc.language
            or not self.database.check_messages_index_exists(chat_id)
        )

    async def prepare_chat_indices_for_scraping(
        self,
        tg_client: TelegramClient,
        tg_chat_id: int,
        client_doc: Client,
        chat_manager: ChatManager,
        db_chat_doc: Optional[Chat] = None,
    ) -> bool:
        """Prepare a single chat for scraping, if not already prepared.

        Steps:
        1. Checks if preparation is needed
        2. If needed: calls _execute_preparation, which fetches chat from Telegram,
           detects language, creates indices
        3. Saves chat document and metrics

        Args:
            tg_client: Active Pyrogram client connection.
            tg_chat_id: Telegram chat ID to prepare.
            client_doc: Client document for the scraping operation.
            chat_manager: ChatManager instance for language detection.
            db_chat_doc: Optional existing chat document from database.

        Returns:
            True if successfully prepared, False if preparation failed.
        """
        # Check if preparation needed
        if not self.chat_indices_need_preparation(tg_chat_id, db_chat_doc):
            logger.debug(f"Chat {tg_chat_id} already prepared")
            return True

        logger.info(f"Preparing chat {tg_chat_id} for scraping")

        try:
            await self._execute_preparation(
                tg_client=tg_client,
                tg_chat_id=tg_chat_id,
                client_doc=client_doc,
                db_chat_doc=db_chat_doc,
                chat_manager=chat_manager,
            )
            logger.info(f"Successfully prepared chat {tg_chat_id}")
            return True
        except Exception as e:
            logger.error(
                f"Failed to prepare chat {tg_chat_id}: {e}",
                exc_info=True,
            )
            return False

    async def _execute_preparation(
        self,
        tg_client: TelegramClient,
        tg_chat_id: int,
        client_doc: Client,
        chat_manager: ChatManager,
        db_chat_doc: Optional[Chat],
    ) -> None:
        """Execute the actual preparation work for a chat.

        Internal method that:
        1. Fetches chat details from Telegram (if not in DB)
        2. Detects chat language by analyzing messages
        3. Creates/updates chat document
        4. Creates messages index with proper language settings
        5. Saves chat and member count metrics to database

        Args:
            tg_client: The Telegram client to fetch chat details.
            tg_chat_id: The Telegram chat ID to prepare.
            client_doc: The database client document.
            chat_manager: ChatManager instance for language detection.
            db_chat_doc: Optional chat document from the database.

        Raises:
            TimeoutError: If messages index creation times out.
        """
        container = ResultsContainer(
            size=1000,
            keys=["chats", "metrics"],
            database=self.database,
        )

        chat_language = None
        chat_language_other = None

        if not db_chat_doc:
            # Chat does not exist in DB: fetch from Telegram, parse, detect language, save
            tg_chat = await fetch_chat_from_telegram(tg_chat_id, tg_client)
            if tg_chat is None:
                logger.warning(f"Could not fetch chat {tg_chat_id} from Telegram")
                return
            if (
                tg_chat.type is None
                or tg_chat.type.name not in ChatType._value2member_map_
            ):
                logger.warning(
                    f"Invalid chat type for chat {tg_chat_id}: {tg_chat.type}"
                )
                return
            try:
                new_chat = Chat.from_pyrogram_chat(tg_chat, client_doc.id)
            except ValidationError:
                logger.error(f'Error validating chat "{tg_chat.id}"', exc_info=True)
                return
            logger.info(f"Chat information of chat {tg_chat_id} is being scraped")

            # Detect language
            try:
                (
                    chat_language,
                    chat_language_other,
                ) = await chat_manager.get_chat_language(
                    chat_id=tg_chat_id, chat_doc=new_chat, tg_client=tg_client
                )
            except Exception as e:
                logger.error(
                    f"Error detecting language for chat {tg_chat_id}: {e}",
                    exc_info=True,
                )
                # Continue with fallback language

            new_chat.language = (
                chat_language if chat_language else settings.fallback_language
            )
            new_chat.language_other = chat_language_other

            # Add member count metric if available
            add_chat_metric(new_chat, container)

            container.add("chats", new_chat)

        elif db_chat_doc and not db_chat_doc.language:
            # Detect and update language for existing chat
            try:
                (
                    chat_language,
                    chat_language_other,
                ) = await chat_manager.get_chat_language(
                    chat_id=tg_chat_id, chat_doc=db_chat_doc, tg_client=tg_client
                )
                db_chat_doc.language = chat_language
                db_chat_doc.language_other = chat_language_other
            except Exception as e:
                logger.error(
                    f"Error detecting language for existing chat {tg_chat_id}: {e}",
                    exc_info=True,
                )
                # Set fallback language
                db_chat_doc.language = settings.fallback_language

            container.add("chats", db_chat_doc)

        if container.count():
            container.save_to_database(refresh="true")
            container.clear_data()

        # Create messages index if needed, always using the detected or existing language
        if not self.database.check_messages_index_exists(tg_chat_id):
            self._create_and_wait_for_messages_index(
                tg_chat_id,
                chat_language if chat_language else settings.fallback_language,
            )

    def _create_and_wait_for_messages_index(
        self, chat_id: int, language: str, timeout_seconds: int = 60
    ) -> None:
        """Create messages index for a chat and wait for it to be ready.

        Args:
            chat_id: Telegram chat ID to create index for.
            language: Language code for the index analyzer.
            timeout_seconds: Maximum seconds to wait for index creation. Defaults to 60.

        Raises:
            TimeoutError: If index creation times out.
            Exception: If index creation fails.
        """
        try:
            dynamic_messages_indexing.create_index_for_chatmessages(
                self.database.es_client,
                chat_id,
                language,
            )

            # Wait for index creation with timeout
            retry_count = 0
            while not self.database.check_messages_index_exists(chat_id):
                if retry_count >= timeout_seconds:
                    raise TimeoutError(
                        f"Timeout waiting for messages index creation for chat {chat_id}"
                    )
                time.sleep(1)
                retry_count += 1

            logger.info(
                f"Messages index created for chat {chat_id} with language {language}"
            )
        except Exception as e:
            logger.error(
                f"Error creating messages index for chat {chat_id}: {e}",
                exc_info=True,
            )
            raise
