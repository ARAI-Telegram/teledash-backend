from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Union, cast

from pydantic import BaseModel, ConfigDict, Field
from pyrogram import types as pyrogram_types

from common.database.models.aggregations import AggregatedMetrics
from common.database.models.refs import ChatRef, UserRef
from common.database.models.verification_status import VerificationStatus
from common.utils import naive_utcnow, serialize_pyrogram_type


class UserStatus(str, Enum):
    """Copy of Pyrograms user status enumeration used in :obj:`~pyrogram.types.User`."""

    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    RECENTLY = "RECENTLY"
    LAST_WEEK = "LAST_WEEK"
    LAST_MONTH = "LAST_MONTH"
    LONG_AGO = "LONG_AGO"


class UserMetrics(BaseModel):
    activity_last_day: Optional[AggregatedMetrics] = None
    activity_total: Optional[AggregatedMetrics] = None


class UserIn(BaseModel):
    """
    The user model (a Telegram user) with only those fields that can be modified by
    a client consuming the API (used in REST-API for POST/PUT/PATCH endpoints).

    Adapted from Pyrograms user model:
    https://docs.pyrogram.org/api/types/User#pyrogram.types.User
    """


class User(UserIn):
    """
    The complete user model (a Telegram user) as it is stored in the database (used in
    REST-API and by the scraper).

    Adapted from Pyrograms user model:
    https://docs.pyrogram.org/api/types/User#pyrogram.types.User
    """

    id: int = Field(validation_alias="_id", serialization_alias="_id")
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_self: Optional[bool] = None
    is_contact: Optional[bool] = None
    is_mutual_contact: Optional[bool] = None
    is_deleted: Optional[bool] = None
    is_bot: Optional[bool] = None
    verification_status: Optional[VerificationStatus] = None
    is_restricted: Optional[bool] = None
    is_support: Optional[bool] = None
    metrics: Optional[UserMetrics] = None
    status: Optional[UserStatus] = None
    last_online_date: Optional[datetime] = None
    next_offline_date: Optional[datetime] = None
    language_code: Optional[str] = None
    dc_id: Optional[int] = None
    phone_number: Optional[str] = None
    photo: Optional[dict] = None  # TODO: pyrogram_types.ChatPhoto
    restrictions: Optional[List[dict]] = None  # TODO: pyrogram_types.Restriction
    updated_at: datetime = Field(default_factory=naive_utcnow)
    scraped_by: str
    in_chats: Optional[List[ChatRef]] = None

    model_config = ConfigDict(validate_by_name=True)

    def create_ref(self) -> UserRef:
        return UserRef(
            id=self.id,
            username=self.username,
            first_name=self.first_name,
            last_name=self.last_name,
        )

    @classmethod
    def from_pyrogram_user(cls, user: pyrogram_types.User, client_id: str) -> "User":
        datetime_now = naive_utcnow()

        return cls(
            id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            is_self=user.is_self,
            is_contact=user.is_contact,
            is_mutual_contact=user.is_mutual_contact,
            is_deleted=user.is_deleted,
            is_bot=user.is_bot,
            verification_status=VerificationStatus(
                is_verified=user.verification_status.is_verified,
                is_scam=user.verification_status.is_scam,
                is_fake=user.verification_status.is_fake,
            )
            if user.verification_status
            else None,
            is_restricted=user.is_restricted,
            is_support=user.is_support,
            status=UserStatus[user.status.name] if user.status else None,
            last_online_date=user.last_online_date,
            next_offline_date=user.next_offline_date,
            language_code=user.language_code,
            dc_id=user.dc_id,
            phone_number=user.phone_number,
            photo=cast(Optional[dict], serialize_pyrogram_type(user.photo)),
            restrictions=cast(
                Optional[list], serialize_pyrogram_type(user.restrictions)
            ),
            updated_at=datetime_now,
            scraped_by=client_id,
        )


class UserOut(User):
    """
    The complete user model as it is returned by the REST-API.
    All fields except "id" are optional since the API allows to include/exclude fields.
    """

    id: int  # type: ignore -> For FastAPI to recognize id as "id", not  "_id" (due to serialization_alias)
    scraped_by: Optional[str] = None
    metrics: Optional[UserMetrics] = None
    highlight: Optional[Dict[str, List[str]]] = None
    score: Optional[float] = None
