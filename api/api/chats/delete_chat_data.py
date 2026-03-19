"""
Service functions for deleting a chat and its related data.
"""

import logging
from typing import Optional

from elasticsearch.dsl import Q

from api.database.database import Database
from api.database.utils import collect_storage_refs
from common.storage import Storage

logger = logging.getLogger(__name__)


async def delete_chat_data(
    database: Database,
    chat_id: int,
    storage: Optional[Storage] = None,
) -> tuple[int, list[str]]:
    """
    Delete a chat and all its related data.

    Order:
    1. Collect storage references from messages (before deletion, only if attachments requested)
    2. Delete chat record
    3. Delete message index
    4. Delete metrics
    5. Delete vectorized index
    6. Delete orphaned storage objects (only if storage provided)

    Args:
        database: Database instance
        chat_id: Chat ID to delete
        storage: If provided, also delete attachment files from storage

    Returns:
        Tuple of (deleted_storage_objects, errors)
    """
    errors: list[str] = []

    # 1. Collect storage refs BEFORE deleting messages
    storage_refs: set[tuple[str, str]] = set()
    if storage:
        storage_refs = await collect_storage_refs(
            database.es_client,
            f"messages_{chat_id}",
            {"exists": {"field": "attachment.storage_refs"}},
        )

    # 2. Delete chat record
    try:
        await database.chats.delete_by_query(query=Q("ids", values=[chat_id]))
        logger.info(f"Deleted chat record {chat_id}")
    except Exception as e:
        logger.error(f"Failed to delete chat record {chat_id}: {e}", exc_info=True)
        errors.append("Failed to delete chat record")

    # 3. Delete message index
    try:
        await database.es_client.indices.delete(
            index=f"messages_{chat_id}", ignore_unavailable=True
        )
    except Exception as e:
        logger.error(
            f"Failed to delete message index for chat {chat_id}: {e}", exc_info=True
        )
        errors.append("Failed to delete message index")

    # 4. Delete metrics
    try:
        await database.metrics.delete_by_query(
            query=Q("terms", **{"metadata.chat_id": [chat_id]})
        )
    except Exception as e:
        logger.error(f"Error deleting metrics for chat {chat_id}: {e}", exc_info=True)
        errors.append("Failed to delete metrics")

    # 5. Delete vectorized index
    try:
        await database.es_client.indices.delete(
            index=f"vectorized_messages_{chat_id}", ignore_unavailable=True
        )
    except Exception as e:
        logger.error(
            f"Failed to delete vectorized index for chat {chat_id}: {e}", exc_info=True
        )
        errors.append("Failed to delete vectorized index")

    # 6. Delete orphaned storage objects
    count_deleted_storage_objects = 0
    if storage and storage_refs:
        count, storage_error = await storage.cleanup_orphaned_objects(
            database, storage_refs
        )
        count_deleted_storage_objects = count
        if storage_error:
            errors.append(storage_error)

    return count_deleted_storage_objects, errors
