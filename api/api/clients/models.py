from enum import Enum
from typing import Optional

from pydantic import BaseModel
from pyrogram import types as pyrogram_types

from common.database.models.client import Client


class SentCodeType(str, Enum):
    """Copy of Pyrograms sent code type enumeration used in :obj:`~pyrogram.types.SentCode`."""

    APP = "APP"
    CALL = "CALL"
    FLASH_CALL = "FLASH_CALL"
    MISSED_CALL = "MISSED_CALL"
    SMS = "SMS"
    FRAGMENT_SMS = "FRAGMENT_SMS"
    EMAIL_CODE = "EMAIL_CODE"


class NextCodeType(str, Enum):
    """Copy of Pyrograms next code type enumeration used in :obj:`~pyrogram.types.SentCode`."""

    CALL = "CALL"
    FLASH_CALL = "FLASH_CALL"
    MISSED_CALL = "MISSED_CALL"
    SMS = "SMS"
    FRAGMENT_SMS = "FRAGMENT_SMS"


class SentCode(BaseModel):
    type: SentCodeType
    phone_code_hash: str
    next_type: Optional[NextCodeType] = None
    timeout: Optional[int] = None

    @classmethod
    def from_pyrogram_sent_code(cls, sent_code: pyrogram_types.SentCode) -> "SentCode":
        return cls(
            type=SentCodeType[
                sent_code.type.name
            ],  # Takes the name of Pyrogram's Enum as a string and gets our according Enum.
            phone_code_hash=sent_code.phone_code_hash,
            next_type=NextCodeType[sent_code.next_type.name]
            if sent_code.next_type
            else None,
            timeout=sent_code.timeout,
        )


class ClientCreate(Client):
    id: str  # type: ignore -> For FastAPI to recognize id as mandatory despite default value
    auth: SentCode


class ClientUpdate(BaseModel):
    title: Optional[str] = None
    is_active: Optional[bool] = None


class AddChatRequest(BaseModel):
    chat_id: int


class ClientVerifyPhoneCode(BaseModel):
    phone_code_hash: str
    phone_code: str


class ClientVerifyPassword(BaseModel):
    password: str
