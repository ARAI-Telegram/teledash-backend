from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from common.database.models.refs import ChatRef
from common.utils import naive_utcnow


class ClientIn(BaseModel):
    """
    The client model with Telegram auth infos and only those fields that can be
    modified by a client consuming the API (used in REST-API for
    POST/PUT/PATCH endpoints).
    """

    title: str
    phone_number: str
    api_id: int
    api_hash: str


class Client(ClientIn):
    """
    The complete client model with Telegram auth infos as it is stored in the
    database (used in REST-API and by the scraper).
    """

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        validation_alias="_id",
        serialization_alias="_id",
    )
    session_hash: Optional[str] = None
    user_id: Optional[int] = None  # Associated Telegram User
    # List of Telegram chats (channels, groups etc.)
    chats: Optional[List[ChatRef]] = None
    chats_to_join: Optional[List[str]] = None
    is_active: bool = False
    # Should be read-only after create
    created_at: datetime = Field(default_factory=naive_utcnow)
    updated_at: datetime = Field(default_factory=naive_utcnow)

    model_config = ConfigDict(validate_by_name=True)


class ClientOut(Client):
    """
    The complete client model as it is returned by the REST-API.
    """

    # TODO: Make phone number and api credentials optional?
    id: str  # type: ignore -> For FastAPI to recognize id as mandatory despite default value
