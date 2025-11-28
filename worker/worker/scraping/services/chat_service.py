"""Service for managing chat updates and recommendations."""

from datetime import datetime

from celery.utils.log import get_task_logger
from pydantic import ValidationError
from pyrogram.client import Client as TelegramClient

from common.database.models.chat import Chat, ChatType
from common.database.models.client import Client
from common.database.models.refs import ChatRef
from worker.database.database import Database
from worker.scraping.managers.chat_manager import ChatManager
from worker.scraping.managers.metric_manager import add_chat_metric
from worker.scraping.telegram_api.client import fetch_chat_from_telegram
from worker.scraping.telegram_api.recommendations import get_recommended_channels
from worker.utils.containers import ResultsContainer

logger = get_task_logger(__name__)


class ChatService:
    """High-level service for chat update operations.

    This service handles fetching chat information from Telegram,
    updating chat documents, and managing chat recommendations.
    """

    def __init__(self, database: Database) -> None:
        """Initialize ChatService with database and chat manager.

        Args:
            database: Database instance for all operations.
        """
        self.database = database
        self.chat_manager = ChatManager(database)

    async def update_single_chat(
        self,
        tg_client: TelegramClient,
        chat_id: int,
        client_doc: Client,
        db_chat_docs: dict,
        container: ResultsContainer,
    ) -> None:
        """Update a single chat with latest information from Telegram.

        Args:
            tg_client: Active Pyrogram client connection.
            chat_id: Telegram chat ID to update.
            client_doc: Client document for reference.
            db_chat_docs: Dictionary of existing chat documents from database.
            container: ResultsContainer for batching updates.
        """
        # Fetch chat from Telegram
        try:
            tg_chat = await fetch_chat_from_telegram(chat_id, tg_client)
        except Exception:
            logger.error(
                f"Error receiving chat {chat_id} from Telegram. Skipping update."
            )
            return

        # Validate chat
        if (
            tg_chat is None
            or tg_chat.type
            and tg_chat.type.name not in ChatType._value2member_map_
        ):
            logger.warning(f"Chat {chat_id} not found or wrong type. Skipping update.")
            return

        # Convert to Chat model
        try:
            updated_chat = Chat.from_pyrogram_chat(tg_chat, client_doc.id)
        except ValidationError:
            logger.error(f'Error validating chat "{tg_chat.id}"', exc_info=True)
            return

        # Add similar channels for channels
        if updated_chat.type == ChatType.CHANNEL:
            similar_channel_refs = await get_recommended_channels(
                tg_client=tg_client, chat_id=chat_id
            )
            if similar_channel_refs:
                updated_chat.similar_channels = [
                    ChatRef(**ref) for ref in similar_channel_refs
                ]
                logger.info("Updating similar channels for chat %s", chat_id)

        # Preserve fields from existing database document
        db_chat_doc = db_chat_docs.get(chat_id)
        if db_chat_doc:
            for field_name, field_value in db_chat_doc:
                if field_value is not None and (
                    not hasattr(updated_chat, field_name)
                    or getattr(updated_chat, field_name) is None
                ):
                    if field_name == "history_updated_at" and isinstance(
                        field_value, str
                    ):
                        field_value = datetime.fromisoformat(field_value)
                    setattr(updated_chat, field_name, field_value)

        # Add member count metric if available
        add_chat_metric(updated_chat, container)

        # Add to container for batch save
        container.add("chats", updated_chat)
        logger.info(f"Updated chat {chat_id} for client {client_doc.id}")

    async def update_client_chats(
        self,
        tg_client: TelegramClient,
        client_doc: Client,
        container: ResultsContainer,
    ) -> None:
        """Update all chats for a specific client.

        Args:
            tg_client: Active Pyrogram client connection.
            client_doc: Client document with chat references.
            container: ResultsContainer for batching updates.
        """
        if not client_doc.chats:
            logger.info(f"Client {client_doc.id} has no chats to update.")
            return

        # Parse chat references
        chat_refs = [
            ChatRef(**chat) if isinstance(chat, dict) else chat
            for chat in client_doc.chats
        ]
        chat_ids = [chat.id for chat in chat_refs]

        # Fetch existing chat documents
        db_chat_docs = self.chat_manager.get_chat_documents(chat_ids)

        # Update each chat
        for chat_id in chat_ids:
            await self.update_single_chat(
                tg_client=tg_client,
                chat_id=chat_id,
                client_doc=client_doc,
                db_chat_docs=db_chat_docs,
                container=container,
            )
