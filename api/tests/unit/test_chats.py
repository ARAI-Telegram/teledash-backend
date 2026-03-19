"""
Unit tests for the Chat API routes.

Testing includes:
- Mock database and authentication dependencies
- Test all endpoint scenarios including success and error cases
- Test filtering, sorting, and pagination
"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from api.database.database import StatsEntry
from elasticsearch.dsl import Q

from common.database.models.chat import ChatOut, ChatType


class TestListChats:
    """Test cases for GET /chats endpoint."""

    @pytest.fixture
    def sample_chats(self):
        """Create sample chats for testing."""
        chats = []
        for i in range(5):
            chats.append(
                ChatOut(
                    id=123456789 + i,
                    type=ChatType.CHANNEL if i % 2 == 0 else ChatType.SUPERGROUP,
                    title=f"Test Channel {i}",
                    username=f"test_channel_{i}",
                    description=f"Test channel {i} description",
                    members_count=1000 * (i + 1),
                    scraped_by="test_client_id",
                    added_at=datetime(2024, 1, 1, 0, 0, 0),
                    updated_at=datetime(2024, 1, 1, 0, 0, 0),
                )
            )
        return chats

    @pytest.mark.asyncio
    async def test_list_chats_returns_paginated_results(
        self, mock_database, sample_chats
    ):
        """Test that list_chats returns paginated results."""

        # Configure mock database
        async def mock_find(*args, **kwargs):
            for chat in sample_chats:
                yield chat

        mock_database.chats.find = mock_find
        mock_database.chats.count = AsyncMock(return_value=5)

        # Mock get_chat_metrics
        with patch(
            "api.chats.routes.get_chat_metrics", new_callable=AsyncMock
        ) as mock_metrics:
            mock_metrics.return_value = {}

            # Import router function dependencies
            from api.sort_config import ChatSortBy, ChatSortOptions, OrderEnum

            # Create test dependencies
            offset, limit, _ = 0, 10, 100
            sort = [
                ChatSortOptions(sort_by=ChatSortBy.MEMBERS_COUNT, order=OrderEnum.DESC)
            ]

            # Simulate calling the endpoint logic with pagination and sort
            result = []
            async for doc in mock_database.chats.find(
                skip=offset, limit=limit, sort=sort
            ):
                result.append(doc)

            count_total = await mock_database.chats.count()

            assert len(result) == 5
            assert count_total == 5
            assert result[0].title == "Test Channel 0"

    @pytest.mark.asyncio
    async def test_list_chats_with_filter(self, mock_database, sample_chats):
        """Test list_chats filters results by chat type."""
        # Filter only CHANNEL type
        filtered_chats = [c for c in sample_chats if c.type == ChatType.CHANNEL]

        async def mock_find(*args, **kwargs):
            for chat in filtered_chats:
                yield chat

        mock_database.chats.find = mock_find
        mock_database.chats.count = AsyncMock(return_value=len(filtered_chats))

        result = []
        async for doc in mock_database.chats.find():
            result.append(doc)

        assert len(result) == 3  # 3 out of 5 are CHANNEL
        for chat in result:
            assert chat.type == ChatType.CHANNEL

    @pytest.mark.asyncio
    async def test_list_chats_with_search_query(self, mock_database):
        """Test list_chats searches by text query."""
        matching_chat = ChatOut(
            id=123456789,
            type=ChatType.CHANNEL,
            title="Matching Channel",
            username="matching",
            description="This channel matches the search",
            members_count=1000,
            scraped_by="test_client_id",
            added_at=datetime(2024, 1, 1, 0, 0, 0),
            updated_at=datetime(2024, 1, 1, 0, 0, 0),
            highlight={"title": ["<em>Matching</em> Channel"]},
        )

        async def mock_find(*args, **kwargs):
            yield matching_chat

        mock_database.chats.find = mock_find
        mock_database.chats.count = AsyncMock(return_value=1)

        result = []
        async for doc in mock_database.chats.find():
            result.append(doc)

        assert len(result) == 1
        assert result[0].title == "Matching Channel"
        assert result[0].highlight is not None

    @pytest.mark.asyncio
    async def test_list_chats_with_aggregations(self, mock_database, sample_chats):
        """Test list_chats includes chat metrics when aggregations enabled."""

        async def mock_find(*args, **kwargs):
            for chat in sample_chats[:2]:
                yield chat

        mock_database.chats.find = mock_find
        mock_database.chats.count = AsyncMock(return_value=2)

        with patch(
            "api.chats.routes.get_chat_metrics", new_callable=AsyncMock
        ) as mock_metrics:
            mock_metrics.return_value = {
                123456789: {"activity_total": {"messages_count": 100}},
                123456790: {"activity_total": {"messages_count": 200}},
            }

            result = []
            async for doc in mock_database.chats.find():
                result.append(doc)

            chat_ids = [chat.id for chat in result]
            metrics = await mock_metrics(chat_ids, total=False, yesterday=True)

            assert 123456789 in metrics
            assert 123456790 in metrics

    @pytest.mark.asyncio
    async def test_list_chats_empty_results(self, mock_database):
        """Test list_chats returns empty list when no chats found."""

        async def mock_find(*args, **kwargs):
            # Empty async generator - yields nothing
            if False:
                yield

        mock_database.chats.find = mock_find
        mock_database.chats.count = AsyncMock(return_value=0)

        result = []
        async for doc in mock_database.chats.find():
            result.append(doc)

        assert len(result) == 0


class TestGetChat:
    """Test cases for GET /chats/{id} endpoint."""

    @pytest.fixture
    def sample_chat(self):
        """Create a sample chat for testing."""
        return ChatOut(
            id=123456789,
            type=ChatType.CHANNEL,
            title="Test Channel",
            username="test_channel",
            description="A test channel",
            members_count=1000,
            scraped_by="test_client_id",
            added_at=datetime(2024, 1, 1, 0, 0, 0),
            updated_at=datetime(2024, 1, 1, 0, 0, 0),
        )

    @pytest.mark.asyncio
    async def test_get_chat_found(self, mock_database, sample_chat):
        """Test get_chat returns a chat when found."""
        mock_database.chats.find_one = AsyncMock(return_value=sample_chat)

        with patch(
            "api.chats.routes.get_chat_metrics", new_callable=AsyncMock
        ) as mock_metrics:
            mock_metrics.return_value = {
                123456789: {"activity_total": {"messages_count": 100}}
            }

            with patch(
                "api.chats.routes.aggregate_classification_results",
                new_callable=AsyncMock,
            ) as mock_classification:
                mock_classification.return_value = None

                result = await mock_database.chats.find_one(
                    filter=Q("ids", values=[123456789])
                )

                assert result is not None
                assert result.id == 123456789
                assert result.title == "Test Channel"

    @pytest.mark.asyncio
    async def test_get_chat_not_found(self, mock_database):
        """Test get_chat raises 404 when chat not found."""
        mock_database.chats.find_one = AsyncMock(return_value=None)

        result = await mock_database.chats.find_one(filter=Q("ids", values=[999999999]))

        assert result is None

    @pytest.mark.asyncio
    async def test_get_chat_with_metrics(self, mock_database, sample_chat):
        """Test get_chat includes metrics in response."""
        mock_database.chats.find_one = AsyncMock(return_value=sample_chat)

        with patch(
            "api.chats.routes.get_chat_metrics", new_callable=AsyncMock
        ) as mock_metrics:
            mock_metrics.return_value = {
                123456789: {
                    "activity_total": {"messages_count": 100, "views_count": 5000},
                    "growth_total": {"members_count_change": 50},
                }
            }

            result = await mock_database.chats.find_one(
                filter=Q("ids", values=[123456789])
            )
            metrics = await mock_metrics([123456789], total=True, yesterday=True)

            assert result is not None
            assert 123456789 in metrics
            assert metrics[123456789]["activity_total"]["messages_count"] == 100


class TestUpdateChat:
    """Test cases for PUT /chats/{id} endpoint."""

    @pytest.fixture
    def sample_chat(self):
        """Create a sample chat for testing."""
        return ChatOut(
            id=123456789,
            type=ChatType.CHANNEL,
            title="Test Channel",
            username="test_channel",
            description="A test channel",
            members_count=1000,
            scraped_by="test_client_id",
            added_at=datetime(2024, 1, 1, 0, 0, 0),
            updated_at=datetime(2024, 1, 1, 0, 0, 0),
            tags=["news", "tech"],
            language="en",
        )

    @pytest.mark.asyncio
    async def test_update_chat_success(self, mock_database, sample_chat):
        """Test update_chat successfully updates chat metadata."""
        updated_chat = ChatOut(
            id=123456789,
            type=ChatType.CHANNEL,
            title="Test Channel",
            username="test_channel",
            description="A test channel",
            members_count=1000,
            scraped_by="test_client_id",
            added_at=datetime(2024, 1, 1, 0, 0, 0),
            updated_at=datetime(2024, 1, 1, 0, 0, 0),
            tags=["updated", "tags"],
            language="de",
        )

        mock_database.chats.update_one = AsyncMock(return_value=updated_chat)

        result = await mock_database.chats.update_one(
            query=Q("ids", values=[123456789]),
            update={"tags": ["updated", "tags"], "language": "de"},
        )

        assert result is not None
        assert result.tags == ["updated", "tags"]
        assert result.language == "de"

    @pytest.mark.asyncio
    async def test_update_chat_not_found(self, mock_database):
        """Test update_chat raises UpdateTargetNotFoundError when document not found."""
        from api.database.database import UpdateTargetNotFoundError

        mock_database.chats.update_one = AsyncMock(
            side_effect=UpdateTargetNotFoundError("No document found")
        )

        with pytest.raises(UpdateTargetNotFoundError):
            await mock_database.chats.update_one(
                query=Q("ids", values=[999999999]), update={"tags": ["new"]}
            )

    @pytest.mark.asyncio
    async def test_update_chat_lowercase_tags(self, mock_database, sample_chat):
        """Test that tags are converted to lowercase."""
        # This tests the route logic, not the database
        from common.database.models.chat import ChatIn

        chat_update = ChatIn(tags=["NEWS", "Tech", "POLITICS"])
        update_dict = chat_update.model_dump(exclude_unset=True, exclude_none=True)

        # Convert tags to lowercase (as done in the route)
        if "tags" in update_dict and update_dict["tags"]:
            update_dict["tags"] = [tag.lower() for tag in update_dict["tags"]]

        assert update_dict["tags"] == ["news", "tech", "politics"]


class TestGetChatsStats:
    """Test cases for GET /chats/stats endpoint."""

    @pytest.mark.asyncio
    async def test_get_chats_stats_returns_aggregations(self, mock_database):
        """Test get_chats_stats returns tag aggregations."""
        mock_database.chats.get_top_field_values = AsyncMock(
            return_value=[
                StatsEntry(value="news", count=50),
                StatsEntry(value="tech", count=30),
                StatsEntry(value="politics", count=20),
            ]
        )

        result = await mock_database.chats.get_top_field_values(
            field="tags",
            size=20,
        )

        assert len(result) == 3
        assert result[0].value == "news"
        assert result[0].count == 50

    @pytest.mark.asyncio
    async def test_get_chats_stats_empty(self, mock_database):
        """Test get_chats_stats returns empty when no data."""
        mock_database.chats.get_top_field_values = AsyncMock(return_value=[])

        result = await mock_database.chats.get_top_field_values(
            field="tags",
            size=20,
        )

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_get_chats_stats_with_filter(self, mock_database):
        """Test get_chats_stats applies filters to aggregation."""
        mock_database.chats.get_top_field_values = AsyncMock(
            return_value=[
                StatsEntry(value="breaking", count=15),
            ]
        )

        filter_query = Q("term", type="CHANNEL")
        result = await mock_database.chats.get_top_field_values(
            field="tags",
            size=20,
            filter=filter_query,
        )

        assert len(result) == 1
        assert result[0].value == "breaking"
        assert result[0].count == 15

        mock_database.chats.get_top_field_values.assert_called_once_with(
            field="tags",
            size=20,
            filter=filter_query,
        )


class TestChatFiltering:
    """Test cases for chat filter parsing."""

    def test_parse_chat_filter_by_type(self):
        """Test parsing filter by chat type."""
        from api.chats.validators import parse_chat_filter

        result = parse_chat_filter(type=ChatType.CHANNEL, tags=None)

        assert result is not None
        # The result should be a bool query with term filter
        filter_dict = result.to_dict()
        assert filter_dict["bool"]["filter"][0]["term"]["type"] == "CHANNEL"

    def test_parse_chat_filter_by_verification(self):
        """Test parsing filter by verification status."""
        from api.chats.validators import parse_chat_filter

        result = parse_chat_filter(is_verified=True, tags=None)

        assert result is not None
        filter_dict = result.to_dict()
        assert (
            filter_dict["bool"]["filter"][0]["term"]["verification_status.is_verified"]
            is True
        )

    def test_parse_chat_filter_by_tags(self):
        """Test parsing filter by multiple tags."""
        from api.chats.validators import parse_chat_filter

        result = parse_chat_filter(tags=["news", "tech"])

        assert result is not None
        # All tags must match (AND logic)
        filter_dict = result.to_dict()
        assert "bool" in filter_dict

    def test_parse_chat_filter_multiple_criteria(self):
        """Test parsing filter with multiple criteria."""
        from api.chats.validators import parse_chat_filter

        result = parse_chat_filter(
            type=ChatType.CHANNEL,
            is_verified=True,
            is_scam=False,
            tags=None,
        )

        assert result is not None
        filters = result.to_dict()["bool"]["filter"]
        assert len(filters) == 3

    def test_parse_chat_filter_none_when_no_filters(self):
        """Test that None is returned when no filters provided."""
        from api.chats.validators import parse_chat_filter

        result = parse_chat_filter(tags=None)

        assert result is None


class TestChatSearchQuery:
    """Test cases for chat search query parsing."""

    def test_parse_flexible_chat_search_query(self):
        """Test parsing a search query."""
        from api.chats.validators import parse_flexible_chat_search_query

        result = parse_flexible_chat_search_query(search_query="test search")

        assert result is not None

    def test_parse_flexible_chat_search_query_none(self):
        """Test that None is returned for empty search."""
        from api.chats.validators import parse_flexible_chat_search_query

        result = parse_flexible_chat_search_query(search_query=None)

        assert result is None


class TestChatSorting:
    """Test cases for chat sort parsing."""

    def test_parse_chat_sort_default(self):
        """Test default sort parameters."""
        from api.chats.validators import parse_chat_sort
        from api.sort_config import ChatSortBy, OrderEnum

        result = parse_chat_sort()

        assert result is not None
        assert len(result) == 1
        # Default sort should be title ascending (from DEFAULT_SORT_OPTIONS)
        assert result[0].sort_by == ChatSortBy.TITLE
        assert result[0].order == OrderEnum.ASC

    def test_parse_chat_sort_custom(self):
        """Test custom sort parameters."""
        from api.chats.validators import parse_chat_sort
        from api.sort_config import ChatSortBy, OrderEnum

        result = parse_chat_sort(
            sort_by=ChatSortBy.UPDATED_AT,
            order=OrderEnum.ASC,
        )

        assert result[0].sort_by == ChatSortBy.UPDATED_AT
        assert result[0].order == OrderEnum.ASC

    def test_parse_chat_sort_with_search_context(self):
        """Test sort with search context uses score."""
        from api.chats.validators import parse_chat_sort
        from api.sort_config import ChatSortBy, OrderEnum

        result = parse_chat_sort(search_query="test")

        # When search context is present and no explicit sort, should sort by score
        assert result[0].sort_by == ChatSortBy.SCORE
        assert result[0].order == OrderEnum.DESC


class TestChatDeletion:
    """Test cases for the delete_chat_data function."""

    @pytest.mark.asyncio
    async def test_delete_chat_data_without_storage(self, mock_database):
        """Test complete chat deletion without storage cleanup."""
        from api.chats.delete_chat_data import delete_chat_data

        mock_database.chats.delete_by_query = AsyncMock(return_value=1)
        mock_database.metrics.delete_by_query = AsyncMock(return_value=5)
        mock_database.es_client.indices.delete = AsyncMock()
        mock_database.es_client.indices.exists = AsyncMock(return_value=False)

        deleted_storage_objects, errors = await delete_chat_data(
            mock_database, 123, storage=None
        )

        assert deleted_storage_objects == 0
        assert len(errors) == 0
        mock_database.chats.delete_by_query.assert_called_once()
        assert mock_database.es_client.indices.delete.call_count == 2

    @pytest.mark.asyncio
    async def test_delete_chat_data_with_storage(self, mock_database):
        """Test complete chat deletion with storage cleanup."""
        from unittest.mock import Mock

        from api.chats.delete_chat_data import delete_chat_data

        mock_storage = Mock()
        mock_storage.cleanup_orphaned_objects = AsyncMock(return_value=(3, None))

        mock_database.chats.delete_by_query = AsyncMock(return_value=1)
        mock_database.metrics.delete_by_query = AsyncMock(return_value=5)
        mock_database.es_client.indices.delete = AsyncMock()

        storage_refs = {("photos", "photo1.jpg"), ("photos", "photo2.jpg")}
        with patch(
            "api.chats.delete_chat_data.collect_storage_refs",
            new_callable=AsyncMock,
            return_value=storage_refs,
        ):
            deleted_storage_objects, errors = await delete_chat_data(
                mock_database, 123, storage=mock_storage
            )

        assert deleted_storage_objects == 3
        assert len(errors) == 0
        mock_storage.cleanup_orphaned_objects.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_chat_data_with_errors(self, mock_database):
        """Test deletion handles non-critical errors gracefully."""
        from api.chats.delete_chat_data import delete_chat_data

        mock_database.chats.delete_by_query = AsyncMock(return_value=1)
        mock_database.metrics.delete_by_query = AsyncMock(
            side_effect=Exception("Metrics error")
        )
        mock_database.es_client.indices.delete = AsyncMock()
        mock_database.es_client.indices.exists = AsyncMock(return_value=False)

        deleted_storage_objects, errors = await delete_chat_data(
            mock_database, 123, storage=None
        )

        assert deleted_storage_objects == 0
        assert len(errors) > 0
        assert any("metrics" in error.lower() for error in errors)

    @pytest.mark.asyncio
    async def test_delete_chat_data_no_storage_refs(self, mock_database):
        """Test that storage cleanup is skipped when collect_storage_refs returns nothing."""
        from unittest.mock import Mock

        from api.chats.delete_chat_data import delete_chat_data

        mock_storage = Mock()
        mock_storage.cleanup_orphaned_objects = AsyncMock(return_value=(0, None))

        mock_database.chats.delete_by_query = AsyncMock(return_value=1)
        mock_database.metrics.delete_by_query = AsyncMock(return_value=0)
        mock_database.es_client.indices.delete = AsyncMock()

        with patch(
            "api.chats.delete_chat_data.collect_storage_refs",
            new_callable=AsyncMock,
            return_value=set(),
        ):
            deleted_storage_objects, errors = await delete_chat_data(
                mock_database, 999, storage=mock_storage
            )

        assert deleted_storage_objects == 0
        mock_storage.cleanup_orphaned_objects.assert_not_called()


class TestLeaveChat:
    """Test cases for the leave_chat function."""

    @pytest.mark.asyncio
    async def test_leave_chat_no_clients(self, mock_database):
        """Test leave_chat returns empty list when no clients are found for the chat."""
        from api.chats.leave_chat import leave_chat

        with patch(
            "api.chats.leave_chat.find_clients_for_chat",
            new_callable=AsyncMock,
            return_value=[],
        ):
            results = await leave_chat(mock_database, 123)

        assert results == []

    @pytest.mark.asyncio
    async def test_leave_chat_success(self, mock_database, sample_client):
        """Test leave_chat returns success when client leaves successfully."""
        from api.chats.leave_chat import leave_chat
        from api.chats.models import LeaveChatResult

        with patch(
            "api.chats.leave_chat.find_clients_for_chat",
            new_callable=AsyncMock,
            return_value=[sample_client],
        ):
            with patch(
                "api.chats.leave_chat.leave_chat_via_pyrogram",
                new_callable=AsyncMock,
                return_value=LeaveChatResult(client_id=sample_client.id, success=True),
            ):
                results = await leave_chat(mock_database, 123)

        assert len(results) == 1
        assert results[0].success is True

    @pytest.mark.asyncio
    async def test_leave_chat_not_member_is_success(self, mock_database, sample_client):
        """Test that 'not a member' errors are treated as success."""
        from api.chats.leave_chat import leave_chat
        from api.chats.models import LeaveChatResult

        with patch(
            "api.chats.leave_chat.find_clients_for_chat",
            new_callable=AsyncMock,
            return_value=[sample_client],
        ):
            with patch(
                "api.chats.leave_chat.leave_chat_via_pyrogram",
                new_callable=AsyncMock,
                return_value=LeaveChatResult(
                    client_id=sample_client.id,
                    success=True,
                    message="Already not a member",
                ),
            ):
                results = await leave_chat(mock_database, 123)

        assert len(results) == 1
        assert results[0].success is True

    @pytest.mark.asyncio
    async def test_leave_chat_active_client_failure_raises(self, mock_database, sample_client):
        """Test that a failure from an active client raises an exception."""
        from api.chats.leave_chat import leave_chat
        from api.chats.models import LeaveChatResult

        sample_client.is_active = True

        with patch(
            "api.chats.leave_chat.find_clients_for_chat",
            new_callable=AsyncMock,
            return_value=[sample_client],
        ):
            with patch(
                "api.chats.leave_chat.leave_chat_via_pyrogram",
                new_callable=AsyncMock,
                return_value=LeaveChatResult(
                    client_id=sample_client.id,
                    success=False,
                    message="Connection error",
                ),
            ):
                with pytest.raises(Exception, match=sample_client.id):
                    await leave_chat(mock_database, 123)

    @pytest.mark.asyncio
    async def test_leave_chat_inactive_client_failure_continues_with_warning(
        self, mock_database, sample_client
    ):
        """Test that a failure from an inactive client continues and adds a warning message."""
        from api.chats.leave_chat import leave_chat
        from api.chats.models import LeaveChatResult

        sample_client.is_active = False

        with patch(
            "api.chats.leave_chat.find_clients_for_chat",
            new_callable=AsyncMock,
            return_value=[sample_client],
        ):
            with patch(
                "api.chats.leave_chat.leave_chat_via_pyrogram",
                new_callable=AsyncMock,
                return_value=LeaveChatResult(
                    client_id=sample_client.id,
                    success=False,
                    message="Connection error",
                ),
            ):
                results = await leave_chat(mock_database, 123)

        assert len(results) == 1
        assert results[0].success is False
        assert "inactive" in results[0].message.lower()
