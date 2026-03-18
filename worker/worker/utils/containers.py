"""Shared data structures and containers for scraping operations."""

import time
from typing import Dict, List, Optional

from celery.utils.log import get_task_logger
from pydantic.main import BaseModel

from common.database.models.message import Message
from common.storage import Storage
from worker.database.database import Database, bson_to_json

ResultsContainerData = Dict[str, List[Dict]]

logger = get_task_logger(__name__)


class ResultsContainer:
    """
    Helper class to handle scraping results and perform database actions.
    """

    def __init__(
        self,
        size: int,
        keys: List[
            str
        ],  # Name of the indices ('chats', 'users', 'metrics', 'messages_*')
        database: Database,
        chat_id: Optional[str] = None,
    ) -> None:
        self.size = size
        self.keys = keys
        self.data: ResultsContainerData = {}
        self.database = database
        self.chat_id = chat_id

        self.clear_data()

    def clear_data(self) -> None:
        self.data = {key: [] for key in self.keys}

    def add(self, key: str, model: BaseModel) -> None:
        if key not in self.data:
            self.data[key] = []  # Initialize the key with an empty list

        # Append the model's dictionary representation to the list associated with the key
        self.data[key].append(
            model.model_dump(exclude_none=True, by_alias=True)
        )  # here we use by_alias=True in order to store _id instead of id

    def has(self, key: str, attribute: str, value) -> bool:
        """Check if any item in key's list has matching attribute value.

        Args:
            key: Data key to check within.
            attribute: Attribute name to check.
            value: Value to match.

        Returns:
            True if matching item found, False otherwise.
        """
        if key in self.data:
            return any(
                item[attribute] == value for item in self.data[key] if attribute in item
            )
        else:
            return False

    def count(self) -> int:
        return sum(len(results) for results in self.data.values())

    @property
    def is_full(self) -> bool:
        return self.count() >= self.size

    @staticmethod
    def generate_actions(key: str, documents: List[Dict], es_index: str) -> List[Dict]:
        """Generates a list of Elasticsearch actions based on the provided key and documents for use in a bulk operation.
        For messages and metrics, the action corresponds to an insert, while for users and chats, the action corresponds to
         an upsert."""
        collection_name_to_action_type = {
            "metrics": "index",
            "users": "index",
            "chats": "index",
        }

        # Determine if the key represents a message collection
        if key.startswith("messages_"):
            action_type = "create"  # Messages that were scraped already through another scraper are not being indexed;
            # With "index" we'd lose manually added fields like tags when simply overwriting the message object
            # This works because message updates are handled differently, not through ResultsContainer
            pipeline = "url_hashtag_pipeline"
        else:
            action_type = collection_name_to_action_type.get(key)
            pipeline = None

        def create_action(doc: Dict) -> Dict:
            """Create Elasticsearch action for a single document.

            Args:
                doc: Document dictionary to create action for.

            Returns:
                Elasticsearch action dictionary.
            """
            action = {
                "_op_type": action_type,
                "_index": es_index,
                "_source": bson_to_json(
                    {k: v for k, v in dict(doc).items() if k != "_id"}
                ),
            }
            # For metrics with type "message_posted", use message_id as the document ID to ensure uniqueness
            if key == "metrics":
                metadata = doc.get("metadata", {})
                if metadata.get("type") == "message_posted" and metadata.get(
                    "message_id"
                ):
                    action["_id"] = Message.create_id(
                        id_in_chat=metadata.get("message_id"),
                        chat_id=metadata.get("chat_id"),
                    )
                    # For other metric types, let Elasticsearch generate a random ID (no _id field)
            else:
                action["_id"] = str(doc["_id"])
            if pipeline:
                action["pipeline"] = pipeline
            return action

        return [create_action(doc) for doc in documents]

    def save_to_database(self, refresh: str) -> None:
        """
        Save documents to database. Count results of database transactions.
        Parameters:
        - refresh ("true" or "false"): refresh mode for Elasticsearch.
        """
        logger.info(f"Saving {self.count()} documents")

        for key, documents in self.data.items():
            if not documents:
                continue

            collection = self.database.get_collection_by_name(key)
            logger.info(f"Creating bulk actions for collection {collection.name}")
            requests = self.generate_actions(key, documents, collection.name)
            logger.info(f"Saving collection {collection.name} to database")
            successes, errors = collection.bulk_write(requests, refresh=refresh)

            # Only log remaining errors (conflicts are already handled in bulk_write)
            if len(errors) > 0:
                logger.error(f"Error saving documents to database: {errors}")
                raise RuntimeError(
                    f"Failed to save {len(errors)} documents to {collection.name}: {errors[:3]}"
                )


class StorageFileCache:
    """Per-task in-memory cache for storage file lookups.

    Each file is checked individually against storage via a prefix query and
    cached in memory to prevent duplicate queries within the same task run.
    """

    def __init__(self) -> None:
        self.cache: Dict[
            str, Dict[str, str]
        ] = {}  # {attachment_type: {unique_id: full_filename}}
        self.created_at = time.time()
        self.storage = Storage()

    async def file_exists(self, attachment_type: str, file_unique_id: str) -> bool:
        """Check if file exists in cache or storage."""
        if file_unique_id in self.cache.get(attachment_type, {}):
            return True

        # Import here to avoid circular dependency
        from worker.utils.helpers import bucket_name_from_attachment_type

        bucket_name = bucket_name_from_attachment_type(attachment_type)
        try:
            objects = self.storage.list_objects(bucket_name, prefix=file_unique_id + ".")
        except Exception as e:
            logger.warning(
                f"Error checking storage for {attachment_type}/{file_unique_id}: {e}"
            )
            return False

        if objects:
            self.cache.setdefault(attachment_type, {})[file_unique_id] = objects[0]
            return True

        return False

    def get_filename(self, attachment_type: str, file_unique_id: str) -> Optional[str]:
        """Get the full filename (with extension) for a file that exists in storage."""
        return self.cache.get(attachment_type, {}).get(file_unique_id)

    def add_file(
        self, attachment_type: str, file_unique_id: str, full_filename: str
    ) -> None:
        """Add a file to the cache."""
        if attachment_type not in self.cache:
            self.cache[attachment_type] = {}
        self.cache[attachment_type][file_unique_id] = full_filename
        logger.debug(
            f"Added {file_unique_id} -> {full_filename} to {attachment_type} storage cache"
        )

    def clear(self) -> None:
        """Clear the entire cache."""
        files_count = sum(len(file_dict) for file_dict in self.cache.values())
        self.cache.clear()
        logger.info(f"Cleared storage file cache ({files_count} files)")
