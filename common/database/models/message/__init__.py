from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field
from pyrogram import types as pyrogram_types

from common.database.models.message.attachment import MessageAttachment
from common.database.models.message.entity import MessageEntity
from common.database.models.message.forward import MessageForward
from common.database.models.message.scraping_mode import ScrapingMode
from common.database.models.message.service_info import MessageServiceInfo
from common.database.models.refs import ChatRef, MessageRef, UserRef
from common.database.models.user import User
from common.utils import naive_utcnow


class MessageIn(BaseModel):
    """
    The message model with only those fields that can be modified by a client consuming
    the API (used in REST-API for POST/PUT/PATCH endpoints).

    Adapted from Pyrograms message model:
    https://docs.pyrogram.org/api/types/Message#pyrogram.types.Message
    """

    """
    partial index draft:
    {
        customFilter:
            {
                attachment: {$exists: true},
                'processed.attachment.transcription': {$exists: true},
                'processed.attachment.in_storage': {$exists: true},
                'processed.text.translation': {$exists: true},
                'processed.caption.translation': {$exists: true},
            }
        }
    }


    """

    language: Optional[str] = None
    tags: Optional[list[str]] = None

    model_config = ConfigDict(validate_by_name=True)


class Message(MessageIn):
    """
    The complete message model as it is stored in the database (used in REST-API
    and by the scraper).

    Adapted from Pyrograms message model:
    https://docs.pyrogram.org/api/types/Message#pyrogram.types.Message
    """

    id: str = Field(
        validation_alias="_id", serialization_alias="_id"
    )  # a string created from chat-id and message-id
    # incrementing number in chat (only unique in combination with chat-id)
    id_in_chat: int
    from_user: Optional[UserRef] = None
    chat: ChatRef
    sender_chat: Optional[ChatRef] = None
    date: Optional[datetime] = None
    forward: Optional[MessageForward] = None
    reply_to_message: Optional[MessageRef] = None
    mentioned: Optional[bool] = None
    is_empty: Optional[bool] = None
    attachment: Optional[MessageAttachment] = None
    edit_date: Optional[datetime] = None
    author_signature: Optional[str] = None
    text: Optional[str] = None
    entities: Optional[List[MessageEntity]] = None
    caption: Optional[str] = None
    caption_entities: Optional[List[MessageEntity]] = None
    views: Optional[int] = None
    is_outgoing: Optional[bool] = None
    service_info: Optional[MessageServiceInfo] = None
    updated_at: datetime = Field(default_factory=naive_utcnow)
    scraped_by: str
    deleted: Optional[datetime] = None
    scraping_mode: Optional[ScrapingMode] = None
    extracted_urls: Optional[List[Dict]] = None
    extracted_hashtags: Optional[List[str]] = None

    @staticmethod
    def create_id(id_in_chat: int, chat_id: int) -> str:
        return f"{chat_id}:{id_in_chat}"

    @classmethod
    def from_pyrogram_message(
        cls,
        tg_message: pyrogram_types.Message,
        client_id: str,
        tg_chat: Optional[pyrogram_types.Chat] = None,
    ) -> Tuple[List[User], "Message"]:
        datetime_now = naive_utcnow()
        chat = tg_message.chat if tg_message.chat else tg_chat

        if not chat or not chat.id:
            raise ValueError("Could not parse Message because of missing chat info")

        # parse user from message
        new_users: List[User] = []
        from_user: Optional[User] = (
            User.from_pyrogram_user(tg_message.from_user, client_id)
            if tg_message.from_user
            else None
        )

        # parse sender user
        if from_user:
            new_users.append(from_user)

        forward = (
            MessageForward.from_pyrogram_message(tg_message)
            if getattr(tg_message, "forward_origin", None) is not None
            else None
        )

        attachment = MessageAttachment.from_pyrogram_message(tg_message)

        service_info_users, service_info = MessageServiceInfo.from_pyrogram_message(
            tg_message, client_id
        )
        if service_info_users:
            new_users.extend(service_info_users)

        new_message = cls(
            id=cls.create_id(tg_message.id, chat.id),
            id_in_chat=tg_message.id,
            from_user=from_user.create_ref() if from_user else None,
            sender_chat=(
                ChatRef.from_pyrogram_chat(tg_message.sender_chat)
                if tg_message.sender_chat
                else None
            ),
            date=tg_message.date,
            chat=ChatRef.from_pyrogram_chat(chat),
            forward=forward,
            reply_to_message=(
                MessageRef.from_pyrogram_message(tg_message.reply_to_message, chat)
                if tg_message.reply_to_message
                else None
            ),
            mentioned=tg_message.mentioned,
            is_empty=tg_message.empty,
            attachment=attachment,
            edit_date=tg_message.edit_date,
            author_signature=tg_message.author_signature,
            text=tg_message.text,
            entities=(
                [
                    MessageEntity.from_pyrogram_message_entity(message_entity)
                    for message_entity in tg_message.entities
                ]
                if tg_message.entities
                else None
            ),
            caption=tg_message.caption,
            caption_entities=(
                [
                    MessageEntity.from_pyrogram_message_entity(message_entity)
                    for message_entity in tg_message.caption_entities
                ]
                if tg_message.caption_entities
                else None
            ),
            views=tg_message.views,
            is_outgoing=tg_message.outgoing,
            service_info=service_info,
            updated_at=datetime_now,
            scraped_by=client_id,
        )

        return new_users, new_message


class MessageOut(Message):
    """
    The complete message model as it is returned by the REST-API.
    All fields except "id" are optional since the API allows to include/exclude fields.
    """

    id: str  # type: ignore -> For FastAPI to recognize id as mandatory despite default value
    id_in_chat: Optional[int] = None
    chat: Optional[ChatRef] = None
    scraped_by: Optional[str] = None
    highlight: Optional[Dict[str, List[str]]] = None
    score: Optional[float] = None
    classification_score_pos: Optional[float] = None
    semantic_score: Optional[float] = None
