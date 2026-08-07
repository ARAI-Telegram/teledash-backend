"""
Service functions for leaving Telegram chats via Pyrogram.

This module provides functionality to:
- Find clients that are members of a specific chat
- Leave a chat using the client's Telegram session
"""

import logging
from typing import List

from api.chats.models import LeaveChatResult
from api.database.database import Database
from elasticsearch.dsl import Q
from pyrogram.client import Client as TelegramClient
from pyrogram.errors import (
    ChannelParicipantMissing,  # Note: typo in Pyrogram library
    ChannelPrivate,
    ChatForbidden,
    UserKicked,
    UserNotParticipant,
)

from common.database.models.client import ClientOut
from common.settings import settings

logger = logging.getLogger(__name__)


async def find_clients_for_chat(database: Database, chat_id: int) -> List[ClientOut]:
    """
    Find which clients have joined a specific chat by checking the 'chats' field on clients.
    Note:
        - Multiple clients could theoretically be members of the same chat.
        - Edge case: if a client joined a chat but the init scraper hasn't run yet,
        the chat won't appear in the client's 'chats' list and we won't be able to leave it.

    Args:
        database: Database instance
        chat_id: Chat ID to find clients for

    Returns:
        List of ClientOut documents that have this chat in their 'chats' list
    """
    clients_query = Q("terms", **{"chats.id": [chat_id]})
    clients: List[ClientOut] = [
        client async for client in database.clients.find(filter=clients_query)
    ]
    return clients


async def leave_chat_via_pyrogram(client: ClientOut, chat_id: int) -> LeaveChatResult:
    """
    Leave a single chat using the client's Pyrogram session.

    "Not a member" errors are treated as success — the goal (client not in chat) is achieved.

    Args:
        client: Client document with session_hash
        chat_id: Telegram chat ID to leave

    Returns:
        LeaveChatResult with success status and any message
    """
    if not client.session_hash:
        return LeaveChatResult(
            client_id=client.id,
            success=False,
            message="Client has no session_hash - not authenticated",
        )

    tg_client = TelegramClient(
        name=f"leave_chat_{client.id}",
        api_id=client.api_id,
        api_hash=client.api_hash,
        session_string=client.session_hash,
        no_updates=True,
        in_memory=True,
        test_mode=settings.telegram_test_mode,
    )

    try:
        await tg_client.connect()
        await tg_client.leave_chat(chat_id)

        logger.info(f"Client {client.id} successfully left chat {chat_id}")
        return LeaveChatResult(client_id=client.id, success=True)

    except (
        UserNotParticipant,
        UserKicked,
        ChannelPrivate,
        ChannelParicipantMissing,
        ChatForbidden,
    ) as e:
        # Client is already not a member — goal achieved
        logger.warning(
            f"Client {client.id} is not a member of chat {chat_id} (already left or never joined): {e}"
        )
        return LeaveChatResult(
            client_id=client.id,
            success=True,
            message=f"Already not a member: {e}",
        )

    except Exception as e:
        logger.error(
            f"Failed to leave chat {chat_id} with client {client.id}: {e}",
            exc_info=True,
        )
        return LeaveChatResult(
            client_id=client.id,
            success=False,
            message=str(e),
        )

    finally:
        if tg_client.is_connected:
            await tg_client.disconnect()


async def leave_chat(database: Database, chat_id: int) -> List[LeaveChatResult]:
    """
    Leave a single chat via Pyrogram for all clients that are members.

    Raises:
        Exception: If an active client fails to leave — deletion would be unsafe
                   since that client will keep scraping the chat.

    Note: If a client joined a chat but the init scraper task hasn't run yet,
    the chat won't appear in the client's 'chats' list. In this edge case,
    we cannot automatically leave the chat - you would need to manually
    trigger the scraper or leave via Telegram directly.

    Args:
        database: Database instance
        chat_id: Chat ID to leave

    Returns:
        List of LeaveChatResult for each client
    """
    clients = await find_clients_for_chat(database, chat_id)

    if not clients:
        logger.warning(f"No clients found for chat {chat_id}")
        return []

    leave_results: List[LeaveChatResult] = []

    for client in clients:
        result = await leave_chat_via_pyrogram(client, chat_id)

        if not result.success:
            if client.is_active:
                raise Exception(
                    f"Active client {client.id} failed to leave chat {chat_id}: {result.message}"
                )
            else:
                result.message = (
                    f"Client {client.id} failed to leave chat. It is currently inactive — "
                    f"if set to active again, it will re-scrape this chat."
                )

        leave_results.append(result)

    return leave_results
