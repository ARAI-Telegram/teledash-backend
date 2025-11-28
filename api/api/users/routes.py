import logging
from datetime import timedelta
from typing import Optional, Tuple

from elasticsearch.dsl import Q
from elasticsearch.dsl.query import Query as ESQuery
from fastapi import APIRouter, Depends, HTTPException, status

from api.accounts.auth import (
    get_current_active_verified_superuser,
    get_current_active_verified_user,
)
from api.accounts.models import AccountRead
from api.database import get_database
from api.database.aggregations import aggregate_metrics
from api.database.database import Database
from api.fulltext_search import create_highlight_config
from api.pagination import PaginatedResponse, PaginatedUsers, Pagination
from api.sort_config import UserSortOptions
from api.storage import get_storage
from api.users.models import UserSearchField
from api.users.validators import (
    parse_flexible_user_search_query,
    parse_user_filter,
    parse_user_sort,
)
from api.validators import FieldFilter, SortParams, parse_fields_params
from common.database.models.user import UserMetrics, UserOut
from common.storage import Storage
from common.utils import naive_utcnow

logger = logging.getLogger(__name__)


def get_users_router(app) -> APIRouter:
    """Create and configure the users API router."""
    router = APIRouter()
    current_active_verified_user = get_current_active_verified_user()
    pagination = Pagination(maximum_limit=100)

    @router.get(
        "/users",
        response_description="List matching users",
        tags=["users"],
        response_model=PaginatedUsers,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def list_users(
        filter: Optional[ESQuery] = Depends(parse_user_filter),
        search_query: Optional[ESQuery] = Depends(parse_flexible_user_search_query),
        sort: SortParams[UserSortOptions] = Depends(parse_user_sort),
        fields: Optional[FieldFilter] = Depends(parse_fields_params),
        pagination: Tuple[int, int, int] = Depends(pagination.parse_params),
        account: AccountRead = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
    ) -> PaginatedResponse:
        """
        Search and list users with filtering, sorting, and pagination.

        Supports text search across usernames and names, filtering by user properties
        (bot, verified, scam, etc.), and field projection. Results include search
        highlighting for matched terms.
        """
        offset, limit, max_limit = pagination
        from_ = offset if offset else 0

        highlight_config = create_highlight_config(
            fields=[field.value for field in UserSearchField]
        )

        result = [
            doc
            async for doc in database.users.find(
                search_query=search_query,
                filter=filter,
                fields=fields,
                from_=from_,
                size=limit,
                sort=sort,
                highlight=highlight_config,
            )
        ]

        count_total = await database.users.count(
            filter=filter, search_query=search_query
        )

        return PaginatedUsers.create(
            data=result,
            sort=sort[0],
            params=pagination,
            count_total=count_total,
        )

    @router.get(
        "/users/{id}",
        response_description="Get a user profile",
        tags=["users"],
        response_model=UserOut,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def get_user(
        id: int,
        account: AccountRead = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
    ) -> UserOut:
        """Retrieve a single user profile with activity metrics and chat memberships."""
        user_doc = await database.users.find_one(filter=Q("ids", values=[id]))

        if not user_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {id} not found",
            )

        # get user metrics
        try:
            activity_total = await aggregate_metrics(
                database,
                {"metadata__user_id": id, "metadata__type": "message_posted"},
                "sum",
            )

            # Calculate the timestamp for 24 hours ago
            yesterday = naive_utcnow() - timedelta(days=1)

            activity_last_day = await aggregate_metrics(
                database,
                {
                    "metadata__user_id": id,
                    "metadata__type": "message_posted",
                    "ts": {"gte": yesterday},
                },
                "sum",
            )

            user_doc.metrics = UserMetrics(
                activity_total=activity_total, activity_last_day=activity_last_day
            )
        except Exception as e:
            logger.error(f"Error calculating user metrics: {e}", exc_info=True)

        # find groups user is member of
        filter = Q("term", members__id=user_doc.id)
        fields: FieldFilter = {"includes": ["id", "title", "username"]}
        chats_user_is_member = [
            doc
            async for doc in database.chats.find(
                filter=filter,
                fields=fields,
            )
        ]
        user_doc.in_chats = [chat.create_ref() for chat in chats_user_is_member]

        return user_doc

    @router.delete(
        "/users/{id}",
        response_description="Delete a user and their messages",
        tags=["users"],
        status_code=status.HTTP_200_OK,
    )
    async def delete_user(
        id: int,
        account: AccountRead = Depends(get_current_active_verified_superuser()),
        database: Database = Depends(get_database),
        storage: Storage = Depends(get_storage),
    ) -> dict[str, str | int]:
        """
        Delete a user, all their messages, and clean up orphaned storage objects.
        Only accessible to super users.

        This operation:
        1. Collects all storage object references from the user's messages
        2. Deletes all messages posted by this user
        3. Checks each storage object and deletes orphaned ones
        4. Deletes the user record

        Args:
            id: The user ID to delete
            account: The authenticated super user account
            database: The database connection
            storage: The storage connection for file operations

        Returns:
            200 OK with deletion confirmation including counts of deleted messages and storage objects
            404 Not Found if the user doesn't exist
        """
        # First verify that the user exists
        user_doc = await database.users.find_one(filter=Q("ids", values=[id]))

        if not user_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {id} not found",
            )

        try:
            # First, collect all storage references from user's messages before deletion
            storage_refs_to_check = set()

            # Use scroll API to get all messages from this user (no size limit)
            search_body = {
                "query": {"term": {"from_user.id": id}},
                "_source": ["attachment.storage_refs"],
                "size": 1000,  # Batch size for scroll
            }

            # Initialize scroll
            messages_response = await database.es_client.search(
                index="messages",
                body=search_body,
                scroll="1m",  # Keep scroll context for 1 minute
            )

            scroll_id = messages_response.get("_scroll_id")

            # Process first batch and subsequent batches
            while True:
                hits = messages_response.get("hits", {}).get("hits", [])

                if not hits:
                    break

                # Extract storage references from this batch
                for hit in hits:
                    source = hit.get("_source", {})
                    attachment = source.get("attachment", {})
                    storage_refs = attachment.get("storage_refs", [])

                    for ref in storage_refs:
                        if "bucket" in ref and "object" in ref:
                            storage_refs_to_check.add((ref["bucket"], ref["object"]))

                # Get next batch
                try:
                    messages_response = await database.es_client.scroll(
                        scroll_id=scroll_id, scroll="1m"
                    )
                except Exception as scroll_error:
                    logger.error(f"Scroll error: {scroll_error}", exc_info=True)
                    break

            # Clean up scroll context
            if scroll_id:
                try:
                    await database.es_client.clear_scroll(scroll_id=scroll_id)
                except Exception:
                    pass  # Ignore cleanup errors

            logger.info(
                f"Found {len(storage_refs_to_check)} unique storage objects to check for cleanup"
            )

            # Delete all messages from this user
            delete_messages_body = {"query": {"term": {"from_user.id": id}}}

            delete_response = await database.es_client.delete_by_query(
                index="messages", body=delete_messages_body, refresh=True
            )

            deleted_count = delete_response.get("deleted", 0)
            logger.info(f"Successfully deleted {deleted_count} messages for user {id}")

            # Now check each storage object to see if it's still referenced by other messages
            deleted_storage_count, _ = await storage.cleanup_orphaned_objects(
                database, storage_refs_to_check
            )

            # Then delete the user using the document's Elasticsearch ID
            deleted_user = await database.users.delete_by_id(doc_id=str(user_doc.id))

            if not deleted_user:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to delete user",
                )

            return {
                "message": f"User {id} and {deleted_count} messages deleted successfully",
                "deleted_messages_count": deleted_count,
                "deleted_storage_objects_count": deleted_storage_count,
            }

        except Exception as e:
            logger.error(f"Error deleting user {id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete user",
            )

    return router
