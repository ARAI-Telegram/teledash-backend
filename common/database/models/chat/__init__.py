from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Union, cast

from pydantic import BaseModel, ConfigDict, Field
from pyrogram import types as pyrogram_types

from common.database.models.aggregations import AggregatedMetrics
from common.database.models.refs import ChatRef, MessageRef, UserRef
from common.database.models.verification_status import VerificationStatus
from common.utils import naive_utcnow, serialize_pyrogram_type

"""
Adapted from Pyrograms chat model:
https://docs.pyrogram.org/api/types/Chat#pyrogram.types.Chat
"""


class ClassificationAggregation(BaseModel):
    classified_success_count: Optional[int] = None
    classified_error_count: Optional[int] = None
    score_pos_avg: Optional[float] = None


class GlobalMetrics(BaseModel):
    users_count: Optional[int] = None
    chats_count: Optional[int] = None
    messages_count: Optional[int] = None
    photos_count: Optional[int] = None
    videos_count: Optional[int] = None
    voices_count: Optional[int] = None
    growth_total: Optional[AggregatedMetrics] = None
    activity_total: Optional[AggregatedMetrics] = None
    classification_total: Optional[ClassificationAggregation] = None


class ChatMetrics(BaseModel):
    activity_last_day: Optional[AggregatedMetrics] = None
    activity_total: Optional[AggregatedMetrics] = None
    growth_last_day: Optional[AggregatedMetrics] = None
    growth_total: Optional[AggregatedMetrics] = None


class ChatType(str, Enum):
    # we don't save "bot", "private", "forum" and "direct" chats
    GROUP = "GROUP"
    SUPERGROUP = "SUPERGROUP"
    CHANNEL = "CHANNEL"


class ChatIn(BaseModel):
    """
    The chat model with only those fields that can be modified by a client consuming
    the API (used in REST-API for POST/PUT/PATCH endpoints).
    """

    language: Optional[str] = None
    language_other: Optional[List[str]] = None
    tags: Optional[list[str]] = None


class Chat(ChatIn):
    """
    The complete chat model as it is stored in the database (used by the scraper).
    """

    id: int = Field(validation_alias="_id", serialization_alias="_id")
    type: ChatType  # group, supergroup or channel
    title: Optional[str] = None
    username: Optional[str] = None
    # TODO: is_active / exclude to manually disable scraping of specific chat
    verification_status: Optional[VerificationStatus] = None
    is_restricted: Optional[bool] = None
    photo: Optional[dict] = None  # TODO: pyrogram_types.ChatPhoto
    description: Optional[str] = None
    invite_link: Optional[str] = None
    pinned_message: Optional[MessageRef] = None
    members: Optional[List[UserRef]] = None
    members_count: Optional[int] = None
    metrics: Optional[ChatMetrics] = None
    linked_chat: Optional[ChatRef] = None
    restrictions: Optional[List[dict]] = None  # TODO: pyrogram_types.Restriction
    permissions: Optional[dict] = None  # TODO: pyrogram_types.Restriction
    added_at: datetime = Field(default_factory=naive_utcnow)
    updated_at: datetime = Field(
        default_factory=naive_utcnow
    )  # will later be updated, not like added_at
    history_updated_at: Optional[datetime] = None
    scraped_by: str
    similar_channels: Optional[List[ChatRef]] = None

    model_config = ConfigDict(use_enum_values=True, validate_by_name=True)

    def create_ref(self) -> ChatRef:
        return ChatRef(
            id=self.id,
            title=self.title,
            username=self.username,
        )

    @classmethod
    def from_pyrogram_chat(cls, tg_chat: pyrogram_types.Chat, client_id: str) -> "Chat":
        if tg_chat.id is None:
            raise ValueError("Pyrogram chat has no ID")
        if tg_chat.type is None:
            raise ValueError(f"Chat {tg_chat.id} has no type")

        datetime_now = naive_utcnow()

        return cls(
            id=tg_chat.id,
            type=ChatType[tg_chat.type.name],
            title=tg_chat.title,
            username=tg_chat.username,
            verification_status=VerificationStatus(
                is_verified=tg_chat.verification_status.is_verified,
                is_scam=tg_chat.verification_status.is_scam,
                is_fake=tg_chat.verification_status.is_fake,
            )
            if tg_chat.verification_status
            else None,
            is_restricted=tg_chat.is_restricted,
            photo=cast(Optional[dict], serialize_pyrogram_type(tg_chat.photo)),
            description=tg_chat.description,
            invite_link=tg_chat.invite_link,
            pinned_message=(
                MessageRef.from_pyrogram_message(tg_chat.pinned_message)
                if tg_chat.pinned_message
                else None
            ),
            members_count=tg_chat.members_count,
            linked_chat=(
                ChatRef.from_pyrogram_chat(tg_chat.linked_chat)
                if tg_chat.linked_chat
                else None
            ),
            restrictions=cast(
                Optional[list], serialize_pyrogram_type(tg_chat.restrictions)
            ),
            permissions=cast(
                Optional[dict], serialize_pyrogram_type(tg_chat.permissions)
            ),
            added_at=datetime_now,
            updated_at=datetime_now,
            scraped_by=client_id,
        )


class ChatOut(Chat):
    """
    The complete chat model as it is returned by the REST-API.
    All fields except "id" are optional since the API allows to include/exclude fields.
    """

    id: int  # type: ignore -> For FastAPI to recognize id as "id", not "_id"
    type: Optional[ChatType] = None
    classification_aggregated: Optional[ClassificationAggregation] = None
    scraped_by: Optional[str] = None
    updated_at: Optional[datetime] = None
    metrics: Optional[ChatMetrics] = None
    highlight: Optional[Dict[str, List[str]]] = None
    score: Optional[float] = None
