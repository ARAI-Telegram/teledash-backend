from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel

from common.database.models.chat import Chat
from common.database.models.message import Message
from common.utils import naive_utcnow


class MetricType(str, Enum):
    chat_members_count = "chat_members_count"
    message_posted = "message_posted"


class MetricMeta(BaseModel):
    """
    The model for meta data for metrics.
    """

    user_id: Optional[int] = None
    chat_id: Optional[int] = None
    message_id: Optional[int] = None
    type: MetricType


class Metric(BaseModel):
    """
    The complete model for storing and returning metrics.
    """

    metadata: MetricMeta
    ts: datetime
    value: int

    @classmethod
    def from_new_message_posted(
        cls,
        message: Message,
    ) -> "Metric":
        if message.date is None:
            raise ValueError("Could not create metric from message (missing date)")

        # check if message has from_user.id (e.g. messages in channels don't have it)
        from_user = getattr(message, "from_user", None)
        from_user_id = getattr(from_user, "id", None)

        return cls(
            metadata=MetricMeta(
                user_id=from_user_id,
                chat_id=message.chat.id,
                message_id=message.id_in_chat,
                type=MetricType("message_posted"),
                # TODO: Save MessageAttachmentType
            ),
            ts=message.date,
            value=1,
        )

    @classmethod
    def from_chat(cls, chat: Chat) -> "Metric":
        if chat.members_count is None:
            raise ValueError(
                "Could not create metric from chat (missing members_count)"
            )

        return cls(
            metadata=MetricMeta(
                user_id=None,
                message_id=None,
                chat_id=chat.id,
                type=MetricType("chat_members_count"),
            ),
            ts=naive_utcnow(),
            value=chat.members_count,
        )
