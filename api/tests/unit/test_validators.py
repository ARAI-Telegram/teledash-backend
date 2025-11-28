"""
Unit tests for API validators and sort configuration.

Testing includes:
- Test all validation functions
- Test edge cases and error scenarios
- Test default values
"""

from datetime import datetime
from enum import Enum

import pytest

from api.sort_config import (
    DEFAULT_SORT_OPTIONS,
    ChatSortBy,
    ChatSortOptions,
    ClientSortBy,
    ClientSortOptions,
    MessageSortBy,
    MessageSortOptions,
    OrderEnum,
    UserSortBy,
    UserSortOptions,
    sort_semantic_search_results,
)
from api.validators import (
    convert_enum_to_value,
    parse_fields_params,
    parse_sort_params,
)
from common.database.models.message import MessageOut


class TestConvertEnumToValue:
    """Test cases for convert_enum_to_value function."""

    def test_convert_string_enum(self):
        """Test converting string enum to value."""
        result = convert_enum_to_value(ChatSortBy.TITLE)
        assert result == "title.keyword"

    def test_convert_order_enum(self):
        """Test converting order enum to value."""
        result = convert_enum_to_value(OrderEnum.DESC)
        assert result == "desc"

    def test_non_enum_value_unchanged(self):
        """Test that non-enum values are returned unchanged."""
        result = convert_enum_to_value("plain_string")
        assert result == "plain_string"

        result = convert_enum_to_value(42)
        assert result == 42

        result = convert_enum_to_value(None)
        assert result is None

    def test_convert_custom_enum(self):
        """Test converting custom enum."""

        class CustomEnum(Enum):
            VALUE = "custom_value"

        result = convert_enum_to_value(CustomEnum.VALUE)
        assert result == "custom_value"


class TestParseSortParams:
    """Test cases for parse_sort_params function."""

    def test_default_chat_sort_no_params(self):
        """Test default chat sort when no parameters provided."""
        result = parse_sort_params(ChatSortOptions)

        assert len(result) == 1
        assert result[0].sort_by == ChatSortBy.TITLE
        assert result[0].order == OrderEnum.ASC

    def test_default_message_sort_no_params(self):
        """Test default message sort when no parameters provided."""
        result = parse_sort_params(MessageSortOptions)

        assert len(result) == 1
        assert result[0].sort_by == MessageSortBy.DATE
        assert result[0].order == OrderEnum.DESC

    def test_default_user_sort_no_params(self):
        """Test default user sort when no parameters provided."""
        result = parse_sort_params(UserSortOptions)

        assert len(result) == 1
        assert result[0].sort_by == UserSortBy.USERNAME
        assert result[0].order == OrderEnum.ASC

    def test_default_client_sort_no_params(self):
        """Test default client sort when no parameters provided."""
        result = parse_sort_params(ClientSortOptions)

        assert len(result) == 1
        assert result[0].sort_by == ClientSortBy.TITLE
        assert result[0].order == OrderEnum.ASC

    def test_custom_sort_by(self):
        """Test custom sort_by parameter."""
        result = parse_sort_params(
            ChatSortOptions,
            sort_by=ChatSortBy.MEMBERS_COUNT,
        )

        assert result[0].sort_by == ChatSortBy.MEMBERS_COUNT
        assert result[0].order == OrderEnum.DESC  # Default order

    def test_custom_order(self):
        """Test custom order parameter."""
        result = parse_sort_params(
            ChatSortOptions,
            sort_by=ChatSortBy.TITLE,
            order=OrderEnum.ASC,
        )

        assert result[0].order == OrderEnum.ASC

    def test_custom_sort_and_order(self):
        """Test both custom sort_by and order."""
        result = parse_sort_params(
            MessageSortOptions,
            sort_by=MessageSortBy.CONSPIRACY,
            order=OrderEnum.DESC,
        )

        assert result[0].sort_by == MessageSortBy.CONSPIRACY
        assert result[0].order == OrderEnum.DESC

    def test_search_context_uses_score(self):
        """Test that search context enables score-based sorting."""
        result = parse_sort_params(
            ChatSortOptions,
            search_context=True,
        )

        assert result[0].sort_by == ChatSortBy.SCORE
        assert result[0].order == OrderEnum.DESC

    def test_score_without_search_context_falls_back(self):
        """Test that requesting SCORE without search context falls back to default."""
        result = parse_sort_params(
            ChatSortOptions,
            sort_by=ChatSortBy.SCORE,
            search_context=False,
        )

        # Should fall back to default (TITLE ASC)
        assert result[0].sort_by == ChatSortBy.TITLE
        assert result[0].order == OrderEnum.ASC

    def test_explicit_sort_with_search_context(self):
        """Test that explicit sort_by overrides search context default."""
        result = parse_sort_params(
            ChatSortOptions,
            sort_by=ChatSortBy.UPDATED_AT,
            order=OrderEnum.ASC,
            search_context=True,
        )

        # Should use explicit sort, not fall back to SCORE
        assert result[0].sort_by == ChatSortBy.UPDATED_AT
        assert result[0].order == OrderEnum.ASC

    def test_message_sort_date(self):
        """Test message sort by date."""
        result = parse_sort_params(
            MessageSortOptions,
            sort_by=MessageSortBy.DATE,
            order=OrderEnum.ASC,
        )

        assert result[0].sort_by == MessageSortBy.DATE
        assert result[0].order == OrderEnum.ASC

    def test_user_sort_updated_at(self):
        """Test user sort by updated_at."""
        result = parse_sort_params(
            UserSortOptions,
            sort_by=UserSortBy.UPDATED_AT,
            order=OrderEnum.DESC,
        )

        assert result[0].sort_by == UserSortBy.UPDATED_AT
        assert result[0].order == OrderEnum.DESC


