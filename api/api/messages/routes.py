import logging
from typing import Any, Dict, List, Optional, Tuple, cast

from elasticsearch.dsl import Q
from elasticsearch.dsl.query import Query as ESQuery
from elasticsearch.exceptions import NotFoundError
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.orm.attributes import flag_modified

from api.accounts.auth import Account, get_account_db, get_current_active_verified_user
from api.database import get_database
from api.database.database import Database, UpdateTargetNotFoundError
from api.fulltext_search import create_highlight_config
from api.messages.models import (
    MESSAGE_SEARCH_TYPE_FIELD_MAP,
    MessageSearchType,
    MessageStats,
    MessageStatsFields,
)
from api.messages.semantic_messages_client import (
    get_semantic_messages,
    map_classifier_results_to_messages,
)
from api.messages.validators import (
    parse_flexible_message_search_query,
    parse_message_filter,
    parse_message_search_query,
    parse_message_sort,
)
from api.pagination import PaginatedMessages, PaginatedResponse, Pagination
from api.sort_config import MessageSortOptions, sort_semantic_search_results
from api.validators import FieldFilter, SortParams, parse_fields_params
from common.database.models.message import MessageIn, MessageOut
from common.utils import naive_utcnow

logger = logging.getLogger(__name__)


def get_messages_router(app) -> APIRouter:
    """Create and configure the messages API router."""
    router = APIRouter()
    current_active_verified_user = get_current_active_verified_user()
    pagination = Pagination(maximum_limit=50)

    @router.get(
        "/messages",
        response_description="List matching messages",
        tags=["messages"],
        response_model=PaginatedMessages,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def list_messages(
        filter: Tuple[Optional[ESQuery], dict] = Depends(parse_message_filter),
        chat_tags: Optional[List[str]] = Query(None),
        search_type: MessageSearchType = Query(MessageSearchType.FLEXIBLE),
        search_query: Optional[ESQuery] = Depends(parse_message_search_query),
        # Store unparsed search query string to query semantic search API
        search_query_string: str = Query(None, alias="search_query"),
        sort: SortParams[MessageSortOptions] = Depends(parse_message_sort),
        fields: Optional[FieldFilter] = Depends(parse_fields_params),
        pagination: Tuple[int, int, int] = Depends(pagination.parse_params),
        account: Account = Depends(current_active_verified_user),
        saved_search_id: Optional[str] = None,
        database: Database = Depends(get_database),
        account_database: SQLAlchemyUserDatabase = Depends(get_account_db),
    ) -> PaginatedResponse:
        """
        Search and list messages with advanced filtering and multiple search modes.

        Supports flexible/exact/fuzzy text search, semantic search via external service,
        filtering by chat tags, date ranges, and message properties. Results are paginated
        and can be sorted by various fields. Optionally updates saved search timestamps.
        """
        offset, limit, max_limit = pagination
        from_ = offset if offset else 0

        es_filter, semantic_filter = filter
        valid_semantic_search = search_type.is_semantic() and search_query_string

        # Handle chat_tags filtering if provided
        if chat_tags:
            # We want chats that have ANY of the provided tags (OR logic)
            tag_queries = [Q("term", **{"tags": tag}) for tag in chat_tags]
            chat_tags_filter = Q("bool", should=tag_queries, minimum_should_match=1)

            # Query chats index and get IDs of chats matching the tags
            chat_tags_fields: FieldFilter = {"excludes": ["*"]}
            chat_ids = [
                chat_doc.id
                async for chat_doc in database.chats.find(
                    filter=chat_tags_filter, fields=chat_tags_fields
                )
            ]

            if chat_ids:
                # Use the chat IDs to filter messages
                message_chat_filter = Q("terms", **{"chat.id": chat_ids})

                if es_filter is None:
                    es_filter = Q("bool", filter=[message_chat_filter])
                else:
                    es_filter.filter.append(message_chat_filter)

        highlight_config = None

        try:
            # Handle the special case of semantic search
            if valid_semantic_search:
                semantic_message_matches = await get_semantic_messages(
                    search_query_string,
                    search_type,
                    chat_ids=semantic_filter.get("chat_ids", None),
                    date_from=semantic_filter.get("date_from", None),
                    date_to=semantic_filter.get("date_to", None),
                )

                # Create a score map for the script
                score_map = {
                    match["id"]: match["score"] for match in semantic_message_matches
                }
                semantic_message_ids = list(score_map.keys())

                es_filter = (
                    Q("ids", values=semantic_message_ids)
                    if es_filter is None
                    else Q(
                        "bool",
                        filter=[es_filter, Q("ids", values=semantic_message_ids)],
                    )
                )

            # Configure highlighting based on search_type
            if search_query:
                fields_to_highlight = MESSAGE_SEARCH_TYPE_FIELD_MAP.get(
                    search_type,
                    MESSAGE_SEARCH_TYPE_FIELD_MAP[MessageSearchType.FLEXIBLE],
                )

                # Only configure highlighting if fields not None (semantic search has no fields)
                if fields_to_highlight:
                    highlight_config = create_highlight_config(
                        fields=fields_to_highlight
                    )

            # Dynamically construct arguments for the `find` method
            find_kwargs = {
                "search_query": search_query,
                "filter": es_filter,
                "fields": fields,
                "highlight": highlight_config,
            }

            # Only include pagination and sorting if it's not valid semantic search
            if not valid_semantic_search:
                find_kwargs["from_"] = from_
                find_kwargs["size"] = limit
                find_kwargs["sort"] = sort
            result = [doc async for doc in database.messages.find(**find_kwargs)]

            # Update saved search if provided
            if saved_search_id:
                saved_searches_update = []
                for saved_search in cast(List[Dict[str, Any]], account.saved_searches):
                    if saved_search["id"] == saved_search_id:
                        saved_search["last_visited"] = naive_utcnow().isoformat()
                        saved_searches_update.append(saved_search)
                    else:
                        saved_searches_update.append(saved_search)

                # SQLAlchemy skips the update when the field is not manually flagged as modified
                flag_modified(account, "saved_searches")
                await account_database.update(
                    account,
                    update_dict={"saved_searches": saved_searches_update},
                )

            # Return appropriate response based on search type
            if not valid_semantic_search:
                # Exact, flexible, fuzzy or no search query provided
                count_total = await database.messages.count(
                    filter=es_filter, search_query=search_query
                )
                return PaginatedMessages.create(
                    data=result,
                    params=pagination,
                    sort=sort[0],
                    count_total=count_total,
                )

            else:  # Valid semantic search
                message_outs = map_classifier_results_to_messages(
                    messages=result, score_map=score_map
                )

                sorted_filtered_message_outs = []
                if message_outs:
                    sorted_filtered_message_outs = sort_semantic_search_results(
                        message_outs, sort
                    )

                # Apply pagination
                paginated_messages = sorted_filtered_message_outs[from_ : from_ + limit]

                # Return paginated response
                return PaginatedMessages.create(
                    data=paginated_messages,
                    params=(from_, limit, max_limit),
                    sort=sort[0],
                    count_total=len(sorted_filtered_message_outs),
                )

        except NotFoundError:
            # Handle case when messages indices not yet exist
            return PaginatedMessages.create(
                data=[],
                params=pagination,
                sort=sort[0],
                count_total=0,
            )

    @router.get(
        "/messages/stats",
        response_description="Return message statistics (top hashtags, domains, etc.)",
        tags=["messages"],
        response_model=MessageStats,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def get_messages_stats(
        filter: Tuple[Optional[ESQuery], dict] = Depends(parse_message_filter),
        search_query: Optional[ESQuery] = Depends(
            parse_flexible_message_search_query
        ),  # TODO: is a search query and filter here necessary? If so: what about search_type?
        account: Account = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
    ) -> MessageStats:
        """Get aggregated statistics including top hashtags, domains, and message attributes."""
        stats_result = {}
        es_filter, _ = filter
        TOP_N_AGGREGATIONS = 20
        try:
            for field in MessageStatsFields:
                try:
                    # Extract results using the field's value
                    aggregation_result = await database.messages.get_top_field_values(
                        field=field.value,
                        size=TOP_N_AGGREGATIONS,
                        search_query=search_query,
                        filter=es_filter,
                    )
                    aggregation_result.sort(key=lambda v: v.count, reverse=True)
                    # Store results with the field's name as a key if any
                    if len(aggregation_result) > 0:
                        stats_result[field.name.lower()] = aggregation_result
                except Exception as e:
                    logger.error(
                        f"Error while fetching aggregations for {field.name.lower()}: {e}",
                        exc_info=True,
                    )
                    continue

            return MessageStats.model_validate(stats_result)

        except NotFoundError:
            return MessageStats.model_validate({})

    @router.get(
        "/messages/{id}",
        response_description="Get a single message",
        tags=["messages"],
        response_model=MessageOut,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def show_message(
        id: str,
        account: Account = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
    ) -> MessageOut:
        message = await database.messages.find_one(filter=Q("ids", values=[id]))

        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Message with ID {id} not found",
            )

        return message

    @router.put(
        "/messages/{id}",
        response_description="Update a message",
        tags=["messages"],
        response_model=MessageOut,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def update_message(
        id: str,
        message: MessageIn,
        account: Account = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
    ) -> MessageOut:
        search_query = Q("ids", values=[id])

        update_query = message.model_dump(
            exclude_unset=True, exclude_none=True, by_alias=True
        )

        if "tags" in update_query and update_query["tags"]:
            update_query["tags"] = [tag.lower() for tag in update_query["tags"]]

        try:
            updated_msg_doc = await database.messages.update_one(
                query=search_query, update=update_query
            )
            return updated_msg_doc
        except UpdateTargetNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Message {id} not found",
            )

    return router
