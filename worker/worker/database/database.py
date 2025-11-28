import base64
from datetime import datetime
from typing import (
    Any,
    Dict,
    Generic,
    Iterator,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
)

from celery.utils.log import get_task_logger
from elasticsearch import Elasticsearch, NotFoundError
from elasticsearch.dsl import Index, Q, Search
from elasticsearch.dsl.query import Query
from elasticsearch.helpers import BulkIndexError, bulk

from common.database.models.chat import Chat
from common.database.models.client import Client
from common.database.models.message import Message
from common.database.models.metric import Metric
from common.database.models.user import User
from common.settings import settings

logger = get_task_logger(__name__)

T = TypeVar("T", Client, Chat, Message, User, Metric)


class Collection(Generic[T]):
    """Generic collection class for Elasticsearch index operations.

    Provides type-safe CRUD operations for Elasticsearch indices using Pydantic models.
    Subclasses must define 'name' and 'model' class attributes.
    """

    name: str
    model: Type[T]

    def __init__(self, client: Elasticsearch, name: Optional[str] = None) -> None:
        """Initialize collection with Elasticsearch client.

        Args:
            client: Elasticsearch client instance
            name: Optional index name override (defaults to class-level name)

        Raises:
            ValueError: If name or model is not provided
        """
        self.client = client
        self.name = name or self.name
        self.index = Index(self.name)
        self.index._get_connection(using=self.client)

        if not self.model or not self.name:
            raise ValueError(
                "Error initializing collection. Name or model not provided."
            )

    def __transform_document(self, doc: Dict[str, Any]) -> T:
        """Transform Elasticsearch document to Pydantic model.

        Uses model_construct to allow partial documents with excluded fields.

        Args:
            doc: Raw document dictionary from Elasticsearch

        Returns:
            Typed model instance
        """
        return self.model.model_construct(
            **doc
        )  # can't use model_validate here cause then exclusions of mandatory fields in an ES query are not allowed

    def _get_match_response(
        self,
        search_query: Optional[Query] = None,
        filter: Optional[Query] = None,
        sort: Optional[List[Dict[str, str]]] = None,
        fields: Optional[Dict[str, List[str]]] = None,
        size: Optional[int] = None,
    ):
        """Execute Elasticsearch query with optional filters, sorting, and field selection.

        Args:
            search_query: Main query (e.g., match, term)
            filter: Filter query for post-filtering results
            sort: List of sort criteria with field and order
            fields: Dict with 'includes' and/or 'excludes' field lists
            size: Maximum number of results to return

        Returns:
            Elasticsearch response object

        Raises:
            RuntimeError: If index not found or query fails
        """
        search = Search(using=self.client, index=self.name)

        if search_query:
            search = search.query(search_query)

        if filter:
            search = search.filter(filter)

        if fields:
            if "includes" in fields:
                search = search.source(includes=fields["includes"])
            if "excludes" in fields:
                search = search.source(excludes=fields["excludes"])

        # Apply sorting if specified
        if sort:
            sort_fields = []
            for item in sort:
                field = item["field"]
                order = item.get("order", "asc")  # Default to 'asc' if not specified
                sort_fields.append({field: {"order": order, "missing": "_last"}})
                logger.debug(f"Sorting by field: {field}")

            search = search.sort(*sort_fields)

        if size:
            search = search.extra(size=size)

        try:
            response = search.execute()
        except NotFoundError as e:
            raise RuntimeError(
                f"Index '{self.name}' not found in Elasticsearch."
            ) from e
        except Exception as e:
            logger.error("Elasticsearch query error: %s", e)
            raise

        return response

    def find_one(
        self,
        search_query: Optional[Query] = None,
        filter: Optional[Query] = None,
        sort: Optional[List[Dict[str, str]]] = None,
        fields: Optional[Dict[str, List[str]]] = None,
    ) -> Optional[T]:
        """Find a single document matching the query.

        Args:
            search_query: Main query to match documents
            filter: Additional filter query
            sort: Sort criteria (first result will be returned)
            fields: Field inclusion/exclusion specification

        Returns:
            Matched document as typed model, or None if not found
        """
        response = self._get_match_response(
            search_query=search_query, filter=filter, sort=sort, fields=fields, size=1
        )
        if not response.hits:
            return None

        doc = response.hits[0].to_dict()
        doc["id"] = response.hits[0].meta.id
        return self.__transform_document(doc)

    def find(
        self,
        search_query: Optional[Query] = None,
        filter: Optional[Query] = None,
        sort: Optional[List[Dict[str, str]]] = None,
        fields: Optional[Dict[str, List[str]]] = None,
        size: Optional[int] = 10000,
    ) -> Iterator[T]:
        """Find multiple documents matching the query.

        Args:
            search_query: Main query to match documents
            filter: Additional filter query
            sort: Sort criteria for results
            fields: Field inclusion/exclusion specification
            size: Maximum results (default 10000, ES max_result_window limit)

        Returns:
            Iterator of matched documents as typed models

        Raises:
            RuntimeError: If index not found or query fails
        """
        response = self._get_match_response(
            search_query=search_query,
            filter=filter,
            sort=sort,
            fields=fields,
            size=size,
        )

        return (
            self.__transform_document({**hit.to_dict(), "id": hit.meta.id})
            for hit in response.hits
        )

    def update_one(
        self,
        update: Dict[str, Any],
        search_query: Optional[Query] = None,
        filter: Optional[Query] = None,
    ) -> None:
        """Update a single document matching the query.

        Args:
            update: Dictionary of fields to update
            search_query: Query to find document
            filter: Additional filter query

        Raises:
            ValueError: If no document matches the criteria
            RuntimeError: If query or update fails
        """
        search = Search(using=self.client, index=self.name)
        if search_query:
            search = search.query(search_query)

        if filter:
            search = search.filter(filter)

        try:
            response = search.execute()
        except Exception as e:
            raise RuntimeError(f"Elasticsearch query error: {e}") from e

        if not response.hits:
            raise ValueError(
                f"No document found in index '{self.name}' matching the criteria to update."
            )

        doc_id = response.hits[0].meta.id

        try:
            self.client.update(index=self.name, id=str(doc_id), body={"doc": update})
            logger.debug(f"Updated document {doc_id} in index '{self.name}'")
        except Exception as e:
            logger.error(
                f"Error updating document {doc_id} in index '{self.name}': {e}"
            )
            raise

    def bulk_write(
        self, actions: List[Dict[str, Any]], refresh: str
    ) -> Tuple[int, List[Dict[str, Any]]]:
        """Perform bulk write operations in Elasticsearch.

        Handles document creation/indexing in bulk with special handling for
        409 conflicts in message indices (treating duplicates as expected).

        Args:
            actions: List of bulk action dictionaries
            refresh: Refresh mode ('true', 'wait_for', or 'false')

        Returns:
            Tuple of (success_count, error_list)
        """
        try:
            successes, errors = bulk(self.client, actions=actions, refresh=refresh)
            if not isinstance(errors, list):
                errors = []  # Convert to empty list if no errors occurred
        except BulkIndexError as e:
            successes = len(actions) - len(e.errors)
            errors = e.errors

            # NOTE: We treat 409 conflicts (duplicate messages) as expected when using bulk "create".
            # Elasticsearch returns them as errors, but they indicate the message was already ingested.
            # If ES behavior changes (e.g. configurable ignore for bulk create), this block can be removed.
            if self.name.startswith("messages_"):
                conflicts = []
                actual_errors = []
                conflict_ids = []

                for error in errors:
                    # Check if it's a 409 conflict (document already exists)
                    if (
                        isinstance(error, dict)
                        and error.get("create", {}).get("status") == 409
                    ):
                        conflicts.append(error)
                        # Extract the document ID from the error
                        doc_id = error.get("create", {}).get("_id", "unknown")
                        conflict_ids.append(doc_id)
                    else:
                        actual_errors.append(error)

                if conflicts:
                    logger.warning(
                        f"Skipped {len(conflicts)} duplicate messages in '{self.name}': "
                        f"{conflict_ids[:3]}{'...' if len(conflict_ids) > 3 else ''}"
                    )

                if actual_errors:
                    logger.error(
                        f"Bulk indexing failed for '{self.name}': {len(actual_errors)} actual errors"
                    )
                else:
                    logger.debug(
                        f"Bulk indexing completed for '{self.name}' with {len(conflicts)} expected conflicts"
                    )

                errors = actual_errors
            else:
                logger.error(
                    f"Bulk indexing failed for '{self.name}': {len(e.errors)} errors"
                )

        return successes, errors

    def delete_by_query(self, query: Query) -> None:
        """Delete all documents matching a query.

        Args:
            query: Elasticsearch query to match documents for deletion

        Raises:
            Exception: If deletion fails
        """
        logger.info(f"Deleting documents matching query from index '{self.name}'")
        try:
            s = Search(using=self.client, index=self.name).query(query)
            s.delete()
        except Exception as e:
            logger.error(f"Error deleting documents by query: {e}")
            raise

    def delete(self, ids: Optional[List[Union[str, int]]] = None) -> None:
        """Delete documents by IDs, or all documents if none provided.

        Args:
            ids: Optional list of document IDs to delete.
                 If None, deletes all documents in the index.

        Raises:
            Exception: If deletion fails
        """
        if ids is not None:
            if not ids:
                logger.warning("No IDs provided for deletion")
                return

            logger.info(
                f"Deleting {len(ids)} documents by IDs from index '{self.name}'"
            )
            query = Q("ids", values=ids)
        else:
            logger.info(f"Deleting all documents from index '{self.name}'")
            query = Q("match_all")

        try:
            s = Search(using=self.client, index=self.name).query(query)
            s.delete()
        except Exception as e:
            logger.error(f"Error deleting documents: {e}")
            raise


