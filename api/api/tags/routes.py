from typing import Optional, Tuple

from elasticsearch.dsl.query import Query as ESQuery
from fastapi import APIRouter, Depends

from api.accounts.auth import get_current_active_verified_user
from api.accounts.models import AccountRead
from api.database import get_database
from api.database.database import Database
from api.messages.validators import (
    parse_flexible_message_search_query,
    parse_message_filter,
)


def get_tags_router() -> APIRouter:
    """Create and configure the tags API router."""
    router = APIRouter()

    @router.get(
        "/tags",
        response_description="List all tags",
        tags=["tags"],
        response_model=list[str],
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def list_tags(
        filter: Tuple[Optional[ESQuery], dict] = Depends(parse_message_filter),
        search_query: Optional[ESQuery] = Depends(parse_flexible_message_search_query),
        account: AccountRead = Depends(get_current_active_verified_user()),
        database: Database = Depends(get_database),
    ) -> list[str]:
        """Retrieve all unique message tags with optional filtering."""
        es_filter, _ = filter
        # Get all unique tag values from messages
        tags = await database.messages.get_top_field_values(
            field="tags",
            search_query=search_query,
            filter=es_filter,
        )
        return [tag.value for tag in tags]

    return router
