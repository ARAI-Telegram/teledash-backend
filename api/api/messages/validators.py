from datetime import datetime
from typing import List, Optional, Tuple

from elasticsearch.dsl import Q
from elasticsearch.dsl.query import Query as ESQuery
from fastapi import HTTPException, Query, status
from pyrogram import enums as pyrogram_enums

from api.fulltext_search import create_exact_match_query, create_flexible_search_query
from api.messages.models import MESSAGE_SEARCH_TYPE_FIELD_MAP, MessageSearchType
from api.sort_config import MessageSortBy, MessageSortOptions, OrderEnum, SortParams
from api.validators import convert_enum_to_value, parse_sort_params


def parse_message_search_query(
    search_query: Optional[str] = Query(None),
    search_type: MessageSearchType = Query(MessageSearchType.FLEXIBLE),
) -> Optional[ESQuery]:
    """
    Parse message search query based on search type (EXACT, FLEXIBLE, FUZZY, or SEMANTIC).

    Routes the search query to the appropriate parser:
    - EXACT: Phrase and token parsing with exclusion support
    - FLEXIBLE: Standard multi-match query (no fuzziness)
    - FUZZY: Multi-match with AUTO fuzziness for typo tolerance
    - SEMANTIC: Returns None (handled separately by semantic search API)

    Args:
        search_query: The search string from the user
        search_type: Type of search algorithm to use

    Returns:
        Elasticsearch query object for EXACT/FLEXIBLE/FUZZY, or None for SEMANTIC/no query
    """
    if not search_query or search_type.is_semantic():
        return None

    fields = MESSAGE_SEARCH_TYPE_FIELD_MAP.get(
        search_type, MESSAGE_SEARCH_TYPE_FIELD_MAP[MessageSearchType.FLEXIBLE]
    )

    if search_type == MessageSearchType.EXACT:
        return create_exact_match_query(
            fields=fields,
            search_query=search_query,
        )
    else:
        fuzzy = search_type == MessageSearchType.FUZZY
        return create_flexible_search_query(
            fields=fields,
            search_query=search_query,
            fuzzy=fuzzy,
        )


def parse_flexible_message_search_query(
    search_query: Optional[str] = None, fuzzy: Optional[bool] = True
) -> Optional[ESQuery]:
    if search_query:
        return create_flexible_search_query(
            fields=MESSAGE_SEARCH_TYPE_FIELD_MAP[MessageSearchType.FLEXIBLE],
            search_query=search_query,
            fuzzy=fuzzy,
        )
    return None


# Note: Manual search parser - consider merging with regular parser in future refactoring
def parse_message_search_query_manual(
    search_query: Optional[str] = None,
    search_type: MessageSearchType = MessageSearchType.FLEXIBLE,
) -> Optional[ESQuery]:
    if search_query is None:
        return search_query

    fields = MESSAGE_SEARCH_TYPE_FIELD_MAP.get(
        search_type, MESSAGE_SEARCH_TYPE_FIELD_MAP[MessageSearchType.FLEXIBLE]
    )

    if search_type == MessageSearchType.EXACT:
        return create_exact_match_query(
            fields=fields,
            search_query=search_query,
        )

    elif search_type.is_semantic():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Saving semantic searches is not supported.",
        )

    else:
        return create_flexible_search_query(
            fields=fields,
            search_query=search_query,
            fuzzy=search_type == MessageSearchType.FUZZY,
        )


def parse_message_filter_manual(
    from_user_ids: Optional[List[int]] = [],
    chat_ids: Optional[List[int]] = [],
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    is_empty: Optional[bool] = None,
    attachment_type: Optional[pyrogram_enums.MessageMediaType] = None,
    tags: Optional[List[str]] = [],
) -> Optional[ESQuery]:
    """
    A wrapper function that uses empty arrays as default values for parameters of type List,
    thereby preventing parse_message_filter from applying `Query(None)` as a default value
    when called manually (instead of as a FastAPI path operation dependency).
    """
    es_query, _ = parse_message_filter(
        from_user_ids, chat_ids, date_from, date_to, is_empty, attachment_type, tags
    )

    return es_query


def parse_message_filter(
    from_user_ids: Optional[List[int]] = Query(None),
    chat_ids: Optional[List[int]] = Query(None),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    is_empty: Optional[bool] = None,
    attachment_type: Optional[pyrogram_enums.MessageMediaType] = None,
    tags: Optional[List[str]] = Query(None),
) -> Tuple[Optional[ESQuery], dict]:
    """
    Parse message filter parameters into dual query formats for different search backends.

    Creates two separate filter representations:
    1. Full Elasticsearch query with all filters (for fulltext/exact search)
    2. Simplified filter dict with only chat_ids and date range (for semantic search API)

    The semantic search backend has limited filter support, so only chat and date
    filters are passed through. Other filters (user, tags, attachments) are applied
    only in Elasticsearch.

    Args:
        from_user_ids: Filter messages by sender user IDs (ES only)
        chat_ids: Filter by chat IDs (both ES and semantic)
        date_from: Start of date range (both ES and semantic)
        date_to: End of date range (both ES and semantic)
        is_empty: Filter empty/non-empty messages (ES only)
        attachment_type: Filter by media type like PHOTO, VIDEO, etc. (ES only)
        tags: Filter by tags, all must be present (ES only)

    Returns:
        Tuple of:
        - Elasticsearch bool query with all applicable filters, or None
        - Dict with chat_ids/date_from/date_to for semantic search, or empty dict
    """
    filters = []
    semantic_filters = {}

    # Elasticsearch filters
    if from_user_ids:
        filters.append(Q("terms", **{"from_user.id": from_user_ids}))

    if is_empty is not None:  # Check for None to include False values
        filters.append(Q("term", **{"is_empty": is_empty}))

    if attachment_type:
        filters.append(
            Q("term", **{"attachment.type": convert_enum_to_value(attachment_type)})
        )

    if tags:
        # All query tags must match document tags
        filters.append(Q("bool", filter=[Q("term", **{"tags": tag}) for tag in tags]))

    # Filters for Elasticsearch query
    if chat_ids:
        filters.append(Q("terms", **{"chat.id": chat_ids}))  # Add to ES filter
        semantic_filters["chat_ids"] = chat_ids  # Only chat_ids for semantic search

    if date_from or date_to:
        date_range_query = {}
        if date_from:
            semantic_filters["date_from"] = date_from
            date_range_query["gte"] = date_from
        if date_to:
            semantic_filters["date_to"] = date_to
            date_range_query["lt"] = date_to
        filters.append(Q("range", **{"date": date_range_query}))

    es_query = Q("bool", filter=filters) if filters else None

    return es_query, semantic_filters


def parse_message_sort(
    search_query: Optional[str] = None,
    sort_by: Optional[MessageSortBy] = None,
    order: Optional[OrderEnum] = None,
) -> SortParams[MessageSortOptions]:
    return parse_sort_params(
        sort_options_cls=MessageSortOptions,
        sort_by=sort_by,
        order=order,
        search_context=bool(search_query),
    )
