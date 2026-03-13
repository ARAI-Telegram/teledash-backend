"""Chat management for Telegram scraping operations."""

from typing import Any, Dict, List, Optional, Tuple

import gcld3
from celery.utils.log import get_task_logger
from elasticsearch.dsl import Q
from pyrogram.client import Client as TelegramClient

from common.database.models.chat import Chat
from common.database.models.client import Client
from worker.database.database import Database
from worker.scraping.telegram_api.client import (
    fetch_chat_history,
    fetch_valid_chat_references,
)

logger = get_task_logger(__name__)

# Global language detector instance
_language_detector = None


def _get_language_detector() -> Any:
    """Get or create the global language detector instance.

    Returns:
        NNetLanguageIdentifier instance for language detection.
    """
    global _language_detector

    if _language_detector is None:
        _language_detector = gcld3.NNetLanguageIdentifier(  # type: ignore
            min_num_bytes=0, max_num_bytes=1000
        )

    return _language_detector


class ChatManager:
    """Manages chat operations including fetching, validation, and database updates.

    This class provides methods to retrieve chat references from Telegram,
    fetch chat documents from the database, and manage chat-related operations.
    """

    def __init__(self, database: Database) -> None:
        """Initialize ChatManager with a database connection.

        Args:
            database: Database instance for chat document operations.
        """
        self.database = database

    async def fetch_and_update_chat_references(
        self, tg_client: TelegramClient, client_doc: Client
    ) -> List[dict]:
        """Fetch valid chat references from Telegram and update client document.

        Retrieves all accessible chats for the client from Telegram and updates
        the client document with the current chat references.

        Args:
            tg_client: Active Pyrogram client connection.
            client_doc: Client document to update with chat references.

        Returns:
            List of chat reference dictionaries containing id, title, etc.
            Returns empty list if client has no chats.

        Raises:
            Exception: If fetching chat references or updating database fails.
        """
        chat_refs = await fetch_valid_chat_references(tg_client)
        if not chat_refs:
            logger.info(f"No valid chat references found for client {client_doc.id}")
            return []
        logger.info(
            f"Fetched {len(chat_refs)} chat references for client {client_doc.id}"
        )

        # Update client document with fresh chat references
        filter_query = Q("ids", values=[client_doc.id])
        update_query = {"chats": chat_refs}
        self.database.clients.update_one(filter=filter_query, update=update_query)

        return chat_refs

    def get_unscraped_chat_ids(self, chat_ids: List[int]) -> List[int]:
        """Return only chat IDs where history has never been scraped.

        Queries for chats that are scraped (have history_updated_at) and subtracts
        from the input set, so chat IDs not yet in the index are correctly included.

        Args:
            chat_ids: List of Telegram chat IDs to filter.

        Returns:
            Subset of chat_ids where history_updated_at is not set.
        """
        if not chat_ids:
            return []
        results = self.database.chats.find(
            filter=Q("ids", values=chat_ids) & Q("exists", field="history_updated_at"),
        )
        scraped_ids = {int(chat.id) for chat in results if chat is not None}
        return [c for c in chat_ids if c not in scraped_ids]

    def get_chat_documents(
        self, chat_ids: List[int], fields: Optional[List[str]] = None
    ) -> Dict[int, Chat]:
        """Retrieve chat documents from database by IDs.

        Args:
            chat_ids: List of Telegram chat IDs to retrieve.
            fields: Optional list of specific fields to include in the response.
                   If None, returns all fields.

        Returns:
            Dictionary mapping chat_id to Chat document.
            Missing chats are not included in the result.
        """
        if not chat_ids:
            return {}

        filter_query = Q("ids", values=chat_ids)

        if fields:
            response = self.database.chats.find(
                filter=filter_query, fields={"includes": fields}
            )
        else:
            response = self.database.chats.find(filter=filter_query)

        chat_docs = {int(chat.id): chat for chat in response if chat is not None}

        return chat_docs

    @staticmethod
    async def get_chat_language(
        chat_id: int,
        chat_doc: Optional[Chat],
        tg_client: TelegramClient,
    ) -> Tuple[Optional[str], Optional[List[str]]]:
        """
        Asynchronously retrieves the language of a chat.

        This function attempts to determine the language of a chat by first checking the provided
        chat document. If the language is not found in the chat document, it fetches the 1000 most
        current messages of the chat history and uses a language detection algorithm to identify
        the language.

        Args:
            chat_id (int): The ID of the chat.
            chat_doc (Optional[Chat]): The chat document which may contain the language information.
            tg_client (TelegramClient): The Telegram client used to fetch the chat history.

        Returns:
            Tuple[Optional[str], Optional[List[str]]]: A tuple containing the primary language
            and a list of other detected languages, or (None, None) if the language could not be determined.
        """
        language = getattr(chat_doc, "language", None) if chat_doc else None
        language_other = getattr(chat_doc, "language_other", None) if chat_doc else None

        if language:
            return language, language_other

        logger.info(f"Detecting language for chat {chat_id}")
        text_list = []

        async for msg in fetch_chat_history(tg_client, chat_id, limit=1000):
            if hasattr(msg, "text") and msg.text:
                text_list.append(msg.text)
            elif hasattr(msg, "caption") and msg.caption:
                text_list.append(msg.caption)
        logger.info(f"Number of Messages with text: {len(text_list)}")
        if (
            len(text_list) < 10
        ):  # TODO: check if this is a good threshold for language detection. Consider using word count or confidence of the lang detector further down in code
            logger.warning(
                f"Could not detect language for chat {chat_id}. Defaulting to default language"
            )

            return None, None

        text_str = "\n".join(text_list)
        detector = _get_language_detector()

        languages = [
            result.language
            for result in detector.FindTopNMostFreqLangs(text_str, num_langs=3)
            if result.is_reliable
        ]
        language = languages[0] if languages else None
        language_other = languages[1:] if len(languages) > 1 else None

        return language, language_other
