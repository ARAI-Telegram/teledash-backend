from typing import Optional

from pydantic import BaseModel
from pyrogram import types as pyrogram_types


class ChatRef(BaseModel):
    id: int
    title: Optional[str] = None
    username: Optional[str] = None

    @classmethod
    def from_pyrogram_chat(cls, tg_chat: pyrogram_types.Chat) -> "ChatRef":
        if tg_chat.id is None:
            raise ValueError("Pyrogram chat has no ID")
        return cls(id=tg_chat.id, title=tg_chat.title, username=tg_chat.username)


class UserRef(BaseModel):
    id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    @classmethod
    def from_pyrogram_user(cls, tg_user: pyrogram_types.User) -> "UserRef":
        return cls(
            id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
        )


class MessageRef(BaseModel):
    id: str
    text: Optional[str] = None
    caption: Optional[str] = None
    has_attachment: Optional[bool] = None
    user: Optional[UserRef] = None

    @classmethod
    def from_pyrogram_message(
        cls,
        tg_message: pyrogram_types.Message,
        tg_chat: Optional[pyrogram_types.Chat] = None,
    ) -> "MessageRef":
        # defer import to prevent circular dependency errors
        from .message import Message
        from .message.attachment import MessageAttachment

        chat = tg_message.chat if tg_message.chat else tg_chat

        if not chat or chat.id is None:
            raise ValueError("Could not parse MessageRef because of missing chat info")

        return cls(
            id=Message.create_id(tg_message.id, chat.id),
            text=tg_message.text,  # TODO: maybe truncate the text
            caption=tg_message.caption,
            has_attachment=(
                True if MessageAttachment.from_pyrogram_message(tg_message) else None
            ),
            user=(
                UserRef.from_pyrogram_user(tg_message.from_user)
                if tg_message.from_user
                else None
            ),
        )
