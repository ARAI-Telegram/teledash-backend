import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from pyrogram import enums as pyrogram_enums

from api.messages.models import MessageSearchType
from api.messages.validators import MessageSortBy
from api.validators import OrderEnum
from common.utils import naive_utcnow


# Mirrors the query parameters accepted by GET /messages endpoint
# TODO: Find a way to reuse the query parameters from the messages endpoint
#       without duplicating the code.
class ListMessagesParams(BaseModel):
    saved_search_id: Optional[str] = None
    from_user_ids: Optional[list[int]] = None
    chat_ids: Optional[list[int]] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    is_empty: Optional[bool] = None
    attachment_type: Optional[pyrogram_enums.MessageMediaType] = None
    tags: Optional[list[str]] = None
    chat_tags: Optional[list[str]] = None
    search_query: Optional[str] = None
    sort_by: Optional[MessageSortBy] = None
    order: Optional[OrderEnum] = None
    include: Optional[list[str]] = None
    exclude: Optional[list[str]] = None
    search_type: MessageSearchType
    model_config = ConfigDict(use_enum_values=True)


class SavedSearchIn(BaseModel):
    name: str
    params: ListMessagesParams


class SavedSearch(SavedSearchIn):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    last_visited: datetime = Field(default_factory=naive_utcnow)


class SavedSearchOut(SavedSearch):
    id: str  # type: ignore -> For FastAPI to recognize id as mandatory despite default value


class MessagesCount(BaseModel):
    count_total: int
    count_unread: int