class TestParseFieldsParams:
    """Test cases for parse_fields_params function."""

    def test_no_params_returns_none(self):
        """Test that no parameters returns None."""
        # When called with explicit None values (as would happen in actual usage)
        result = parse_fields_params(include=None, exclude=None)
        assert result is None

    def test_include_only(self):
        """Test include parameter only."""
        result = parse_fields_params(include=["title", "username"], exclude=None)

        assert result is not None
        assert "includes" in result
        assert result["includes"] == ["title", "username"]
        assert "excludes" not in result

    def test_exclude_only(self):
        """Test exclude parameter only."""
        result = parse_fields_params(include=None, exclude=["description", "photo"])

        assert result is not None
        assert "excludes" in result
        assert result["excludes"] == ["description", "photo"]
        assert "includes" not in result

    def test_both_include_and_exclude(self):
        """Test both include and exclude parameters."""
        result = parse_fields_params(
            include=["title", "id"],
            exclude=["description"],
        )

        assert result is not None
        assert "includes" in result
        assert result.get("includes") == ["title", "id"]
        assert "excludes" in result
        assert result.get("excludes") == ["description"]

    def test_empty_lists_return_none(self):
        """Test that empty lists are treated as None."""
        # Empty list should still be falsy and not included
        result = parse_fields_params(include=[], exclude=[])
        assert result is None


