import logging
from typing import Optional, Tuple

from elasticsearch.dsl import Q
from elasticsearch.dsl.query import Query as ESQuery
from elasticsearch.exceptions import NotFoundError
from fastapi import APIRouter, Depends, HTTPException, status

from api.accounts.auth import Account, get_current_active_verified_user
from api.chats.deletion import delete_chats_data
from api.chats.models import (
    ChatSearchField,
    ChatStats,
    ChatStatsFields,
    DeleteChatsRequest,
)
from api.chats.validators import (
    parse_chat_filter,
    parse_chat_sort,
    parse_flexible_chat_search_query,
)
from api.database import get_database
from api.database.aggregations import aggregate_classification_results
from api.database.aggregations_chats import get_chat_metrics
from api.database.database import Database
from api.fulltext_search import create_highlight_config
from api.pagination import PaginatedChats, PaginatedResponse, Pagination
from api.sort_config import ChatSortOptions
from api.storage import get_storage
from api.validators import FieldFilter, SortParams, parse_fields_params
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

        updated_chat = await database.chats.update_one(
            query=search_query, update=update_query
        )

        if not updated_chat:
            raise HTTPException(
                status_code=status.HTTP_304_NOT_MODIFIED,
                detail=f"Chat with id {id} was not updated",
            )

        return updated_chat

    @router.delete(
        "/chats",
        response_description="Delete multiple chats and their related data",
        description=(
            "⚠️ WARNING: Ensure clients have left these chats before deletion, "
            "or scraping will automatically restart. This deletes chat records, "
            "message indices, metrics, vectorized indices and, if requested, "
            "storage objects (attachments)."
        ),
        tags=["chats"],
        status_code=status.HTTP_200_OK,
    )
    async def delete_chats(
        request: DeleteChatsRequest,
        account: Account = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
        storage: Storage = Depends(get_storage),
    ) -> dict:
        """
        Delete multiple chats and all their related data.

        This deletion is useful for:
        - Starting over with a chat after scraping issues (use delete_attachments=False)
        - Cleaning up data for chats that are no longer being monitored

        ⚠️ IMPORTANT WARNINGS:
        - Ensure no active scraping is happening for these chats during deletion
          to avoid data inconsistencies and race conditions
        - If the client is still a member of these chats, scraping will automatically
          restart. Use the client management endpoints to leave chats first for
          permanent deletion.
        - Only use delete_attachments=True when permanently removing chats where
          clients have left. For restarting scraping, use delete_attachments=False
          (default) to avoid potential data loss from race conditions.

        This operation deletes:
        - Chat records from the chats index
        - Message indices for each chat (messages_{chat_id})
        - Metrics associated with the chats
        - Vectorized message indices (vectorized_messages_{chat_id}) if they exist
        - Storage objects (attachments) if delete_attachments=True

        Args:
            request: DeleteChatsRequest containing chat_ids and delete_attachments flag

        Returns:
            Deletion statistics including counts of deleted resources
            and any errors
        """
        # Verify that at least some of the chats exist (single query for efficiency)
        existing_chats_query = Q("ids", values=request.chat_ids)
        existing_chat_docs = [
            chat async for chat in database.chats.find(filter=existing_chats_query)
        ]
        existing_chats = [chat.id for chat in existing_chat_docs]

        if not existing_chats:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"None of the specified chats were found: {request.chat_ids}",
            )

        # Perform deletion
        try:
            stats = await delete_chats_data(
                database,
                existing_chats,
                storage if request.delete_attachments else None,
            )

            response = {
                "message": f"Successfully deleted {stats.deleted_chats} chats",
                "warning": (
                    "⚠️ If the client is still a member of these chats, scraping "
                    "will automatically restart. Use the client management endpoints "
                    "to leave the chats first to permanently stop scraping."
                ),
                "deleted_chats": stats.deleted_chats,
                "processed_message_indices": stats.deleted_message_indices,
                "deleted_metrics": stats.deleted_metrics,
                "processed_vectorized_indices": stats.deleted_vectorized_indices,
                "deleted_storage_objects": stats.deleted_storage_objects,
            }

            if stats.errors:
                response["errors"] = stats.errors
                response["message"] += " (with some errors)"

            # Include info about chats that weren't found
            not_found = [cid for cid in request.chat_ids if cid not in existing_chats]
            if not_found:
                response["not_found"] = not_found
                response["message"] += (
                    f". {len(not_found)} chat(s) not found: {not_found}"
                )

            return response

        except Exception as e:
            logger.error(f"Error deleting chats {existing_chats}: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete chats: {str(e)}",
            )

    return router
