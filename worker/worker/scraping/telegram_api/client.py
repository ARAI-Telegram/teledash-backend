"""Pure Telegram API wrappers for Pyrogram client operations.

This module contains thin wrappers around Pyrogram API calls for common operations
like fetching dialogs, getting chat info, and joining chats. These are low-level
API interactions without business logic.
"""

from typing import List, Optional, Union, cast

import pyrogram.types as pyrogram_types
from celery.utils.log import get_task_logger
from pyrogram.client import Client as TelegramClient
from pyrogram.errors import exceptions

from common.database.models.chat import ChatRef, ChatType
from common.database.models.user import User
from common.utils import run_pyrogram_method_with_retry_async

logger = get_task_logger(__name__)


async def fetch_valid_chat_references(
    tg_client: TelegramClient,
) -> List[dict]:
    """
    Fetch chat references asynchronously by iterating over the dialogs of a Telegram client.
    Returns only valid types of chats, i.e., groups, supergroups, and channels.

    Args:
        tg_client (TelegramClient): The Telegram client instance to use for fetching dialogs.

    Returns:
        List[dict]: A list of dictionaries containing chat references, with None values excluded
        and keys using aliases.
    """
    dialogs = await run_pyrogram_method_with_retry_async(
        retries=3, func=tg_client.get_dialogs
    )
    chat_refs = []
    if dialogs:
        async for dialog in dialogs:
            if dialog.chat.type and dialog.chat.type.name in ChatType.__members__:
                chat_ref = ChatRef.from_pyrogram_chat(dialog.chat).model_dump(
                    exclude_none=True,
                )
                chat_refs.append(chat_ref)
    return chat_refs


async def fetch_chat_from_telegram(
    tg_chat_id: int, tg_client: TelegramClient
) -> Optional[pyrogram_types.Chat]:
    """
    Asynchronously retrieves a chat from Telegram using the provided Telegram client.

    Args:
        tg_chat_id (int): The ID of the Telegram chat to retrieve information for.
        tg_client (TelegramClient): The Telegram client instance to use for making the API call.

    Returns:
        Optional[pyrogram_types.Chat]: The chat information if successfully retrieved, otherwise None.

    Raises:
        exceptions.PeerIdInvalid: If the provided chat ID is invalid.
        Exception: For any other exceptions that occur during the API call.
    """
    try:
        # get chat info from Telegram API
        logger.info(f"Getting chat info for chat {tg_chat_id}")
        tg_chat_raw = (
            await run_pyrogram_method_with_retry_async(
                3,
                tg_client.get_chat,
                tg_chat_id,
            ),
        )
        return cast(pyrogram_types.Chat, tg_chat_raw[0])

    except exceptions.PeerIdInvalid:
        logger.error(f'Error getting chat info for chat "{tg_chat_id}" (PeerIdInvalid)')

    except Exception:
        logger.error(f'Error getting chat info for chat "{tg_chat_id}"', exc_info=True)


async def join_chat(
    tg_client: TelegramClient, chat_id: Union[int, str]
) -> Optional[pyrogram_types.Chat]:
    """Join a group chat or channel with a specific client.

    Parameters:
        tg_client (TelegramClient): The Telegram client to use for joining.
        chat_id (``int`` | ``str``):
            Unique identifier for the target chat in form of a *t.me/joinchat/* link, a username of the target
            channel/supergroup (format: @username as per the documentation, but works without the "@" as well)
            or a chat id of a linked chat (channel or supergroup).

    Returns:
        Optional[pyrogram_types.Chat]: The joined chat information or None if failed.

    Raises:
        Exception: If joining the chat fails.
    """
    try:
        logger.info(f"Joining chat {chat_id}")
        tg_chat_raw = (
            await run_pyrogram_method_with_retry_async(
                3,
                tg_client.join_chat,
                chat_id,
            ),
        )
        return cast(pyrogram_types.Chat, tg_chat_raw[0])
    except Exception as e:
        logger.error(f'Error joining chat "{chat_id}": {str(e)}')
        raise


async def fetch_chat_members(
    tg_client: TelegramClient,
    chat_id: int,
    client_id: str,
) -> List[User]:
    """Fetch all members of a chat asynchronously.

    Args:
        tg_client (TelegramClient): The Telegram client to use for fetching members.
        chat_id (int): The ID of the chat to fetch members from.
        client_id (str): The client ID to associate with users (for tracking).

    Returns:
        List[User]: List of chat members.

    Raises:
        ChatAdminRequired: If user is not admin in the chat.
        ChannelPrivate: If channel is private or user is not a member.
        ChannelInvalid: If channel ID is invalid.
        Exception: For any other unexpected errors during fetching.

    Note:
        Currently returns a maximum of 10,000 members due to Telegram API limitations.
        Status of users (e.g., admin, member) is not included currently but can be added in the future.
    """

    chat_members: List[User] = []
    try:
        members = await run_pyrogram_method_with_retry_async(
            3,
            tg_client.get_chat_members,
            int(chat_id),
        )
        if members:
            async for member in members:
                user = User.from_pyrogram_user(member.user, client_id)
                chat_members.append(user)

    except exceptions.ChatAdminRequired:
        logger.warning(f"User is not admin in chat {chat_id}")

    except exceptions.ChannelPrivate:
        logger.warning(f"Channel {chat_id} is private or user not a member")

    except exceptions.ChannelInvalid:
        logger.error(f"Channel ID {chat_id} is invalid")

    except Exception as e:
        logger.error(f"Unexpected error while fetching chat members: {e}")
        raise

    return chat_members


async def fetch_chat_history(
    tg_client: TelegramClient,
    chat_id: int,
    reverse: bool = False,
    limit: Optional[int] = None,
    min_id: int = 0,
):
    """Fetch chat message history asynchronously.

    Args:
        tg_client (TelegramClient): The Telegram client to use for fetching history.
        chat_id (int): The ID of the chat to fetch history from.
        reverse (bool): If True, messages are returned in chronological order (oldest first).
                       If False, returns in reverse chronological order (newest first).
                       Defaults to False.
        limit (Optional[int]): Maximum number of messages to retrieve. None means no limit.
        min_id (int): Start fetching messages after this message ID (exclusive).
                     Defaults to 0 (fetch from beginning).

    Yields:
        pyrogram_types.Message: Message objects from the chat history.

    Raises:
        Exception: For any errors during fetching.

    Example:
        # Fetch newest 100 messages
        async for msg in fetch_chat_history(client, chat_id, limit=100):
            process(msg)

        # Fetch all messages starting from message ID 1000
        async for msg in fetch_chat_history(client, chat_id, reverse=True, min_id=1000):
            process(msg)
    """
    try:
        async for message in tg_client.get_chat_history(
            chat_id,
            reverse=reverse,
            limit=limit or 0,
            min_id=min_id,
        ):
            yield message
    except Exception as e:
        logger.error(f"Error fetching chat history for chat {chat_id}: {e}")
        raise