class TestSortSemanticSearchResults:
    """Test cases for sort_semantic_search_results function."""

    @pytest.fixture
    def sample_messages(self):
        """Create sample messages with semantic scores."""
        messages = []
        for i in range(5):
            msg = MessageOut(
                id=str(i + 1),
                date=datetime(2024, 1, i + 1, 12, 0, 0),
                text=f"Message {i}",
                views=100 * (i + 1),
            )
            msg.semantic_score = 0.5 + (i * 0.1)
            messages.append(msg)
        return messages

    def test_sort_by_score_descending(self, sample_messages):
        """Test sorting by semantic score descending."""
        sort = [MessageSortOptions(sort_by=MessageSortBy.SCORE, order=OrderEnum.DESC)]

        result = sort_semantic_search_results(sample_messages, sort)

        # Should be sorted from highest to lowest score
        assert result[0].semantic_score == 0.9
        assert result[-1].semantic_score == 0.5

    def test_sort_by_score_ascending(self, sample_messages):
        """Test sorting by semantic score ascending."""
        sort = [MessageSortOptions(sort_by=MessageSortBy.SCORE, order=OrderEnum.ASC)]

        result = sort_semantic_search_results(sample_messages, sort)

        # Should be sorted from lowest to highest score
        assert result[0].semantic_score == 0.5
        assert result[-1].semantic_score == 0.9

    def test_sort_by_date_descending(self, sample_messages):
        """Test sorting by date descending."""
        sort = [MessageSortOptions(sort_by=MessageSortBy.DATE, order=OrderEnum.DESC)]

        result = sort_semantic_search_results(sample_messages, sort)

        # Should be sorted from newest to oldest
        assert result[0].date == datetime(2024, 1, 5, 12, 0, 0)
        assert result[-1].date == datetime(2024, 1, 1, 12, 0, 0)

    def test_sort_handles_none_values(self):
        """Test that None values are sorted to the end (for DESC)."""
        messages = []
        for i in range(3):
            msg = MessageOut(
                id=str(i + 1),
                date=datetime(2024, 1, 1, 12, 0, 0),
                text=f"Message {i}",
            )
            if i == 1:
                msg.semantic_score = None
            else:
                msg.semantic_score = 0.5 + (i * 0.2)
            messages.append(msg)

        sort = [MessageSortOptions(sort_by=MessageSortBy.SCORE, order=OrderEnum.DESC)]
        result = sort_semantic_search_results(messages, sort)

        # None should be at the end for DESC
        assert result[0].semantic_score == 0.9
        assert result[1].semantic_score == 0.5
        assert result[2].semantic_score is None

    def test_sort_empty_list(self):
        """Test sorting an empty list."""
        sort = [MessageSortOptions(sort_by=MessageSortBy.SCORE, order=OrderEnum.DESC)]

        result = sort_semantic_search_results([], sort)

        assert result == []


class TestDefaultSortOptions:
    """Test cases for DEFAULT_SORT_OPTIONS configuration."""

    def test_chat_default_sort(self):
        """Test default chat sort configuration."""
        default = DEFAULT_SORT_OPTIONS[ChatSortOptions]

        assert len(default) == 1
        assert default[0].sort_by == ChatSortBy.TITLE
        assert default[0].order == OrderEnum.ASC

    def test_message_default_sort(self):
        """Test default message sort configuration."""
        default = DEFAULT_SORT_OPTIONS[MessageSortOptions]

        assert len(default) == 1
        assert default[0].sort_by == MessageSortBy.DATE
        assert default[0].order == OrderEnum.DESC

    def test_user_default_sort(self):
        """Test default user sort configuration."""
        default = DEFAULT_SORT_OPTIONS[UserSortOptions]

        assert len(default) == 1
        assert default[0].sort_by == UserSortBy.USERNAME
        assert default[0].order == OrderEnum.ASC

    def test_client_default_sort(self):
        """Test default client sort configuration."""
        default = DEFAULT_SORT_OPTIONS[ClientSortOptions]

        assert len(default) == 1
        assert default[0].sort_by == ClientSortBy.TITLE
        assert default[0].order == OrderEnum.ASC


class TestSortByEnumValues:
    """Test cases for sort enum values."""

    def test_chat_sort_by_values(self):
        """Test ChatSortBy enum values match Elasticsearch field names."""
        assert ChatSortBy.TITLE.value == "title.keyword"
        assert ChatSortBy.MEMBERS_COUNT.value == "members_count"
        assert ChatSortBy.UPDATED_AT.value == "updated_at"
        assert ChatSortBy.SCORE.value == "score"

    def test_message_sort_by_values(self):
        """Test MessageSortBy enum values."""
        assert MessageSortBy.DATE.value == "date"
        assert MessageSortBy.SCORE.value == "score"
        assert MessageSortBy.CONSPIRACY.value == "classification.score_pos"

    def test_user_sort_by_values(self):
        """Test UserSortBy enum values."""
        assert UserSortBy.SCORE.value == "score"
        assert UserSortBy.USERNAME.value == "username.keyword"
        assert UserSortBy.UPDATED_AT.value == "updated_at"

    def test_client_sort_by_values(self):
        """Test ClientSortBy enum values."""
        assert ClientSortBy.TITLE.value == "title"
        assert ClientSortBy.CREATED_AT.value == "created_at"
        assert ClientSortBy.UPDATED_AT.value == "updated_at"

    def test_order_enum_values(self):
        """Test OrderEnum values."""
        assert OrderEnum.ASC.value == "asc"
        assert OrderEnum.DESC.value == "desc"
