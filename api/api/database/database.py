import logging
from typing import (
    Any,
    AsyncIterator,
    Dict,
    Generic,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
    cast,
)
from uuid import UUID

from elasticsearch import AsyncElasticsearch, ConnectionTimeout, NotFoundError
from elasticsearch.dsl import AsyncSearch, Index, Q
from elasticsearch.dsl.query import Query
from elasticsearch.dsl.response import Response
from elasticsearch.helpers import async_bulk
from pydantic import BaseModel

from api.fulltext_search import HighlightConfig
from api.sort_config import SortOptions, SortParams
from api.validators import FieldFilter
from common.database.models.chat import ChatOut
from common.database.models.client import ClientOut
from common.database.models.message import MessageOut
from common.database.models.metric import Metric
from common.database.models.user import UserOut
from common.settings import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", ClientOut, ChatOut, MessageOut, UserOut, Metric)


class StatsEntry(BaseModel):
    value: str
    count: int


class Collection(Generic[T]):
    name: str
    model: Type[T]

    def __init__(self, client: AsyncElasticsearch) -> None:
        """Initialize the collection with an Elasticsearch client."""
        self.client = client
        self.index = Index(self.name)

        if not self.model or not self.name:
            raise Exception(
                "Error initializing collection. Name or model not provided."
            )

    def __transform_document(self, doc: Dict[str, Any]) -> T:
        """Transform a raw Elasticsearch document into a typed model instance."""
        return self.model.model_validate(doc)

    async def _get_match_response(
        self,
        search_query: Optional[Query] = None,
        filter: Optional[Query] = None,
        sort: Optional[SortParams[SortOptions]] = None,
        fields: Optional[FieldFilter] = None,
        size: Optional[int] = None,
        from_: Optional[int] = None,
        highlight: Optional[HighlightConfig] = None,
    ) -> Response:
        """Execute an Elasticsearch search and return the raw response."""
        search = AsyncSearch(using=self.client, index=self.name)
        if search_query:
            search = search.query(search_query)

        search = search.extra(track_scores=True)  # ensure score is always computed

        if filter:
            search = search.filter(filter)
        if fields:
            if "includes" in fields:
                search = search.source(includes=fields["includes"])
            if "excludes" in fields:
                search = search.source(excludes=fields["excludes"])
        if sort:
            sort_fields = []
            for item in sort:
                field = item.sort_by.value
                logger.debug(f"Sorting by field: {field}")
                if field == "score":
                    sort_fields.append({"_score": {"order": item.order.value}})
                else:
                    sort_fields.append(
                        {field: {"order": item.order.value, "missing": "_last"}}
                    )

            search = search.sort(*sort_fields)

        if size:
            search = search.extra(size=size)

        if from_:
            search = search.extra(from_=from_)

        if highlight and "fields" in highlight:
            for field, config in highlight["fields"].items():
                search = search.highlight(field, **config)

        try:
            response = await search.execute()
        except Exception as e:
            logger.error(f"Elasticsearch query error: {e}", exc_info=True)
            raise

        return response

    async def find_one(
        self,
        search_query: Optional[Query] = None,
        filter: Optional[Query] = None,
        sort: Optional[SortParams] = None,
        fields: Optional[FieldFilter] = None,
    ) -> Optional[T]:
        """Find and return a single document matching the query."""
        response = await self._get_match_response(
            search_query, filter, sort, fields, size=1
        )
        if not response.hits:
            return None
        doc = cast(Dict[str, Any], response.hits[0].to_dict())
        doc["id"] = response.hits[0].meta.id
        return self.__transform_document(doc)

    async def find(
        self,
        search_query: Optional[Query] = None,
        filter: Optional[Query] = None,
        sort: Optional[SortParams] = None,
        fields: Optional[FieldFilter] = None,
        size: Optional[int] = 10000,
        from_: Optional[int] = None,
        highlight: Optional[HighlightConfig] = None,
    ) -> AsyncIterator[T]:
        """Find and yield multiple documents matching the query."""
        response = await self._get_match_response(
            search_query,
            filter,
            sort,
            fields,
            size,
            from_,
            highlight,
        )
        for hit in response.hits:
            doc = hit.to_dict()
            doc["id"] = hit.meta.id
            if hasattr(hit.meta, "highlight"):
                doc["highlight"] = hit.meta.highlight.to_dict()
            if hasattr(hit.meta, "score"):
                doc["score"] = hit.meta.score
            if hasattr(hit, "classification") and hasattr(
                hit.classification, "score_pos"
            ):
                doc["classification_score_pos"] = hit.classification.score_pos
            yield self.__transform_document(
                cast(Dict[str, Any], doc)
            )  # Using yield to lazily return validated documents

    async def count(
        self, search_query: Optional[Query] = None, filter: Optional[Query] = None
    ) -> int:
        """Count the number of documents matching the query."""
        search = AsyncSearch(using=self.client, index=self.name)

        if search_query:
            search = search.query(search_query)
        else:  # Note: match_all might be implicit - test if this can be simplified
            search = search.query(Q("match_all"))
        if filter:
            search = search.filter(filter)
        response = await search.count()
        return response

    async def update_one(
        self, query: Query, update: Dict, refresh: Optional[bool] = True
    ) -> Optional[T]:
        """
        Update a single document based on the given query and update dict, and return the updated document.
        Note: Consider implementing update_by_id variant and update_many support.
        """
        # Note: Could potentially reuse find_one logic here
        search = AsyncSearch(using=self.client, index=self.name).query(query)

        try:
            response = await search.execute()
        except Exception as e:
            logger.error(f"Elasticsearch query error: {e}", exc_info=True)
            raise

        if not response.hits:
            logger.warning("No document found to update")
            return None

        doc_id = response.hits[0].meta.id
        doc_index = response.hits[0].meta.index

        update_response = await self.client.update(
            index=doc_index, id=doc_id, body={"doc": update}, refresh=refresh
        )
        if update_response.get("result") == "updated":
            updated_doc = await self.find_one(filter=Q("ids", values=[str(doc_id)]))
            return updated_doc
        else:
            logger.warning(f"Document with ID {doc_id} not updated")
            return None

    async def bulk_write(self, actions: List[Dict]) -> Tuple[int, List[Dict[str, Any]]]:
        """Execute a bulk write operation and return success count and errors."""
        successes, errors = await async_bulk(self.client, actions=actions)
        if isinstance(errors, int):
            errors = []  # Convert to empty list if it's an integer which happens when no errors
        return successes, errors

    async def delete_by_query(self, query: Optional[Query] = None) -> int:
        """
        Delete documents matching the query. If no query is provided, deletes all documents.

        Args:
            query: Elasticsearch query to match documents for deletion.
                   If None, defaults to match_all (deletes all documents).

        Returns:
            Number of documents deleted
        """
        if query is None:
            query = Q("match_all")  # defaults to "match_all" if no query is provided

        try:
            s = AsyncSearch(using=self.client, index=self.name).query(query)
            response = await s.delete()
            # The delete() method returns an ObjectApiResponse with 'deleted' count
            if hasattr(response, "deleted"):
                deleted_count = response.deleted
            else:
                deleted_count = 0
            return deleted_count
        except Exception as e:
            logger.error(f"Error deleting documents: {e}", exc_info=True)
            raise

    async def insert_one(
        self,
        document: Dict[str, Any],
        id: Optional[UUID] = None,
        refresh: Optional[bool] = True,
    ) -> Optional[str]:
        """Insert a single document and return its ID."""
        response = await self.client.index(
            index=self.name,
            id=str(id),
            body=document,
            refresh=refresh,
        )

        doc_id = response["_id"]
        logger.debug(f"Document inserted with ID: {doc_id}")
        return doc_id  # Note: Currently returns only ID; could return full ES response if needed

    async def get_top_field_values(
        self,
        field: str,
        search_query: Optional[Query] = None,
        filter: Optional[Query] = None,
        size: Optional[int] = None,
    ) -> List[StatsEntry]:
        """
        Get unique field values from the index, ordered by frequency.

        Args:
            field: The field to perform the aggregation on (e.g., 'hashtags', 'tags').
            search_query: An optional search query to filter documents.
            filter: An optional filter to further refine the documents.
            size: Maximum number of unique terms to retrieve. If None, uses Elasticsearch default (10).

        Returns:
            List[str]: List of unique field values ordered by frequency.

        Examples:
            # Get top 10 unique tags (default)
            tags = await collection.get_top_field_values("tags")

            # Get top 20 hashtags
            hashtags = await collection.get_top_field_values("hashtags", size=20)
        """
        try:
            search = AsyncSearch(using=self.client, index=self.name)

            if search_query:
                search = search.query(search_query)
            if filter:
                search = search.filter(filter)

            # Only set size if explicitly provided
            if size is not None:
                search.aggs.bucket("field_terms", "terms", field=field, size=size)
            else:
                search.aggs.bucket("field_terms", "terms", field=field)

            response = await search.execute()

            field_terms_buckets = response.aggregations.field_terms.buckets

            return [
                StatsEntry(value=str(bucket.key), count=int(bucket.doc_count))
                for bucket in field_terms_buckets
                if isinstance(bucket.key, (str, int, float, bool))
                and isinstance(bucket.doc_count, (str, int))
            ]

        except Exception as e:
            logger.error(
                f"Failed to retrieve field aggregation for field {field}: {str(e)}",
                exc_info=True,
            )
            return []

    async def delete_by_id(
        self, doc_id: str, refresh: Optional[bool] = True
    ) -> Optional[T]:
        """
        Delete a single document by its ID and return the deleted document.

        Args:
            doc_id: The ID of the document to delete.
            refresh: If True, refresh the index after deletion to make it visible immediately.

        Returns:
            The deleted document, or None if no document was found.
        """
        doc_to_delete = await self.find_one(filter=Q("ids", values=[doc_id]))

        if not doc_to_delete:
            logger.warning(f"No document found with ID {doc_id}")
            return None

        try:
            delete_response = await self.client.delete(
                index=self.name, id=doc_id, refresh=refresh
            )
            if delete_response.get("result") == "deleted":
                return doc_to_delete
            else:
                logger.warning(f"Failed to delete document with ID {doc_id}")
                return None

        except NotFoundError:
            logger.warning(f"Document with ID {doc_id} not found")
            return None

        except Exception as e:
            logger.error(f"Elasticsearch deletion error: {e}", exc_info=True)
            raise


