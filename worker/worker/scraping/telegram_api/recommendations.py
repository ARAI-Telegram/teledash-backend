from typing import List, Optional, Union

from celery.utils.log import get_task_logger
from pyrogram.client import Client as TelegramClient
from pyrogram.errors import RPCError
from pyrogram.raw.functions.channels.get_channel_recommendations import (
    GetChannelRecommendations,
)

from common.database.models.refs import ChatRef
from common.utils import run_pyrogram_method_with_retry_async

logger = get_task_logger(__name__)


async def get_recommended_channels(
    tg_client: TelegramClient,
    chat_id: Optional[Union[int, str]] = None,
    retries: int = 3,
) -> List[dict]:
    """
    Retrieve recommended channels as a list of dictionaries.

    Args:
        tg_client: Telegram client instance.
        chat_id: Optional chat ID to get similar channels for. If not provided,
                general recommendations for the user are returned.
        retries: Number of retries for API calls (default: 3)

    Returns:
        List of dictionaries of ChatRef objects, representing recommended channels.
    """
    try:
        if chat_id:
            recommended_channels = await run_pyrogram_method_with_retry_async(
                retries, tg_client.get_similar_channels, int(chat_id)
            )
        else:  # Method from Telegram API. Not used so far. Needs to be tested with real recommendations.
            recommended_channels = await tg_client.invoke(GetChannelRecommendations())

        if not recommended_channels:
            return []

        if isinstance(recommended_channels, list):
            return [
                ChatRef.from_pyrogram_chat(chat).model_dump(exclude_none=True)
                for chat in recommended_channels
                if chat is not None
            ]
        else:
            logger.warning(f"Unexpected response type: {type(recommended_channels)}")
            return []

    except RPCError as e:
        logger.error(f"Telegram API error in fetching recommendations: {str(e)}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error in fetching recommendations: {str(e)}")
        return []
