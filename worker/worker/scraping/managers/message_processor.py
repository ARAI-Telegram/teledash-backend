"""
Shared message processing logic for both history and live scraping.

This module extracts common functionality to eliminate duplication between
scrape_chats_history.py and scrape_chats_live.py, ensuring consistency
and simplifying maintenance.
"""

from datetime import datetime
from typing import List, Optional

from celery.utils.log import get_task_logger
from pydantic import ValidationError

from common.database.models.message import Message
from common.database.models.message.attachment import MessageAttachmentStorageRef
from common.database.models.message.scraping_mode import ScrapingMode
from common.database.models.user import User
from common.settings import settings
from worker.utils.helpers import bucket_name_from_attachment_type

logger = get_task_logger(__name__)


def parse_and_validate_message(
    tg_message,
    client_id: str,
) -> Optional[tuple[List[User], Message]]:
    """Parse and validate a Telegram message into domain objects.

    Args:
        tg_message: Pyrogram message object.
        client_id: Client ID for the scraping operation.

    Returns:
        Tuple of (users_list, parsed_message) or None if validation fails.
    """
    try:
        new_users, parsed_message = Message.from_pyrogram_message(tg_message, client_id)
        return new_users, parsed_message
    except (ValidationError, ValueError):
        logger.error(f'Error validating message "{tg_message.id}"', exc_info=True)
        return None


def set_message_metadata(
    message: Message,
    chat_language: Optional[str],
    scraping_mode: ScrapingMode,
) -> None:
    """Set language and scraping mode metadata on a message.

    Args:
        message: Message to update.
        chat_language: Language of the chat (can be None).
        scraping_mode: Whether this is HISTORY or LIVE scraping.
    """
    message.language = chat_language
    message.scraping_mode = scraping_mode


def add_storage_refs_to_message(
    message: Message,
    downloaded_attachment: dict,
) -> None:
    """Add storage references to message for already-existing attachment.

    Args:
        message: Message to add storage refs to.
        downloaded_attachment: Attachment info with already_exists=True.
    """
    if message.attachment is None:
        logger.warning(
            f"Cannot add storage refs to message {message.id}: attachment is None"
        )
        return

    bucket_name = bucket_name_from_attachment_type(downloaded_attachment["type"])
    object_name = downloaded_attachment["file_name"]

    storage_refs = [MessageAttachmentStorageRef(bucket=bucket_name, object=object_name)]

    if "thumbnail" in downloaded_attachment:
        thumbnail_storage_ref = MessageAttachmentStorageRef(
            bucket="thumbnails",
            object=downloaded_attachment["thumbnail"],
        )
        storage_refs.append(thumbnail_storage_ref)

    message.attachment.storage_refs = storage_refs
    logger.info(
        f"Added existing storage refs to message {message.id}: {bucket_name}/{object_name}"
    )


def valid_message_attachment(message: Message, max_date: datetime) -> bool:
    """Check if message attachment should be downloaded based on settings.

    Args:
        message: Message to check.
        max_date: Maximum date for downloading attachments.

    Returns:
        True if attachment should be downloaded, False otherwise.
    """
    return (
        message.date is not None
        and message.date >= max_date
        and message.attachment is not None
        and message.attachment.type in settings.save_attachment_types
        and message.attachment.type != "web_page"
    )
