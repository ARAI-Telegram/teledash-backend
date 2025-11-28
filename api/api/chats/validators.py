from typing import List, Optional

from elasticsearch.dsl import Q
from elasticsearch.dsl.query import Query as ESQuery
from fastapi.param_functions import Query

from api.chats.models import ChatSearchField
from api.fulltext_search import create_flexible_search_query
from api.sort_config import ChatSortBy, ChatSortOptions, OrderEnum, SortParams
from api.validators import convert_enum_to_value, parse_sort_params
from common.database.models.chat import ChatType


def parse_flexible_chat_search_query(
    search_query: Optional[str] = Query(None),
) -> Optional[ESQuery]:
    if search_query:
        return create_flexible_search_query(
            fields=[field.value for field in ChatSearchField],
            search_query=search_query,
            fuzzy=True,
        )
    return None


def parse_chat_filter(
    type: Optional[ChatType] = None,
    is_verified: Optional[bool] = None,
    is_restricted: Optional[bool] = None,
    is_scam: Optional[bool] = None,
    is_fake: Optional[bool] = None,
    tags: Optional[List[str]] = Query(None),
) -> Optional[ESQuery]:
    """
    Build Elasticsearch filter query from chat attribute filters.

    Constructs a bool query with term filters for each non-None parameter.
    For tags, all provided tags must be present in the document (AND logic).

    Returns:
        Elasticsearch bool query with all filters, or None if no filters provided
    """
    filters = []
    if type:
        filters.append(Q({"term": {"type": convert_enum_to_value(type)}}))
    if is_verified is not None:
        filters.append(Q({"term": {"verification_status.is_verified": is_verified}}))
    if is_restricted is not None:
        filters.append(Q({"term": {"is_restricted": is_restricted}}))
    if is_scam is not None:
        filters.append(Q({"term": {"verification_status.is_scam": is_scam}}))
    if is_fake is not None:
        filters.append(Q({"term": {"verification_status.is_fake": is_fake}}))
    if tags:
        # All query tags must match document tags
        filters.append(Q("bool", filter=[Q({"term": {"tags": tag}}) for tag in tags]))

    if filters:
        return Q("bool", filter=filters)
    else:
        return None


def parse_chat_sort(
    search_query: Optional[str] = None,
    sort_by: Optional[ChatSortBy] = None,
    order: Optional[OrderEnum] = None,
) -> SortParams[ChatSortOptions]:
    return parse_sort_params(
        sort_options_cls=ChatSortOptions,
        sort_by=sort_by,
        order=order,
        search_context=bool(search_query),
    )
