from datetime import datetime
from typing import Optional

from pydantic import BaseModel
from pyrogram import types as pyrogram_types

from common.database.models.refs import ChatRef, UserRef


class MessageForward(BaseModel):
    from_user: Optional[UserRef] = None  # Called 'sender_user' in Telegram API
    sender_name: Optional[str] = None  # Called 'sender_user_name' in Telegram API
    from_chat: Optional[ChatRef] = None  # Called 'sender_chat' in Telegram API
    from_message_id: Optional[int] = None
    signature: Optional[str] = None
    date: Optional[datetime] = None

    @classmethod
    def from_pyrogram_message(cls, message: pyrogram_types.Message) -> "MessageForward":
        origin = message.forward_origin  # forward_origin is an instance of MessageOrigin which has multiple subclasses

        if origin is None:
            return cls()  # no forwarding info

        from_user = None
        if isinstance(origin, pyrogram_types.MessageOriginUser):
            from_user = (
                UserRef.from_pyrogram_user(origin.sender_user)
                if origin.sender_user
                else None
            )

        from_chat = None
        if isinstance(origin, pyrogram_types.MessageOriginChat):
            from_chat = (
                ChatRef.from_pyrogram_chat(origin.sender_chat)
                if origin.sender_chat
                else None
            )

        if isinstance(origin, pyrogram_types.MessageOriginChannel):
            from_chat = ChatRef.from_pyrogram_chat(origin.chat) if origin.chat else None

        return cls(
            from_user=from_user,
            from_chat=from_chat,
            sender_name=getattr(origin, "sender_user_name", None),
            from_message_id=getattr(origin, "message_id", None),
            signature=getattr(origin, "author_signature", None),
            date=origin.date,
        )
