from enum import Enum
from typing import Any, List, Optional, Type, TypedDict

from fastapi import Query

from api.sort_config import (
    DEFAULT_SORT_OPTIONS,
    ChatSortBy,
    OrderEnum,
    SortByEnum,
    SortOptions,
    SortParams,
)


class FieldFilter(TypedDict, total=False):
    """Elasticsearch source filtering configuration."""

    includes: List[str]
    excludes: List[str]


def convert_enum_to_value(value: Any) -> Any:
    """Convert enums to their values before passing to Elasticsearch."""
    if isinstance(value, Enum):
        return value.value
    return value


def parse_sort_params(
    sort_options_cls: Type[SortOptions],
    sort_by: Optional[SortByEnum] = None,
    order: Optional[OrderEnum] = None,
    search_context: bool = False,
) -> SortParams:
    """
    Parse sorting parameters and apply intelligent default sorting based on context.

    Implements fallback logic:
    1. If no sort_by provided: use default sort for the type (e.g., TITLE for chats)
    2. If sort_by is SCORE but no search_context: fall back to default sort
    3. If search_context is True and no sort_by: sort by SCORE descending
    4. Otherwise: use the provided sort_by and order

    Args:
        sort_options_cls: The SortOptions subclass (ChatSortOptions, MessageSortOptions, etc.)
        sort_by: Optional field to sort by (SCORE, TITLE, DATE, etc.)
        order: Optional sort order (ASC/DESC), defaults to DESC if not provided
        search_context: Whether a search query is active (enables score-based sorting)

    Returns:
        List of sort options with appropriate sort_by and order values
    """
    # Set fallback order if not provided
    order = order if order else OrderEnum.DESC

    # Get type of sort_by of sort_options_cls
    sort_by_type = sort_options_cls.__annotations__["sort_by"]

    # Use default sorting if sort_by is not provided or when sorting by score
    # without an active search context.
    if not sort_by or (not search_context and sort_by == ChatSortBy.SCORE):
        if search_context:
            return [sort_options_cls(sort_by=sort_by_type.SCORE, order=OrderEnum.DESC)]
        else:
            return DEFAULT_SORT_OPTIONS.get(sort_options_cls, [])
    # Apply custom sorting
    else:
        return [sort_options_cls(sort_by=sort_by, order=order)]


def parse_fields_params(
    include: Optional[List[str]] = Query(None),  # TODO: default values
    exclude: Optional[List[str]] = Query(None),
) -> Optional[FieldFilter]:
    """
    Parse the include and exclude parameters to create a dictionary for Elasticsearch source filtering.

    Args:
        include (Optional[List[str]]): List of fields to include in the Elasticsearch query.
        exclude (Optional[List[str]]): List of fields to exclude from the Elasticsearch query.

    Returns:
        FieldFilter or None: A TypedDict with include and/or exclude fields formatted for Elasticsearch.
    """
    source_filter: FieldFilter = {}

    if include:
        source_filter["includes"] = include

    if exclude:
        source_filter["excludes"] = exclude

    return source_filter if source_filter else None
