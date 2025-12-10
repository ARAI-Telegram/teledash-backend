"""
Unit tests for the Database and Collection classes.

Testing includes:
- Mock AsyncElasticsearch client to prevent actual network calls
- Test all CRUD operations
- Test error handling scenarios
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from elastic_transport import ApiResponseMeta, HttpHeaders, NodeConfig
from elasticsearch import NotFoundError
from elasticsearch.dsl import Q

from api.database.database import ChatsCollection, Database, StatsEntry
from common.database.models.chat import ChatOut, ChatType


class TestDatabaseConnection:
    """Test cases for Database connection and initialization."""

    @patch("api.database.database.AsyncElasticsearch")
    def test_database_connect_success(self, mock_es_class):
        """Test successful database connection initializes all collections."""
        mock_client = AsyncMock()
        mock_es_class.return_value = mock_client

        db = Database(connect=True)

        # Verify Elasticsearch client was initialized
        mock_es_class.assert_called_once()

        # Verify all collections are initialized
        assert db.clients is not None
        assert db.chats is not None
        assert db.messages is not None
        assert db.users is not None
        assert db.metrics is not None

    @patch("api.database.database.AsyncElasticsearch")
    def test_database_connect_false_skips_initialization(self, mock_es_class):
        """Test that connect=False skips client initialization."""
        db = Database(connect=False)

        # Verify Elasticsearch client was not called
        mock_es_class.assert_not_called()

        # Database should not have es_client attribute
        assert not hasattr(db, "es_client")

    @patch("api.database.database.AsyncElasticsearch")
    def test_database_get_collection_by_name(self, mock_es_class):
        """Test retrieving collections by name."""
        mock_client = AsyncMock()
        mock_es_class.return_value = mock_client

        db = Database(connect=True)

        assert db.get_collection_by_name("chats") == db.chats
        assert db.get_collection_by_name("clients") == db.clients
        assert db.get_collection_by_name("messages") == db.messages


class TestCollectionFindOne:
    """Test cases for Collection.find_one method."""

    @pytest.fixture
    def collection_with_mock_client(self):
        """Create a ChatsCollection with mocked ES client."""
        mock_client = AsyncMock()
        collection = ChatsCollection(mock_client)
        return collection, mock_client

    @pytest.mark.asyncio
    async def test_find_one_returns_document(self, collection_with_mock_client):
        """Test find_one returns a document when found."""
        collection, mock_client = collection_with_mock_client

        # Create mock response
        mock_hit = MagicMock()
        mock_hit.to_dict.return_value = {
            "id": 123456789,
            "type": "CHANNEL",
            "title": "Test Channel",
            "username": "test_channel",
            "scraped_by": "test_client",
            "added_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }
        mock_hit.meta.id = "123456789"

        mock_response = MagicMock()
        mock_response.hits = [mock_hit]

        # Patch the search execution
        with patch.object(
            collection, "_get_match_response", new_callable=AsyncMock
        ) as mock_get_response:
            mock_get_response.return_value = mock_response

            result = await collection.find_one(filter=Q("ids", values=["123456789"]))

            assert result is not None
            assert result.id == 123456789
            assert result.title == "Test Channel"

    @pytest.mark.asyncio
    async def test_find_one_returns_none_when_not_found(
        self, collection_with_mock_client
    ):
        """Test find_one returns None when no document is found."""
        collection, mock_client = collection_with_mock_client

        mock_response = MagicMock()
        mock_response.hits = []

        with patch.object(
            collection, "_get_match_response", new_callable=AsyncMock
        ) as mock_get_response:
            mock_get_response.return_value = mock_response

            result = await collection.find_one(filter=Q("ids", values=["nonexistent"]))

            assert result is None


class TestCollectionFind:
    """Test cases for Collection.find method."""

    @pytest.fixture
    def collection_with_mock_client(self):
        """Create a ChatsCollection with mocked ES client."""
        mock_client = AsyncMock()
        collection = ChatsCollection(mock_client)
        return collection, mock_client

    @pytest.mark.asyncio
    async def test_find_returns_multiple_documents(self, collection_with_mock_client):
        """Test find returns multiple documents as async iterator."""
        collection, mock_client = collection_with_mock_client

        # Create mock hits
        mock_hits = []
        for i in range(3):
            mock_hit = MagicMock()
            mock_hit.to_dict.return_value = {
                "id": 123456789 + i,
                "type": "CHANNEL",
                "title": f"Test Channel {i}",
                "username": f"test_channel_{i}",
                "scraped_by": "test_client",
                "added_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
            mock_hit.meta.id = str(123456789 + i)
            mock_hit.meta.score = 1.0
            # Delete highlight attribute so hasattr returns False
            del mock_hit.meta.highlight
            mock_hits.append(mock_hit)

        mock_response = MagicMock()
        mock_response.hits = mock_hits

        with patch.object(
            collection, "_get_match_response", new_callable=AsyncMock
        ) as mock_get_response:
            mock_get_response.return_value = mock_response

            results = [doc async for doc in collection.find()]

            assert len(results) == 3
            assert results[0].title == "Test Channel 0"
            assert results[1].title == "Test Channel 1"
            assert results[2].title == "Test Channel 2"

    @pytest.mark.asyncio
    async def test_find_with_highlight(self, collection_with_mock_client):
        """Test find includes highlight data when present."""
        collection, mock_client = collection_with_mock_client

        mock_hit = MagicMock()
        mock_hit.to_dict.return_value = {
            "id": 123456789,
            "type": "CHANNEL",
            "title": "Test Channel",
            "username": "test_channel",
            "scraped_by": "test_client",
            "added_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }
        mock_hit.meta.id = "123456789"
        mock_hit.meta.score = 1.0
        mock_hit.meta.highlight = MagicMock()
        mock_hit.meta.highlight.to_dict.return_value = {
            "title": ["<em>Test</em> Channel"]
        }

        mock_response = MagicMock()
        mock_response.hits = [mock_hit]

        with patch.object(
            collection, "_get_match_response", new_callable=AsyncMock
        ) as mock_get_response:
            mock_get_response.return_value = mock_response

            results = [doc async for doc in collection.find()]

            assert len(results) == 1
            assert results[0].highlight is not None
            assert "title" in results[0].highlight


class TestCollectionCount:
    """Test cases for Collection.count method."""

    @pytest.fixture
    def collection_with_mock_client(self):
        """Create a ChatsCollection with mocked ES client."""
        mock_client = AsyncMock()
        collection = ChatsCollection(mock_client)
        return collection, mock_client

    @pytest.mark.asyncio
    async def test_count_returns_total(self, collection_with_mock_client):
        """Test count returns the total number of documents."""
        collection, mock_client = collection_with_mock_client

        # Mock the search count
        with patch("api.database.database.AsyncSearch") as mock_search_class:
            mock_search = MagicMock()
            mock_search.query.return_value = mock_search
            mock_search.filter.return_value = mock_search
            mock_search.count = AsyncMock(return_value=42)
            mock_search_class.return_value = mock_search

            result = await collection.count()

            assert result == 42

    @pytest.mark.asyncio
    async def test_count_with_filter(self, collection_with_mock_client):
        """Test count with a filter query."""
        collection, mock_client = collection_with_mock_client

        with patch("api.database.database.AsyncSearch") as mock_search_class:
            mock_search = MagicMock()
            mock_search.query.return_value = mock_search
            mock_search.filter.return_value = mock_search
            mock_search.count = AsyncMock(return_value=10)
            mock_search_class.return_value = mock_search

            result = await collection.count(filter=Q("term", type="CHANNEL"))

            assert result == 10
            mock_search.filter.assert_called_once()


class TestCollectionInsertOne:
    """Test cases for Collection.insert_one method."""

    @pytest.fixture
    def collection_with_mock_client(self):
        """Create a ChatsCollection with mocked ES client."""
        mock_client = AsyncMock()
        collection = ChatsCollection(mock_client)
        return collection, mock_client

    @pytest.mark.asyncio
    async def test_insert_one_returns_document_id(self, collection_with_mock_client):
        """Test insert_one returns the created document ID."""
        collection, mock_client = collection_with_mock_client

        doc_id = str(uuid.uuid4())
        mock_client.index.return_value = {"_id": doc_id, "result": "created"}

        document = {
            "type": "CHANNEL",
            "title": "New Channel",
            "username": "new_channel",
        }

        result = await collection.insert_one(document, id=uuid.UUID(doc_id))

        assert result == doc_id
        mock_client.index.assert_called_once()


class TestCollectionUpdateOne:
    """Test cases for Collection.update_one method."""

    @pytest.fixture
    def collection_with_mock_client(self):
        """Create a ChatsCollection with mocked ES client."""
        mock_client = AsyncMock()
        collection = ChatsCollection(mock_client)
        return collection, mock_client

    @pytest.mark.asyncio
    async def test_update_one_success(self, collection_with_mock_client):
        """Test update_one successfully updates a document."""
        collection, mock_client = collection_with_mock_client

        # Mock the search to find the document
        mock_hit = MagicMock()
        mock_hit.meta.id = "123456789"
        mock_hit.meta.index = "chats"

        mock_search_response = MagicMock()
        mock_search_response.hits = [mock_hit]

        # Mock the update response
        mock_client.update.return_value = {"result": "updated"}

        # Mock find_one for the return value
        updated_doc = ChatOut(
            id=123456789,
            type=ChatType.CHANNEL,
            title="Updated Title",
            username="test_channel",
            scraped_by="test_client",
            added_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
        )

        with patch("api.database.database.AsyncSearch") as mock_search_class:
            mock_search = MagicMock()
            mock_search.query.return_value = mock_search
            mock_search.execute = AsyncMock(return_value=mock_search_response)
            mock_search_class.return_value = mock_search

            with patch.object(
                collection, "find_one", new_callable=AsyncMock
            ) as mock_find_one:
                mock_find_one.return_value = updated_doc

                result = await collection.update_one(
                    query=Q("ids", values=["123456789"]),
                    update={"title": "Updated Title"},
                )

                assert result is not None
                assert result.title == "Updated Title"
                mock_client.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_one_not_found(self, collection_with_mock_client):
        """Test update_one returns None when document not found."""
        collection, mock_client = collection_with_mock_client

        mock_search_response = MagicMock()
        mock_search_response.hits = []

        with patch("api.database.database.AsyncSearch") as mock_search_class:
            mock_search = MagicMock()
            mock_search.query.return_value = mock_search
            mock_search.execute = AsyncMock(return_value=mock_search_response)
            mock_search_class.return_value = mock_search

            result = await collection.update_one(
                query=Q("ids", values=["nonexistent"]),
                update={"title": "Updated Title"},
            )

            assert result is None


class TestCollectionDeleteById:
    """Test cases for Collection.delete_by_id method."""

    @pytest.fixture
    def collection_with_mock_client(self):
        """Create a ChatsCollection with mocked ES client."""
        mock_client = AsyncMock()
        collection = ChatsCollection(mock_client)
        return collection, mock_client

    @pytest.mark.asyncio
    async def test_delete_by_id_success(self, collection_with_mock_client):
        """Test delete_by_id successfully deletes a document."""
        collection, mock_client = collection_with_mock_client

        # Create the document to be deleted
        doc_to_delete = ChatOut(
            id=123456789,
            type=ChatType.CHANNEL,
            title="Test Channel",
            username="test_channel",
            scraped_by="test_client",
            added_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
        )

        mock_client.delete.return_value = {"result": "deleted"}

        with patch.object(
            collection, "find_one", new_callable=AsyncMock
        ) as mock_find_one:
            mock_find_one.return_value = doc_to_delete

            result = await collection.delete_by_id("123456789")

            assert result is not None
            assert result.id == 123456789
            mock_client.delete.assert_called_once_with(
                index="chats", id="123456789", refresh=True
            )

    @pytest.mark.asyncio
    async def test_delete_by_id_not_found(self, collection_with_mock_client):
        """Test delete_by_id returns None when document not found."""
        collection, mock_client = collection_with_mock_client

        with patch.object(
            collection, "find_one", new_callable=AsyncMock
        ) as mock_find_one:
            mock_find_one.return_value = None

            result = await collection.delete_by_id("nonexistent")

            assert result is None
            mock_client.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_by_id_handles_not_found_error(
        self, collection_with_mock_client
    ):
        """Test delete_by_id handles NotFoundError gracefully."""
        collection, mock_client = collection_with_mock_client

        doc_to_delete = ChatOut(
            id=123456789,
            type=ChatType.CHANNEL,
            title="Test Channel",
            username="test_channel",
            scraped_by="test_client",
            added_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
        )

        node = NodeConfig(scheme="http", host="localhost", port=9200)
        meta = ApiResponseMeta(
            status=404,
            http_version="1.1",
            headers=HttpHeaders({}),
            duration=0.0,
            node=node,
        )
        mock_client.delete.side_effect = NotFoundError(
            message="document not found", meta=meta, body={}
        )

        with patch.object(
            collection, "find_one", new_callable=AsyncMock
        ) as mock_find_one:
            mock_find_one.return_value = doc_to_delete

            result = await collection.delete_by_id("123456789")

            assert result is None


class TestCollectionGetTopFieldValues:
    """Test cases for Collection.get_top_field_values method."""

    @pytest.fixture
    def collection_with_mock_client(self):
        """Create a ChatsCollection with mocked ES client."""
        mock_client = AsyncMock()
        collection = ChatsCollection(mock_client)
        return collection, mock_client

    @pytest.mark.asyncio
    async def test_get_top_field_values_returns_stats(
        self, collection_with_mock_client
    ):
        """Test get_top_field_values returns aggregated stats."""
        collection, mock_client = collection_with_mock_client

        # Create mock aggregation response
        mock_bucket1 = MagicMock()
        mock_bucket1.key = "tag1"
        mock_bucket1.doc_count = 10

        mock_bucket2 = MagicMock()
        mock_bucket2.key = "tag2"
        mock_bucket2.doc_count = 5

        mock_response = MagicMock()
        mock_response.aggregations.field_terms.buckets = [mock_bucket1, mock_bucket2]

        with patch("api.database.database.AsyncSearch") as mock_search_class:
            mock_search = MagicMock()
            mock_search.query.return_value = mock_search
            mock_search.filter.return_value = mock_search
            mock_search.aggs.bucket.return_value = None
            mock_search.execute = AsyncMock(return_value=mock_response)
            mock_search_class.return_value = mock_search

            result = await collection.get_top_field_values("tags", size=10)

            assert len(result) == 2
            assert isinstance(result[0], StatsEntry)
            assert result[0].value == "tag1"
            assert result[0].count == 10
            assert result[1].value == "tag2"
            assert result[1].count == 5

    @pytest.mark.asyncio
    async def test_get_top_field_values_handles_error(
        self, collection_with_mock_client
    ):
        """Test get_top_field_values returns empty list on error."""
        collection, mock_client = collection_with_mock_client

        with patch("api.database.database.AsyncSearch") as mock_search_class:
            mock_search = MagicMock()
            mock_search.query.return_value = mock_search
            mock_search.filter.return_value = mock_search
            mock_search.aggs.bucket.return_value = None
            mock_search.execute = AsyncMock(side_effect=Exception("Search failed"))
            mock_search_class.return_value = mock_search

            result = await collection.get_top_field_values("tags")

            assert result == []


class TestCollectionDeleteByQuery:
    """Test cases for Collection.delete_by_query method."""

    @pytest.fixture
    def collection_with_mock_client(self):
        """Create a ChatsCollection with mocked ES client."""
        mock_client = AsyncMock()
        collection = ChatsCollection(mock_client)
        return collection, mock_client

    @pytest.mark.asyncio
    async def test_delete_by_query_without_query(self, collection_with_mock_client):
        """Test delete_by_query deletes all documents."""
        collection, mock_client = collection_with_mock_client

        with patch("api.database.database.AsyncSearch") as mock_search_class:
            mock_search = MagicMock()
            mock_search.query.return_value = mock_search
            mock_search.delete = AsyncMock()
            mock_search_class.return_value = mock_search

            await collection.delete_by_query()

            mock_search.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_by_query_with_query(self, collection_with_mock_client):
        """Test delete_by_query deletes documents matching query."""
        collection, mock_client = collection_with_mock_client

        with patch("api.database.database.AsyncSearch") as mock_search_class:
            mock_search = MagicMock()
            mock_search.query.return_value = mock_search
            mock_search.delete = AsyncMock()
            mock_search_class.return_value = mock_search

            await collection.delete_by_query(query=Q("term", type="CHANNEL"))

            mock_search.query.assert_called()
            mock_search.delete.assert_called_once()
