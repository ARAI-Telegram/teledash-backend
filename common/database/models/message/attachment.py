from enum import Enum
from typing import List, Optional, cast

from pydantic import BaseModel, ConfigDict
from pyrogram import enums as pyrogram_enums
from pyrogram import types as pyrogram_types

from common.settings import settings
from common.utils import serialize_pyrogram_type


class MessageAttachmentStorageRef(BaseModel):
    bucket: str  # audios
    object: str  # asdoi32j4knmljasdasd.mp3


class TranscriptionStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class MessageAttachment(BaseModel):
    type: pyrogram_enums.MessageMediaType
    group_id: Optional[int] = None  # media group id
    # TODO: pyrogram types: Audio, Document, Photo, Sticker, Animation, Game, Video, Voice, VideoNote, Contact, Location, Venue, WebPage, Poll, Dice # noqa: E501
    raw: Optional[dict] = None
    transcription: Optional[str] = None
    transcription_language: Optional[str] = None
    transcription_language_probability: Optional[float] = None
    transcription_status: Optional[TranscriptionStatus] = None
    storage_refs: Optional[List[MessageAttachmentStorageRef]] = None
    model_config = ConfigDict(use_enum_values=True)

    @classmethod
    def from_pyrogram_message(
        cls, message: pyrogram_types.Message
    ) -> Optional["MessageAttachment"]:
        """
        Parse Message attachment.
        A message object from Pyrogram (or Telegram API?) can only have one attachment.
        Other attachments belonging to the same message are part of other message
        objects and grouped by "media_group_id".
        """

        media_attr = message.media
        types_to_save = [type_.lower() for type_ in settings.save_attachment_types]

        if not media_attr:
            return None

        media_type = media_attr.name.lower()

        return cls(
            type=media_attr,
            group_id=message.media_group_id if message.media_group_id else None,
            # Pyrograms Message has a 'media' attribute denoting the type of media and an attribute of the same name as the type that contains the media,
            # retreived with getattr().
            raw=(
                cast(dict, serialize_pyrogram_type(getattr(message, media_type)))
                if media_type in types_to_save
                else None
            ),
        )
