"""Client management for Telegram scraping operations."""

from typing import List

from celery.utils.log import get_task_logger
from elasticsearch.dsl import Q
from pyrogram.client import Client as TelegramClient

from common.database.models.client import Client
from worker.database.database import Database
from worker.scraping.telegram_api.client import join_chat

logger = get_task_logger(__name__)


class ClientManager:
    """Manages Telegram client operations including initialization and validation.

    This class provides methods to retrieve active clients, initialize Telegram
    client connections, and manage chat joining operations.
    """

    def __init__(self, database: Database) -> None:
        """Initialize ClientManager with database connection.

        Args:
            database: Database instance for client operations.
        """
        self.database = database

    def get_active_clients(self) -> List[Client]:
        """Retrieve all active Telegram clients from the database.

        Returns:
            List of active Client documents. Empty list if no clients found.
        """
        filters = [Q("term", is_active=True), Q("exists", field="session_hash")]
        filter_query = Q("bool", filter=filters)
        active_clients = list(self.database.clients.find(filter=filter_query))

        if not active_clients:
            logger.info("No active Telegram clients found.")
        else:
            logger.info(f"Found {len(active_clients)} active Telegram clients")

        return active_clients

    def get_active_client_by_id(self, client_id: str) -> Client:
        """Retrieve an active client by ID with a valid session hash.

        Args:
            client_id: The client ID to search for.

        Returns:
            Active Client object.

        Raises:
            ValueError: If the client is not found, inactive, or has no valid session.
        """
        filter_query = ClientManager.build_active_client_query(client_id)
        db_client_doc = self.database.clients.find_one(filter=filter_query)

        if (
            not db_client_doc
            or not hasattr(db_client_doc, "session_hash")
            or not db_client_doc.session_hash
        ):
            raise ValueError(
                f"Active client {client_id} not found or has no valid session"
            )

        return db_client_doc

    @staticmethod
    def build_active_client_query(client_id: str):
        """Build query for finding an active client with valid session.

        Args:
            client_id: The client ID to query.

        Returns:
            Elasticsearch Query object for active client lookup.
        """
        filters = [
            Q("ids", values=[client_id]),
            Q("term", is_active=True),
            Q("exists", field="session_hash"),
        ]
        return Q("bool", filter=filters)

    @staticmethod
    def create_telegram_client(
        db_client_doc: Client, takeout: bool = False, no_updates: bool = True
    ) -> TelegramClient:
        """
        Creates and returns a TelegramClient instance based on the provided database client document.

        Args:
            db_client_doc (Client): The client document containing API credentials and session information.
            takeout (bool, optional): Whether to use Telegram's takeout feature. Defaults to False.
            no_updates (bool, optional): Whether to disable updates. Defaults to True.

        Returns:
            TelegramClient: An instance of the TelegramClient.

        Raises:
            Exception: If there is an error creating the Telegram client.
        """
        try:
            return TelegramClient(
                name=(
                    str(db_client_doc.api_id) + "." + db_client_doc.title
                    if db_client_doc.title
                    else str(db_client_doc.api_id)
                ),
                session_string=db_client_doc.session_hash,  # Implies in_memory=True
                api_id=db_client_doc.api_id,
                api_hash=db_client_doc.api_hash,
                takeout=takeout,
                no_updates=no_updates,
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to create Telegram client for {db_client_doc.id}"
            ) from e

    async def join_pending_chats(
        self, client_doc: Client, tg_client: TelegramClient
    ) -> None:
        """Join chats in the client's chats_to_join list and update database.

        Attempts to join all chats in client_doc.chats_to_join. Successfully
        joined chats are removed from the list in the database.

        Args:
            client_doc: Client document with chats_to_join list.
            tg_client: Active Pyrogram client connection.
        """
        if not client_doc.chats_to_join:
            return

        successfully_joined_chats = []

        for chat_id in client_doc.chats_to_join:
            try:
                await join_chat(tg_client, chat_id)
                successfully_joined_chats.append(chat_id)
                logger.info(f"Successfully joined chat {chat_id}")
            except Exception as e:
                logger.error(f"Error while joining chat {chat_id}: {e}")

        if successfully_joined_chats:
            filter_query = Q("ids", values=[client_doc.id])
            remaining_chats = list(
                set(client_doc.chats_to_join) - set(successfully_joined_chats)
            )
            update_query = {"chats_to_join": remaining_chats}
            self.database.clients.update_one(filter=filter_query, update=update_query)
            logger.info(
                f"Updated client {client_doc.id}: removed {len(successfully_joined_chats)} "
                f"successfully joined chats"
            )
