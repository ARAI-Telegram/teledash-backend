from enum import Enum
from typing import List, Optional

from api.database.database import StatsEntry
from pydantic import BaseModel


class ChatSearchField(str, Enum):
    DESCRIPTION = "description"
    TITLE = "title"


class ChatStatsFields(str, Enum):
    TAGS = "tags"


class ChatStats(BaseModel):
    tags: Optional[List[StatsEntry]] = None


class LeaveChatResult(BaseModel):
    """Result of leaving a chat for a single client."""

    client_id: str
    success: bool
    message: Optional[str] = None


class DeleteChatResponse(BaseModel):
    """Response for the delete chat endpoint."""

    leave_results: Optional[List[LeaveChatResult]] = None
    deleted_storage_objects: Optional[int] = None
    errors: Optional[List[str]] = None
