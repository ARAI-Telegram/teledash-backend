from typing import Any, Dict, List, cast

from api.accounts.auth import Account, get_account_db, get_current_active_verified_user
from api.database import get_database
from api.database.database import Database
from api.messages.models import MessageSearchType
from api.messages.validators import (
    parse_message_filter_manual,
    parse_message_search_query_manual,
)
from api.saved_searches.models import (
    MessagesCount,
    SavedSearch,
    SavedSearchIn,
    SavedSearchOut,
)
from dateutil.parser import isoparse
from elasticsearch import NotFoundError
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi_users.db import SQLAlchemyUserDatabase


def get_saved_searches_router() -> APIRouter:
    """Create and configure the saved searches API router."""
    router = APIRouter()
    current_active_verified_user = get_current_active_verified_user()

    @router.get(
        "/saved-searches",
        description="List all saved searches",
        response_description="A list of all saved searches",
        tags=["saved_searches"],
        response_model=list[SavedSearchOut],
        response_model_exclude_none=True,
    )
    async def list_saved_searches(
        account: Account = Depends(current_active_verified_user),
    ) -> list[SavedSearchOut]:
        """Retrieve all saved searches for the authenticated user."""
        existing_searches = cast(List[Dict[str, Any]], account.saved_searches) or []

        return [
            SavedSearchOut.model_validate(saved_search)
            for saved_search in existing_searches
        ]

    @router.post(
        "/saved-searches",
        description="Save a search",
        response_description="The saved search",
        tags=["saved_searches"],
        response_model=SavedSearchOut,
        status_code=status.HTTP_201_CREATED,
    )
    async def save_search(
        search: SavedSearchIn,
        account: Account = Depends(current_active_verified_user),
        database: SQLAlchemyUserDatabase = Depends(get_account_db),
    ) -> SavedSearchOut:
        """Save a new message search configuration for quick access later."""
        existing_saved_searches = (
            cast(List[Dict[str, Any]], account.saved_searches) or []
        )
        if MessageSearchType(search.params.search_type).is_semantic():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Semantic search is not yet supported for saved searches.",
            )

        for existing_saved_search in existing_saved_searches:
            if existing_saved_search.get("params") == search.params:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A saved search with these parameters already exists.",
                )

        # Serialize to a dict compatible with storing in the DB
        new_saved_search = SavedSearch(
            **search.model_dump(mode="json", exclude_none=True)
        )
        new_saved_search_dict = new_saved_search.model_dump(
            mode="json", exclude_none=True
        )
        new_saved_search_dict["last_visited"] = (
            new_saved_search.last_visited.isoformat()
        )

        # Append to saved searches
        updated_saved_searches = existing_saved_searches + [new_saved_search_dict]

        await database.update(account, {"saved_searches": updated_saved_searches})
        return SavedSearchOut(**new_saved_search_dict)

    @router.delete(
        "/saved-searches/{id}",
        description="Delete a client",
        tags=["saved_searches"],
    )
    async def delete_saved_search(
        id: str,
        account: Account = Depends(current_active_verified_user),
        database: SQLAlchemyUserDatabase = Depends(get_account_db),
    ) -> JSONResponse:
        """Remove a saved search from the user's account."""
        saved_searches = []
        existing_searches = cast(List[Dict[str, Any]], account.saved_searches) or []

        for saved_search in existing_searches:
            if not saved_search["id"] == id:
                saved_searches.append(saved_search)

        if len(saved_searches) == len(existing_searches):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Saved search with ID {id} not found",
            )
        else:
            await database.update(
                account,
                update_dict={"saved_searches": saved_searches},
            )

            return JSONResponse(
                content=f"Saved search with id {id} deleted.",
                status_code=status.HTTP_204_NO_CONTENT,
            )

    @router.get(
        "/saved-searches/count-unread-messages",
        response_description="Count all unread messages of all saved searches",
        tags=["saved_searches"],
        response_model=dict[str, MessagesCount],
    )
    async def count_unread_messages(
        account: Account = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
    ) -> dict[str, MessagesCount]:
        """Count total and unread messages for each saved search since last visit."""
        existing_searches = cast(List[Dict[str, Any]], account.saved_searches) or []

        messages_count = {}

        for saved_search in existing_searches:
            saved_params = saved_search["params"]
            saved_search_query = saved_params.pop("search_query", None)

            # Drop sort_by and order from saved_params since they are not needed for counting
            saved_params.pop("sort_by", None)
            saved_params.pop("order", None)

            saved_search_type = saved_params.pop("search_type", None)

            message_search_query = parse_message_search_query_manual(
                search_query=saved_search_query,
                search_type=MessageSearchType(saved_search_type),
            )

            message_filter = parse_message_filter_manual(**saved_params)

            try:
                count_total = await database.messages.count(
                    search_query=message_search_query, filter=message_filter
                )
            except NotFoundError:
                count_total = 0
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"An error occurred while counting messages: {e}",
                )

            if saved_search["last_visited"]:
                last_visited = isoparse(saved_search["last_visited"])
                date_from = (
                    isoparse(saved_params["date_from"])
                    if saved_params.get("date_from")
                    else None
                )

                # In case the saved search contains date_from, we must not overwrite it with
                # last_visited since date_from could be more recent than last_visited and would
                # result in a false count of unread messages.
                if not date_from or (last_visited > date_from):
                    saved_params["date_from"] = saved_search["last_visited"]

            message_filter_unread = parse_message_filter_manual(**saved_params)

            count_unread = await database.messages.count(
                search_query=message_search_query, filter=message_filter_unread
            )

            messages_count[saved_search["id"]] = MessagesCount(
                count_total=count_total, count_unread=count_unread
            )

        return messages_count

    return router
