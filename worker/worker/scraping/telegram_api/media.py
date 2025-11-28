"""Telegram media download operations."""

from typing import Optional, Union, cast

import pyrogram.types as pyrogram_types
from celery.utils.log import get_task_logger
from pyrogram.client import Client as TelegramClient

from common.utils import run_pyrogram_method_with_retry_async

logger = get_task_logger(__name__)


async def download_file_from_telegram(
    tg_message_or_file_id: Union[pyrogram_types.Message, str],
    tmp_dir: str,
    tg_client: TelegramClient,
) -> Optional[str]:
    """Download a file from Telegram API.

    Args:
        tg_message_or_file_id: Telegram message or file ID to download.
        tmp_dir: Temporary directory path for download.
        tg_client: Telegram client instance.

    Returns:
        File path string if successful, None if failed.
    """

    def show_progress(current: int, total: int) -> None:
        """Log download progress.

        Args:
            current: Current bytes downloaded.
            total: Total bytes to download.
        """
        if total > 0:
            logger.debug(f"{current * 100 / total:.1f}%")

    try:
        return cast(
            Union[str, None],
            await run_pyrogram_method_with_retry_async(
                3,
                tg_client.download_media,
                tg_message_or_file_id,
                tmp_dir,
                progress=show_progress,
            ),
        )
    except Exception:
        logger.error(
            "Could not download media from Telegram API",
            exc_info=True,
        )
        return None
