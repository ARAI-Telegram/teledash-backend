from typing import Optional

from api.fulltext_search import create_flexible_search_query
from api.sort_config import OrderEnum, SortParams, UserSortBy, UserSortOptions
from api.users.models import UserSearchField
from api.validators import parse_sort_params
from elasticsearch.dsl import Q
from elasticsearch.dsl.query import Query as ESQuery
from fastapi.param_functions import Query


def parse_flexible_user_search_query(
    search_query: Optional[str] = Query(None),
) -> Optional[ESQuery]:
    if search_query:
        return create_flexible_search_query(
            fields=[field.value for field in UserSearchField],
            search_query=search_query,
            fuzzy=True,
        )
    return None


def parse_user_filter(
    is_deleted: Optional[bool] = None,
    is_bot: Optional[bool] = None,
    is_verified: Optional[bool] = None,
    is_restricted: Optional[bool] = None,
    is_scam: Optional[bool] = None,
    is_fake: Optional[bool] = None,
    is_support: Optional[bool] = None,
    phone_number: Optional[str] = None,
) -> Optional[ESQuery]:
    """
    Build Elasticsearch filter query from user attribute filters.

    Constructs a bool query with term filters for each non-None parameter.
    All filters use exact matching (term queries).

    Returns:
        Elasticsearch bool query with all filters, or None if no filters provided
    """
    params = {
        "is_deleted": is_deleted,
        "is_bot": is_bot,
        "verification_status.is_verified": is_verified,
        "is_restricted": is_restricted,
        "verification_status.is_scam": is_scam,
        "verification_status.is_fake": is_fake,
        "is_support": is_support,
        "phone_number": phone_number,
    }
    filters = []

    # Loop through the filters dictionary and add non-None filters to the query
    for field, value in params.items():
        if value is not None:
            filters.append(Q("term", **{field: value}))

    if filters is not None:
        return Q("bool", filter=filters)
    else:
        return None


def parse_user_sort(
    search_query: Optional[str] = None,
    sort_by: Optional[UserSortBy] = None,
    order: Optional[OrderEnum] = None,
) -> SortParams[UserSortOptions]:
    return parse_sort_params(
        sort_options_cls=UserSortOptions,
        sort_by=sort_by,
        order=order,
        search_context=bool(search_query),
    )
