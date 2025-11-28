import asyncio
from pathlib import Path
from typing import List, Optional

import celery
from celery.utils.log import get_task_logger
from elasticsearch.dsl import Q
from pydantic import ValidationError
from pyrogram import filters
from pyrogram.client import Client as TelegramClient
from pyrogram.types import Message as TelegramMessage

from common.database.models.client import Client
from common.database.models.message import Message
from common.database.models.message.scraping_mode import ScrapingMode
from common.database.models.refs import ChatRef
from common.database.models.user import User
from common.settings import settings
from common.utils import get_or_create_event_loop, naive_utcnow
from worker import tasks
from worker.database.database import Database
from worker.main import app
from worker.scraping.managers.client_manager import ClientManager
from worker.scraping.managers.index_manager import IndexManager
from worker.scraping.managers.message_processor import (
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
from worker.scraping.services.scraping_service import ScrapingService
from worker.utils.containers import ResultsContainer
from worker.utils.helpers import add_users_if_enabled

TMP_PATH = Path().cwd().joinpath("tmp")
RESULTS_CONTAINER_SIZE = 1000

logger = get_task_logger(__name__)


class RetriableConnectionError(Exception):
    """Raised for connection/network errors that should trigger task retry."""

    pass


class NonRetriableError(Exception):
    """Raised for permanent errors (invalid data, missing files) that should be logged and skipped."""

    pass


@app.task(name="live.scrape_chats_live")
def scrape_chats_live(client_id: str) -> None:
    """
    Main task for live chat scraping with Telegram client.
    Includes new message and deletion handlers.

    Args:
        client_id (str): The ID of the client to use for scraping
    """
    database = None
    tg_client = None

    try:
        database = Database()
        client_manager = ClientManager(database)
        db_client_doc = client_manager.get_active_client_by_id(client_id)

        # Initialize Telegram client
        tg_client = ClientManager.create_telegram_client(
            db_client_doc=db_client_doc, takeout=False, no_updates=False
        )

        logger.info(f"Starting Telegram client {db_client_doc.title}")

        # Register handlers
        _register_handlers(tg_client, database, client_id)

        # Start client (this blocks until client stops)
        tg_client.run()

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise
    except ConnectionError as e:
        logger.error(f"Connection error: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error in scrape_chats_live: {e}", exc_info=True)
        raise
    finally:
        if database:
            try:
                database.close()
            except Exception as e:
                logger.warning(f"Error closing database connection: {e}")


def _register_handlers(
    tg_client: TelegramClient, database: Database, client_id: str
) -> None:
    """Register message and deletion handlers with the Telegram client."""
    try:
        # Register message handler
        message_handler = LiveMessageHandler(database, client_id)
        message_handler.register(tg_client)

        # Register deletion handler
        deletion_handler = LiveDeletionHandler(database, client_id)
        deletion_handler.register(tg_client)

        logger.info(f"Registered handlers for client {client_id}")

    except Exception as e:
        logger.error(f"Error registering handlers: {e}")
        raise


def create_active_client_filter(
    database: Database, client_id: str, tg_client: TelegramClient
):
    """Create a filter to check if client is still active.

    Args:
        database: Database instance for checking client status.
        client_id: ID of the client to check.
        tg_client: Telegram client to stop if filter fails.

    Returns:
        Pyrogram filter that checks if client is active.
    """

    async def active_client_filter(_, __, message) -> bool:
        try:
            filter_query = ClientManager.build_active_client_query(client_id)
            db_client_doc = database.clients.find_one(filter=filter_query)

            if not db_client_doc:
                logger.error(
                    f"Active client {client_id} not found or has no valid session - scheduling client stop"
                )
                # Schedule stop asynchronously to avoid deadlock
                asyncio.create_task(tg_client.stop())
                return False

            return True
        except Exception as e:
            logger.error(f"Error checking client status in filter: {e}", exc_info=True)
            return False

    return filters.create(active_client_filter)


class LiveMessageHandler:
    """Handles live message processing for a Telegram client."""

    def __init__(self, database: Database, client_id: str) -> None:
        """Initialize LiveMessageHandler.

        Args:
            database: Database instance for operations.
            client_id: ID of the Telegram client.
        """
        self.database = database
        self.client_id = client_id

    def register(self, tg_client: TelegramClient) -> None:
        """Register the message handler with the Telegram client."""

        @tg_client.on_message(
            filters=create_active_client_filter(
                self.database, self.client_id, tg_client
            )
        )
        async def handle_message(client, message: TelegramMessage):
            await self._handle_message(client, message)

    async def _handle_message(
        self, client: TelegramClient, message: TelegramMessage
    ) -> None:
        """
        Asynchronous handler for processing incoming Telegram messages.

        Args:
            client (pyrogram.Client): The Telegram client instance handling the message.
            message (pyrogram.types.Message): The incoming Telegram message object.
        """
        try:
            # Determine message type for logging
            msg_type = (
                "service"
                if message.service
                else (str(message.media.value) if message.media else "text")
            )
            has_content = " with content" if message.content else ""

            logger.info(
                f"Receiving new message {message.id} from chat {message.chat.id if message.chat else None} "
                f"(type: {msg_type}{has_content})"
            )
            logger.debug(
                f"Message content: {message.content[:40] if message.content else '[No content]'}"
            )

            # Extract media file_id if any
            file_id = None
            if message.media and message.media.value != "web_page":
                media_attr, file_id = self._extract_file_id(message)
                if not file_id:
                    logger.warning(
                        f"Media exists but no file_id found for message {message.id} with media type {media_attr or 'unknown'}."
                    )

            parse_result = self._parse_message(message)
            if parse_result:
                new_users, parsed_message = parse_result
                users_list = (
                    [user.model_dump() for user in new_users] if new_users else None
                )
                message_dict = parsed_message.model_dump()
                process_new_message.apply_async(
                    args=[self.client_id, users_list, message_dict, file_id]
                )

        except Exception as e:
            logger.error(f"Error in handle_message: {e}", exc_info=True)

    def _extract_file_id(self, message: TelegramMessage) -> tuple:
        """Extract file ID from message media."""
        if not message.media:
            return None, None

        media_attr = str(message.media.value)
        media = getattr(message, media_attr, None)

        if media and hasattr(media, "file_id"):
            return media_attr, str(media.file_id)
        return media_attr, None

    def _parse_message(
        self, message: TelegramMessage
    ) -> Optional[tuple[List[User], Message]]:
        """Parse Telegram message into domain objects."""
        return parse_and_validate_message(message, self.client_id)


class LiveDeletionHandler:
    """Handles live message deletion processing for a Telegram client."""

    def __init__(self, database: Database, client_id: str) -> None:
        """Initialize LiveDeletionHandler.

        Args:
            database: Database instance for operations.
            client_id: ID of the Telegram client.
        """
        self.database = database
        self.client_id = client_id

    def register(self, tg_client: TelegramClient) -> None:
        """Register the deletion handler with the Telegram client."""

        if settings.live_deletions == "ignore":
            return

        @tg_client.on_deleted_messages(
            filters=create_active_client_filter(
                self.database, self.client_id, tg_client
            )
        )
        async def handle_deleted_messages(
            client: TelegramClient, messages: List[Optional[TelegramMessage]]
        ):
            await self._handle_deleted_messages(client, messages)

    async def _handle_deleted_messages(
        self, client: TelegramClient, messages: List[Optional[TelegramMessage]]
    ) -> None:
        """Handle deleted messages from Telegram."""
        deletion_mode = settings.live_deletions
        if deletion_mode not in ["mark", "delete"]:
            return

        client_chat_ids = self._get_client_chat_ids()
        if not client_chat_ids:
            logger.warning(
                f"Couldn't find any chats for client {self.client_id}, skipping deletions"
            )
            return

        for tg_del_message in messages:
            if tg_del_message is None or tg_del_message.id is None:
                continue

            logger.info(f"Message with id {tg_del_message.id} was deleted in Telegram.")
            await self._process_single_deletion(
                client, tg_del_message, client_chat_ids, deletion_mode
            )

    def _get_client_chat_ids(self) -> List[int]:
        """Get chat IDs that this client is following."""
        try:
            client_doc = self.database.clients.find_one(
                filter=Q("ids", values=[self.client_id]), fields={"includes": ["chats"]}
            )

            if not client_doc or not client_doc.chats:
                return []

            chat_refs = [
                ChatRef(**chat) if isinstance(chat, dict) else chat
                for chat in client_doc.chats
            ]
            return [chat.id for chat in chat_refs]
        except Exception as e:
            logger.error(f"Error getting client chat IDs: {e}")
            return []

    async def _process_single_deletion(
        self,
        client: TelegramClient,
        tg_del_message: TelegramMessage,
        client_chat_ids: List[int],
        deletion_mode: str,
    ) -> None:
        """Process deletion of a single message."""
        # Find messages with this id_in_chat across followed chats
        found_messages = self._find_messages_by_id(tg_del_message.id, client_chat_ids)

        if not found_messages:
            logger.info(
                f"Message with id_in_chat {tg_del_message.id} not found in any followed chat"
            )
            return

        # Process each found message
        for chat_id, db_message in found_messages:
            await self._verify_and_delete_message(
                client, chat_id, db_message, tg_del_message.id, deletion_mode
            )

    def _find_messages_by_id(
        self, message_id: int, client_chat_ids: List[int]
    ) -> List[tuple]:
        """Find messages with the given id_in_chat across client's chats."""
        found_messages = []

        for chat_id in client_chat_ids:
            try:
                messages_index = self.database.get_messages_collection(chat_id)
                filter_query = Q("term", **{"id_in_chat": message_id})

                chat_messages = list(
                    messages_index.find(
                        filter=filter_query,
                        fields={"includes": ["date", "chat"]},
                    )
                )

                if chat_messages:
                    found_messages.extend([(chat_id, msg) for msg in chat_messages])

            except Exception as e:
                logger.error(f"Error searching chat {chat_id}: {e}")
                continue

        return found_messages

    async def _verify_and_delete_message(
        self,
        client: TelegramClient,
        chat_id: int,
        db_message,
        message_id: int,
        deletion_mode: str,
    ) -> None:
        """Verify deletion with Telegram and delete/mark message in database."""
        try:
            # Verify deletion with Telegram
            tg_message = await client.get_messages(
                chat_id=chat_id,
                message_ids=[int(message_id)],
                replies=0,
            )

            if not isinstance(tg_message, list):
                tg_message = [tg_message]

            message_is_deleted = self._check_if_message_deleted(tg_message)

            if message_is_deleted:
                await self._apply_deletion(chat_id, db_message, deletion_mode)
            else:
                logger.debug(
                    f"Message {message_id} of chat {chat_id} still exists on Telegram, skipping"
                )

        except Exception as e:
            logger.warning(
                f"Error processing deleted message {db_message.id} in chat {chat_id}: {e}"
            )

    def _check_if_message_deleted(self, tg_messages: List) -> bool:
        """Check if Telegram message is marked as empty, corresponding to is deleted."""
        for msg in tg_messages:
            if (isinstance(msg, dict) and msg.get("empty", False)) or (
                isinstance(msg, TelegramMessage) and msg.empty
            ):
                return True
        return False

    async def _apply_deletion(
        self, chat_id: int, db_message, deletion_mode: str
    ) -> None:
        """Apply the deletion action to the database message."""
        try:
            messages_index = self.database.get_messages_collection(chat_id)

            if deletion_mode == "mark":
                logger.info(
                    f"Marking message {db_message.id} of chat {chat_id} as deleted"
                )
                messages_index.update_one(
                    filter=Q("ids", values=[db_message.id]),
                    update={"deleted": naive_utcnow()},
                )
            elif deletion_mode == "delete":
                logger.info(f"Deleting message {db_message.id} of chat {chat_id}")
                messages_index.delete(ids=[db_message.id])

        except Exception as e:
            logger.error(
                f"Error applying deletion to message {db_message.id} in chat {chat_id}: {e}"
            )


@app.task(
    bind=True,
    name="live_processing.new_message",
    pydantic=True,
    autoretry_for=(RetriableConnectionError,),
    retry_backoff=True,
    retry_backoff_max=300,  # 5 minutes max backoff
    max_retries=3,
)
def process_new_message(
    self: celery.Task,
    client_id: str,
    users_list: Optional[List],
    message_dict: dict,
    file_id: Optional[str],
):
    """Process new live message.

    Args:
        self: Celery task instance.
        client_id: The identifier of the client associated with the message.
        users_list: A list of user dictionaries to be processed and stored.
        message_dict: A dictionary containing the message details.
        file_id: The file identifier for downloading attachments, if applicable.

    Raises:
        RetriableConnectionError: For connection errors that trigger retry.
    """
    try:
        loop = get_or_create_event_loop()
        return loop.run_until_complete(
            process_new_message_async(
                self, client_id, users_list, message_dict, file_id
            )
        )
    except RetriableConnectionError:
        # Re-raise to trigger Celery retry
        logger.warning(
            f"Connection error in process_new_message (attempt {self.request.retries + 1}/{self.max_retries + 1})"
        )
        raise
    except Exception as exc:
        logger.error(f"Unexpected error in process_new_message: {exc}", exc_info=True)
        raise


def _get_client_document(database: Database, client_id: str) -> Optional[Client]:
    """Retrieve client document from database.

    Args:
        database: Database instance.
        client_id: ID of the client to retrieve.

    Returns:
        Client document if found, None otherwise.
    """
    """Get and validate client document."""
    try:
        db_client_doc = database.clients.find_one(filter=Q("ids", values=[client_id]))
        if not db_client_doc:
            logger.error(f"Client {client_id} not found")
            return None
        return db_client_doc
    except Exception as e:
        logger.error(f"Error fetching client document: {e}")
        return None


async def _process_message_and_users(
    database: Database,
    message: Message,
    new_users: List[User],
    db_chat_doc,
    task: celery.Task,
    file_id: Optional[str],
    db_client_doc,
):
    """Process message, users, and optional attachments."""
    # Determine chat language
    chat_language = db_chat_doc.language if db_chat_doc else None

    # Initialize results container
    container = ResultsContainer(
        size=RESULTS_CONTAINER_SIZE,
        keys=["metrics", f"messages_{message.chat.id}", "users"],
        database=database,
    )

    # Set message metadata
    set_message_metadata(message, chat_language, ScrapingMode.LIVE)

    # Add "message_posted" metric to container
    add_message_metric(message, container)

    # Add users to container if enabled
    add_users_if_enabled(new_users, container)

    # Add message to container
    container.add(f"messages_{message.chat.id}", message)

    # Handle attachment downloads
    if attachment_download_enabled() and file_id:
        max_attachment_date = get_attachment_max_date()
        if valid_message_attachment(message, max_date=max_attachment_date):
            await _download_message_attachment(
                task, message, file_id, db_client_doc, database
            )

    # Save to database
    if container.count():
        try:
            container.save_to_database(refresh="true")
            logger.info(f"Processed message {message.id} from chat {message.chat.id}")
        except ConnectionError as e:
            # Connection errors - should retry
            logger.error(f"Connection error saving to database: {e}")
            raise RetriableConnectionError(f"Failed to save to database: {e}") from e
        except Exception as e:
            logger.error(
                f"Unexpected error saving container for chat {message.chat.id}: {e}",
            )
            raise


async def _download_message_attachment(
    task: celery.Task,
    message: Message,
    file_id: str,
    db_client_doc,
    database: Database,
):
    """Download attachment for a message.

    Attachment download failures are logged but do not fail the task.

    Args:
        task: Celery task instance.
        message: Parsed message object.
        file_id: Telegram file ID.
        db_client_doc: Client document from database.
        database: Database instance.
    """
    logger.info(f"Downloading attachment for message {message.id}")
    session_dir = TMP_PATH.joinpath("sessions", task.request.id, str(message.chat.id))

    try:
        tg_client = ClientManager.create_telegram_client(
            db_client_doc, takeout=False, no_updates=True
        )

        async with tg_client:
            downloaded_attachment = await download_single_attachment_from_telegram(
                session_dir=session_dir,
                tg_client=tg_client,
                parsed_message=message,
                tg_message_or_file_id=file_id,
                file_cache=None,
            )

            if downloaded_attachment:
                tasks.process_attachments.s(
                    attachments=[downloaded_attachment], chat_id=message.chat.id
                ).apply_async()

                # Cleanup session directory
                if session_dir.exists() and session_dir.is_dir():
                    try:
                        session_dir.rmdir()
                    except OSError as e:
                        logger.error(f"Error removing directory {session_dir}: {e}")
            else:
                logger.error(
                    f"Failed to download attachment for live message {message.id}"
                )

    except Exception as e:
        logger.error(
            f"Error downloading attachment for message {message.id}: {e}",
            exc_info=True,
        )


async def process_new_message_async(
    task: celery.Task,
    client_id: str,
    users_list: Optional[List],
    message_dict: dict,
    file_id: Optional[str],
):
    """
    Processes a new live message asynchronously, handling database updates,
    user and message storage, and optional attachment downloads.

    Args:
        task (celery.Task): The Celery task instance associated with the message processing.
        client_id (str): The identifier of the client associated with the message.
        users_list (Optional[List]): A list of user dictionaries to be processed and stored.
        message_dict (dict): A dictionary containing the message details.
        file_id (Optional[str]): The file identifier for downloading attachments, if applicable.

    Workflow:
        1. Initializes the database and constructs a Message object from the provided dictionary.
        2. Validates the client and chat documents in the database.
        3. Prepares indices for scraping if the chat document or message index does not exist.
        4. Saves users and the message to the results container.
        5. Optionally downloads message attachments if configured in the settings.
        6. Saves the results container to the database.
    """
    database = None

    try:
        try:
            database = Database()
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise RetriableConnectionError(
                f"Database initialization failed: {e}"
            ) from e

        index_manager = IndexManager(database)
        message: Message = Message(**message_dict)

        new_users = []
        if users_list:
            new_users = [User(**user) for user in users_list]

        # Validate client
        db_client_doc = _get_client_document(database, client_id)
        if not db_client_doc:
            raise RuntimeError(f"Client {client_id} not found")

        # Ensure chat is prepared (handles new chats in live scraping)
        chat_id = message.chat.id
        db_chat_doc = database.chats.find_one(
            filter=Q("ids", values=[str(chat_id)]),
            fields={"includes": ["language"]},
        )
        needs_prep = index_manager.chat_indices_need_preparation(chat_id, db_chat_doc)

        if needs_prep:
            # Create temporary client for preparation only if needed
            scraping_service = ScrapingService(database)
            tg_client = ClientManager.create_telegram_client(
                db_client_doc, takeout=False, no_updates=True
            )

            if not tg_client:
                logger.error(f"Failed to create temporary client for chat {chat_id}")
                raise RuntimeError(f"Failed to create client for chat {chat_id}")

            async with tg_client:
                db_chat_doc = await scraping_service.ensure_chat_ready(
                    tg_client=tg_client,
                    client_doc=db_client_doc,
                    chat_id=chat_id,
                )

        if not db_chat_doc:
            logger.error(
                f"Failed to prepare chat {chat_id}, skipping message {message.id}"
            )
            raise RuntimeError(f"Failed to prepare chat {chat_id}")

        # Process message
        await _process_message_and_users(
            database,
            message,
            new_users,
            db_chat_doc,
            task,
            file_id,
            db_client_doc,
        )

    except ValidationError as e:
        logger.error(f"Validation error processing message: {e}")
        # Validation errors are permanent - fail the task
        raise
    except ConnectionError as e:
        logger.error(f"Connection error processing message: {e}")
        # Re-raise as RetriableConnectionError to trigger retry
        raise RetriableConnectionError(f"Connection error: {e}") from e
    except Exception as e:
        logger.error(f"Error processing live message: {e}", exc_info=True)
        # Unexpected errors - fail the task
        raise
