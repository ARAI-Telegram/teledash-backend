from typing import List, Optional

from elasticsearch.dsl import Q
from elasticsearch.dsl.query import Query as ESQuery
from fastapi import Query

from api.sort_config import ClientSortBy, ClientSortOptions, OrderEnum, SortParams
from api.validators import parse_sort_params


def parse_client_filter(
    is_active: Optional[bool] = None,
    phone_number: Optional[str] = None,
    user_id: Optional[int] = None,
    chat_ids: Optional[List[int]] = Query(None),
) -> Optional[ESQuery]:
    filters = []
    if is_active is not None:
        filters.append(Q("term", is_active=is_active))
    if phone_number:
        filters.append(Q("term", phone_number=phone_number))
    if user_id:
        filters.append(Q("term", user_id=user_id))
    if chat_ids:
        filters.append(Q("terms", chats___id=chat_ids))
        # Elasticsearch uses double underscores for nested fields
    if filters is not None:
        return Q("bool", filter=filters)
    else:
        return None


def parse_client_sort(
    sort_by: Optional[ClientSortBy] = None,
    order: Optional[OrderEnum] = None,
) -> SortParams[ClientSortOptions]:
    return parse_sort_params(
        sort_options_cls=ClientSortOptions,
        sort_by=sort_by,
        order=order,
        search_context=False,  # there's no search context so far for Clients
    )
