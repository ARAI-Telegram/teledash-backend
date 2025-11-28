from enum import Enum
from typing import Optional

from pydantic import BaseModel
from pyrogram import types as pyrogram_types

from common.database.models.refs import UserRef


# Reference: https://docs.pyrogram.org/api/enums/MessageEntityType
class MessageEntityType(str, Enum):
    MENTION = "mention"
    HASHTAG = "hashtag"
    CASHTAG = "cashtag"
    BOT_COMMAND = "bot_command"
    URL = "url"
    EMAIL = "email"
    PHONE_NUMBER = "phone_number"
    BOLD = "bold"
    ITALIC = "italic"
    UNDERLINE = "underline"
    STRIKETHROUGH = "strikethrough"
    SPOILER = "spoiler"
    CODE = "code"
    PRE = "pre"
    BLOCKQUOTE = "blockquote"
    TEXT_LINK = "text_link"
    TEXT_MENTION = "text_mention"
    BANK_CARD = "bank_card"
    CUSTOM_EMOJI = "custom_emoji"
    UNKNOWN = "unknown"


# Reference: https://docs.pyrogram.org/api/types/MessageEntity
class MessageEntity(BaseModel):
    type: MessageEntityType
    offset: int
    length: int
    url: Optional[str] = None
    user: Optional[UserRef] = None
    language: Optional[str] = None
    custom_emoji_id: Optional[int] = None

    @classmethod
    def from_pyrogram_message_entity(
        cls, message_entity: pyrogram_types.MessageEntity
    ) -> "MessageEntity":
        return cls(
            type=MessageEntityType(message_entity.type.name.lower()),
            offset=message_entity.offset,
            length=message_entity.length,
            url=message_entity.url,
            user=(
                UserRef.from_pyrogram_user(message_entity.user)
                if message_entity.user
                else None
            ),
            language=message_entity.language,
            custom_emoji_id=message_entity.custom_emoji_id,
        )
