from enum import Enum
from typing import List, Optional

from pydantic import BaseModel

from api.database.database import StatsEntry


class ChatSearchField(str, Enum):
    DESCRIPTION = "description"
    TITLE = "title"


class ChatStatsFields(str, Enum):
    TAGS = "tags"


class ChatStats(BaseModel):
    tags: Optional[List[StatsEntry]] = None


class ChatDeletionStats(BaseModel):
    """Statistics from chat deletion operation."""

    deleted_chats: int = 0
    deleted_message_indices: int = 0
    deleted_metrics: int = 0
    deleted_vectorized_indices: int = 0
    deleted_storage_objects: int = 0
    errors: List[str] = []


class DeleteChatsRequest(BaseModel):
    """Request body for deleting multiple chats."""

    chat_ids: List[int]
    delete_attachments: bool = False