class ClientsCollection(Collection[ClientOut]):
    name = "clients"
    model = ClientOut


class ChatsCollection(Collection[ChatOut]):
    name = "chats"
    model = ChatOut


class MessagesCollection(Collection[MessageOut]):
    name = "messages"
    model = MessageOut


class UsersCollection(Collection[UserOut]):
    name = "users"
    model = UserOut


class MetricsCollection(Collection[Metric]):
    name = "metrics"
    model = Metric


class Database:
    def __init__(self, connect=True) -> None:
        """Initialize the Database. If connect is True, establishes connection immediately."""
        if connect:
            self.connect()

    def connect(self) -> None:
        """
        Establish a connection to the Elasticsearch cluster.
        """
        try:
            # Initialize the Elasticsearch client
            self.es_client = AsyncElasticsearch(
                hosts=[f"{settings.es_scheme}://{settings.es_host}:{settings.es_port}"],
                request_timeout=30,  # Adjust as needed
                max_retries=10,  # Adjust as needed
                retry_on_timeout=True,
            )
            logger.info("Elasticsearch client initialized successfully.")
            self.clients = ClientsCollection(self.es_client)
            self.chats = ChatsCollection(self.es_client)
            self.messages = MessagesCollection(self.es_client)
            self.users = UsersCollection(self.es_client)
            self.metrics = MetricsCollection(self.es_client)
        except ConnectionError as e:
            logger.error(f"Error connecting to Elasticsearch: {e}", exc_info=True)
            raise
        except ConnectionTimeout as e:
            logger.error(f"Elasticsearch connection timeout: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(
                f"An error occurred while connecting to Elasticsearch: {e}",
                exc_info=True,
            )
            raise

    def get_collection_by_name(self, name: str) -> Collection:
        """Get a collection by its name (e.g., 'clients', 'chats', 'messages')."""
        return getattr(self, name)

    async def close(self) -> None:
        """Close the Elasticsearch client connection."""
        await self.es_client.close()
