import logging
from typing import Optional, Tuple

from api.accounts.auth import Account, get_current_active_verified_user
from api.chats.delete_chat_data import delete_chat_data
from api.chats.leave_chat import leave_chat
from api.chats.models import (
    ChatSearchField,
    ChatStats,
    ChatStatsFields,
    DeleteChatResponse,
)
from api.chats.validators import (
    parse_chat_filter,
    parse_chat_sort,
    parse_flexible_chat_search_query,
)
from api.database import get_database
from api.database.aggregations import aggregate_classification_results
from api.database.aggregations_chats import get_chat_metrics
from api.database.database import Database, UpdateTargetNotFoundError
from api.fulltext_search import create_highlight_config
from api.pagination import PaginatedChats, PaginatedResponse, Pagination
from api.sort_config import ChatSortOptions
from api.storage import get_storage
from api.validators import FieldFilter, SortParams, parse_fields_params
from elasticsearch.dsl import Q
from elasticsearch.dsl.query import Query as ESQuery
from elasticsearch.exceptions import NotFoundError
from fastapi import APIRouter, Depends, HTTPException, status

from common.database.models.chat import ChatIn, ChatMetrics, ChatOut
from common.storage import Storage

logger = logging.getLogger(__name__)


def get_chats_router(app) -> APIRouter:
    """Create and configure the chats API router."""
    router = APIRouter()
    current_active_verified_user = get_current_active_verified_user()
    pagination = Pagination(maximum_limit=100)

    @router.get(
        "/chats",
        response_description="List matching chats",
        tags=["chats"],
        response_model=PaginatedChats,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def list_chats(
        filter: Optional[ESQuery] = Depends(parse_chat_filter),
        search_query: Optional[ESQuery] = Depends(parse_flexible_chat_search_query),
        aggregations: Optional[bool] = True,
        sort: SortParams[ChatSortOptions] = Depends(parse_chat_sort),
        fields: Optional[FieldFilter] = Depends(parse_fields_params),
        pagination: Tuple[int, int, int] = Depends(pagination.parse_params),
        account: Account = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
    ) -> PaginatedResponse:
        """
        Search and list chats with optional metrics aggregation.

        Supports text search across chat titles, filtering by chat type and properties,
        and optionally includes aggregated message metrics (count, latest message time)
        for each chat. Results include search highlighting.
        """
        offset, limit, max_limit = pagination
        from_ = offset if offset else 0

        highlight_config = create_highlight_config(
            fields=[field.value for field in ChatSearchField]
        )

        result: list[ChatOut] = [
            doc
            async for doc in database.chats.find(
                search_query=search_query,
                filter=filter,
                fields=fields,
                from_=from_,
                size=limit,
                sort=sort,
                highlight=highlight_config,
            )
        ]

        count_total = await database.chats.count(
            filter=filter, search_query=search_query
        )

        if aggregations:
            chat_ids = [chat.id for chat in result]

            # Fetch metrics for all chats in a single query
            try:
                chat_metrics = await get_chat_metrics(
                    chat_ids, total=False, yesterday=True
                )
                # Add metrics to each chat
                for chat in result:
                    if chat.id in chat_metrics:
                        metrics_dict = chat_metrics[chat.id]
                        if metrics_dict:
                            chat.metrics = ChatMetrics(**metrics_dict)
                        else:
                            chat.metrics = None
                    else:
                        chat.metrics = None
            except Exception as e:
                logger.error(f"Error fetching chat metrics: {str(e)}", exc_info=True)

        return PaginatedChats.create(
            data=result, sort=sort[0], params=pagination, count_total=count_total
        )

    @router.get(
        "/chats/stats",
        response_description="Return chat statistics (top tags)",
        tags=["chats"],
        response_model=ChatStats,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def get_chats_stats(
        filter: Optional[ESQuery] = Depends(parse_chat_filter),
        search_query: Optional[ESQuery] = Depends(parse_flexible_chat_search_query),
        account: Account = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
    ) -> ChatStats:
        """Get aggregated statistics including top tags and most frequent
        chat attributes.
        """
        stats_result = {}
        TOP_N_AGGREGATIONS = 20

        try:
            for field in ChatStatsFields:
                try:
                    # Extract results using the field's value
                    aggregation_result = await database.chats.get_top_field_values(
                        field=field.value,
                        size=TOP_N_AGGREGATIONS,
                        search_query=search_query,
                        filter=filter,
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

            return ChatStats.model_validate(stats_result)

        except NotFoundError:
            return ChatStats.model_validate({})

    @router.get(
        "/chats/{id}",
        response_description="Get a single chat",
        tags=["chats"],
        response_model=ChatOut,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def get_chat(
        id: int,
        account: Account = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
    ) -> ChatOut:
        """Retrieve a single chat with activity metrics and
        classification statistics.
        """
        chat: ChatOut | None = await database.chats.find_one(
            filter=Q("ids", values=[id])
        )

        if not chat:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chat with ID {id} not found",
            )

        try:
            chat_metrics_dict = await get_chat_metrics([id], total=True, yesterday=True)

            # If metrics were found for this chat, attach them
            if chat.id in chat_metrics_dict and chat_metrics_dict[chat.id]:
                chat.metrics = ChatMetrics(**chat_metrics_dict[chat.id])
            else:
                chat.metrics = None
        except Exception as e:
            logger.error(
                f"Error while fetching chat metrics for chat {chat.id}: {e}",
                exc_info=True,
            )

        try:
            classification_aggregated = await aggregate_classification_results(
                chat.id, database
            )
            chat.classification_aggregated = classification_aggregated
        except Exception as e:
            logger.error(
                f"Error while fetching aggregated classification results for chat {chat.id}: {e}",
                exc_info=True,
            )

        # TODO: paginate members

        return chat

    @router.put(
        "/chats/{id}",
        response_description="Update a chat",
        tags=["chats"],
        response_model=ChatOut,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def update_chat(
        id: int,
        chat: ChatIn,
        account: Account = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
    ) -> ChatOut:
        """Update chat metadata such as language and tags."""
        search_query = Q("ids", values=[id])
        update_query = chat.model_dump(exclude_unset=True, exclude_none=True)

        if "tags" in update_query and update_query["tags"]:
            update_query["tags"] = [tag.lower() for tag in update_query["tags"]]

        try:
            updated_chat = await database.chats.update_one(
                query=search_query, update=update_query
            )
            return updated_chat
        except UpdateTargetNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chat with id {id} not found",
            )

    @router.delete(
        "/chats/{id}",
        response_description="Leave and/or delete a chat and its data",
        tags=["chats"],
        response_model=DeleteChatResponse,
        response_model_exclude_none=True,
        status_code=status.HTTP_200_OK,
    )
    async def delete_chat(
        id: int,
        leave: bool = False,
        delete: bool = False,
        attachments: bool = False,
        account: Account = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
        storage: Storage = Depends(get_storage),
    ) -> DeleteChatResponse:
        """
        Leave and/or delete a single chat and its related data.

        - `leave`: Leave the chat in Telegram
        - `delete`: Delete all chat data (record, messages, metrics, vectorized index)
        - `attachments`: Also delete attachment files from storage — requires `delete=true`

        Leave is always performed before deletion to prevent new data arriving
        during the deletion process.

        Attachment deletion: after the chat's messages are removed, any storage file
        that is no longer referenced by any message in the database is deleted. This
        means files shared with other chats (e.g. via forwarding) are kept, but files
        exclusively used by this chat are removed.
        """
        if attachments and not delete:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="attachments=true requires delete=true",
            )
        if not leave and not delete:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="At least one of leave or delete must be true",
            )

        chat = await database.chats.find_one(filter=Q("ids", values=[id]))
        if not chat:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chat with ID {id} not found",
            )

        leave_results = None

        # 1. Leave first — prevents new data from arriving during deletion
        if leave:
            try:
                leave_results = await leave_chat(database, id)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=str(e),
                )

        # 2. Delete data
        deleted_storage_objects: int | None = None
        errors: list[str] | None = None
        if delete:
            try:
                deleted_storage_objects, errors = await delete_chat_data(
                    database,
                    id,
                    storage if attachments else None,
                )
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to delete chat data: {str(e)}",
                )

        return DeleteChatResponse(
            leave_results=leave_results,
            deleted_storage_objects=deleted_storage_objects,
            errors=errors if errors else None,
        )

    return router
