"""Attachment download orchestration and file management."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Union

import pyrogram.types as pyrogram_types
from celery.utils.log import get_task_logger
from pyrogram.client import Client as TelegramClient
from worker.scraping.telegram_api.media import download_file_from_telegram
from worker.utils.containers import StorageFileCache
from worker.utils.helpers import bucket_name_from_attachment_type

from common.database.models.message import Message
from common.settings import settings
from common.utils import naive_utcnow

logger = get_task_logger(__name__)
TMP_PATH = Path().cwd().joinpath("tmp")


def attachment_download_enabled() -> bool:
    """Determine if attachments should be downloaded based on settings.

    Returns:
        True if attachments should be downloaded, False otherwise.
    """
    return settings.save_attachments and bool(settings.save_attachment_types)


def get_attachment_max_date() -> datetime:
    """Get the maximum date for downloading attachments based on settings.

    Returns:
        Oldest message date to keep attachments for.
    """
    return (
        naive_utcnow() - timedelta(days=settings.keep_attachment_files_days)
        if settings.keep_attachment_files_days > 0
        else datetime.min
    )


async def download_single_attachment_from_telegram(
    session_dir: Path,
    tg_client: TelegramClient,
    parsed_message: Message,
    tg_message_or_file_id: Union[pyrogram_types.Message, str],
    file_cache: Optional[StorageFileCache] = None,
) -> Optional[dict]:
    """Download attachment from Telegram and save to downloads directory.

    In history scraper: checks file_cache first to avoid re-downloading existing files.
    In live scraper: downloads directly without cache (file_cache is None).

    Files are named by file_unique_id and organized into subdirectories by type.
    Downloads thumbnail for videos/photos (skips stickers and animations).

    Args:
        session_dir: Directory for temporary file storage.
        tg_client: Telegram client for downloading media.
        parsed_message: Parsed message with attachment metadata.
        tg_message_or_file_id: Pyrogram Message or file_id string.
        file_cache: Optional file cache used in history scraper to track downloaded files
            and get filenames with extensions from storage.

    Returns:
        Optional[dict]: Dictionary with file metadata if successful, None otherwise:
            - id (int): Message ID.
            - file_name (str): Downloaded filename with extension.
            - type (str): Attachment type (photo, video, document, etc.).
            - already_exists (bool, optional): True when file found in cache, absent otherwise.
            - thumbnail (str, optional): Thumbnail filename if downloaded.
    """
    session_dir.mkdir(parents=True, exist_ok=True)

    attachment = parsed_message.model_dump().get("attachment")
    if not attachment:
        logger.error("No attachment found in message")
        return None

    file_unique_id = attachment["raw"]["file_unique_id"]
    attachment_type = attachment["type"]

    # Check if already exists in storage
    cached_result = await _check_cached_attachment(
        file_cache, attachment_type, file_unique_id, attachment, parsed_message
    )
    if cached_result:
        return cached_result

    # Download new file
    return await _download_new_attachment(
        session_dir=session_dir,
        tg_client=tg_client,
        parsed_message=parsed_message,
        tg_message_or_file_id=tg_message_or_file_id,
        attachment=attachment,
        file_cache=file_cache,
    )


async def _check_cached_attachment(
    file_cache: Optional[StorageFileCache],
    attachment_type: str,
    file_unique_id: str,
    attachment: dict,
    parsed_message: Message,
) -> Optional[dict]:
    """Check if attachment exists in cache/storage to avoid re-downloading.

    Returns cached metadata if file exists, including thumbnail filename if available.
    """
    if not file_cache or not await file_cache.file_exists(
        attachment_type, file_unique_id
    ):
        return None

    logger.info(f"File {file_unique_id} already exists in storage, skipping download")

    full_filename = file_cache.get_filename(attachment_type, file_unique_id)
    result = {
        "id": parsed_message.id,
        "file_name": full_filename,
        "type": attachment_type,
        "already_exists": True,
    }

    # Check if thumbnail also cached
    thumbnail_filename = await _check_cached_thumbnail(file_cache, attachment)
    if thumbnail_filename:
        result["thumbnail"] = thumbnail_filename

    return result


async def _check_cached_thumbnail(
    file_cache: StorageFileCache,
    attachment: dict,
) -> Optional[str]:
    """Check if thumbnail exists in cache. Skips stickers and animations."""
    attachment_type = attachment["type"]
    if attachment_type in ["sticker", "animation"]:
        return None

    thumbs = attachment["raw"].get("thumbs")
    if not thumbs:
        return None

    thumb_unique_id = thumbs[0]["file_unique_id"]
    if await file_cache.file_exists("thumbnail", thumb_unique_id):
        return file_cache.get_filename("thumbnail", thumb_unique_id)

    return None


async def _download_new_attachment(
    session_dir: Path,
    tg_client: TelegramClient,
    parsed_message: Message,
    tg_message_or_file_id: Union[pyrogram_types.Message, str],
    attachment: dict,
    file_cache: Optional[StorageFileCache],
) -> Optional[dict]:
    """Download new attachment from Telegram and move to downloads directory.

    Downloads file using file_unique_id for naming, moves to appropriate downloads
    subdirectory by type, updates cache, and downloads thumbnail if available.
    Returns metadata dict or None on failure.
    """
    attachment_type = attachment["type"]
    file_unique_id = attachment["raw"]["file_unique_id"]
    session_dir_with_slash = session_dir.as_posix() + "/"

    logger.info(f"Start downloading {attachment_type.upper()}")

    # Download main file to session directory
    file_path = await download_file_from_telegram(
        tg_message_or_file_id=tg_message_or_file_id,
        tmp_dir=session_dir_with_slash,
        tg_client=tg_client,
    )
    if not file_path:
        logger.error("Failed to download file")
        return None

    # Rename using file_unique_id (persistent ID) and move to organized downloads directory
    path_new = await move_to_downloads_dir(
        attachment_type=attachment_type,
        file_name=file_unique_id,
        file_path_source=file_path,
    )
    if not path_new:
        logger.error("Failed to move file to downloads directory")
        return None

    # Add to cache
    if file_cache:
        file_cache.add_file(attachment_type, file_unique_id, path_new.name)

    logger.info(f"Saved {attachment_type.upper()} to '{path_new}'")

    result = {
        "id": parsed_message.id,
        "file_name": path_new.name,
        "type": attachment_type,
    }

    # Download thumbnail if applicable
    thumbnail_filename = await _download_thumbnail(
        session_dir_with_slash, tg_client, attachment, file_cache
    )
    if thumbnail_filename:
        result["thumbnail"] = thumbnail_filename

    return result


async def _download_thumbnail(
    session_dir: str,
    tg_client: TelegramClient,
    attachment: dict,
    file_cache: Optional[StorageFileCache],
) -> Optional[str]:
    """Download thumbnail for attachment if available.

    Downloads smallest thumbnail using thumb_unique_id for naming. Skips stickers
    and animations. Returns thumbnail filename or None.
    """
    attachment_type = attachment["type"]
    if attachment_type in ["sticker", "animation"]:
        return None

    thumbs = attachment["raw"].get("thumbs")
    if not thumbs:
        return None

    thumb = thumbs[0]
    thumb_unique_id = thumb["file_unique_id"]

    logger.info("Downloading THUMBNAIL")
    thumb_file_path = await download_file_from_telegram(
        thumb["file_id"], session_dir, tg_client
    )
    if not thumb_file_path:
        return None

    thumb_new_path = await move_to_downloads_dir(
        "thumbnail", thumb_unique_id, thumb_file_path
    )
    if not thumb_new_path:
        return None

    if file_cache:
        file_cache.add_file("thumbnail", thumb_unique_id, thumb_new_path.name)

    logger.info(f"Saved THUMBNAIL to '{thumb_new_path}'")
    return thumb_new_path.name


async def move_to_downloads_dir(
    attachment_type: str,
    file_name: str,
    file_path_source: str,
) -> Path:
    download_dir = TMP_PATH.joinpath(
        "downloads", bucket_name_from_attachment_type(attachment_type)
    )
    download_dir.mkdir(parents=True, exist_ok=True)
    download_dir_with_slash = download_dir.as_posix() + "/"

    return Path(
        file_path_source
    ).rename(  # overwrites original file with same name in downloads folder
        download_dir_with_slash + file_name + Path(file_path_source).suffix
    )