class ClientsCollection(Collection[Client]):
    """Collection for Telegram client configurations."""

    name = "clients"
    model = Client


class ChatsCollection(Collection[Chat]):
    """Collection for Telegram chats/channels."""

    name = "chats"
    model = Chat


class MessagesCollection(Collection[Message]):
    """Collection for messages in a specific chat.

    Each chat has its own dedicated messages index (messages_{chat_id}).
    """

    model = Message

    def __init__(self, client: Elasticsearch, chat_id: Union[str, int]) -> None:
        """Initialize messages collection for a specific chat.

        Args:
            client: Elasticsearch client instance
            chat_id: Unique identifier for the chat
        """
        index_name = f"messages_{chat_id}"
        super().__init__(client, index_name)


class UsersCollection(Collection[User]):
    """Collection for Telegram users."""

    name = "users"
    model = User


class MetricsCollection(Collection[Metric]):
    """Collection for scraping metrics and statistics."""

    name = "metrics"
    model = Metric


class Database:
    """Database facade providing access to all Elasticsearch collections.

    Manages Elasticsearch client lifecycle and provides type-safe access
    to all document collections (clients, chats, messages, users, metrics).
    """

    def __init__(self) -> None:
        """Initialize database connection and collections.

        Raises:
            ConnectionError: If unable to connect to Elasticsearch
        """
        self.es_client = Elasticsearch(
            hosts=[f"{settings.es_scheme}://{settings.es_host}:{settings.es_port}"]
        )
        self.clients = ClientsCollection(self.es_client)
        self.chats = ChatsCollection(self.es_client)
        self.messages_collections: Dict[str, MessagesCollection] = {}
        self.users = UsersCollection(self.es_client)
        self.metrics = MetricsCollection(self.es_client)

        if not self.es_client.ping():
            raise ConnectionError(
                f"Could not connect to Elasticsearch at {settings.es_scheme}://{settings.es_host}:{settings.es_port}"
            )

    def find_all_message_indices(self) -> List[str]:
        """Find all message indices in Elasticsearch.

        Returns:
            List of index names starting with 'messages_'
        """
        try:
            indices = self.es_client.indices.get(index="messages_*")
            return list(indices.keys())
        except Exception as e:
            logger.error(f"Error retrieving message indices: {e}")
            return []

    def get_messages_collection(self, chat_id: Union[str, int]) -> MessagesCollection:
        """Get or create messages collection for a specific chat.

        Collections are cached to avoid recreating them for repeated access.

        Args:
            chat_id: Unique identifier for the chat

        Returns:
            MessagesCollection instance for the specified chat
        """
        chat_id = str(chat_id)
        if chat_id not in self.messages_collections:
            self.messages_collections[chat_id] = MessagesCollection(
                self.es_client, chat_id
            )
        return self.messages_collections[chat_id]

    def check_messages_index_exists(self, chat_id: Union[str, int]) -> bool:
        """Check if a message index exists for a specific chat.

        Args:
            chat_id: Unique identifier for the chat

        Returns:
            True if index exists, False otherwise
        """
        index_name = f"messages_{chat_id}"
        return bool(self.es_client.indices.exists(index=index_name))

    def get_collection_by_name(
        self, name: str
    ) -> Union[
        ClientsCollection,
        ChatsCollection,
        MessagesCollection,
        UsersCollection,
        MetricsCollection,
    ]:
        """Retrieve a collection by its index name.

        Handles both static collections (clients, chats, users, metrics) and
        dynamic message collections (messages_{chat_id}).

        Args:
            name: Index name (e.g., 'clients', 'chats', 'messages_123')

        Returns:
            Corresponding collection instance

        Raises:
            AttributeError: If collection name is invalid
        """
        if name.startswith("messages_"):
            chat_id = name.split("_", 1)[1]
            return self.get_messages_collection(chat_id)
        return getattr(self, name)

    def close(self) -> None:
        """Close the Elasticsearch client connection.

        Should be called when the database instance is no longer needed
        to properly release resources.
        """
        self.es_client.close()
        logger.debug("Elasticsearch connection closed")


def bson_to_json(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Convert document to JSON-compatible dictionary.

    Converts Python types (datetime, bytes) to JSON-serializable formats
    for Elasticsearch indexing.

    Args:
        doc: Dictionary potentially containing non-JSON types

    Returns:
        Dictionary with all values converted to JSON-serializable types
    """

    def process_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: process_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [process_value(v) for v in value]
        elif isinstance(value, bytes):
            return base64.b64encode(value).decode("utf-8")  # Convert bytes to Base64
        elif isinstance(value, datetime):
            return value.isoformat()  # Convert datetime to ISO 8601 string
        else:
            return value

    return process_value(doc)
