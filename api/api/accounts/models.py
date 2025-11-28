import uuid
from datetime import datetime
from typing import Optional

from fastapi_users import schemas
from pydantic import Field

from common.utils import naive_utcnow


class AccountRead(schemas.BaseUser[uuid.UUID]):
    id: uuid.UUID  # openapi-typescript does not recognize the generic type, so we have to explicitly define it
    first_name: str
    last_name: str
    created_at: datetime = Field(default_factory=naive_utcnow)
    updated_at: Optional[datetime] = Field(default_factory=naive_utcnow)


class AccountCreate(schemas.BaseUserCreate):
    first_name: str
    last_name: str


class AccountUpdate(schemas.BaseUserUpdate):
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class AccountDB(AccountRead):
    pass
