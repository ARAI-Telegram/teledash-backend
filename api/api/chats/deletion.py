"""
Service functions for deleting chats and their related data.

This module provides functionality to delete:
- Chat records
- Messages belonging to the chats
- Metrics related to the chats
- Vectorized message indices for semantic search
- Orphaned storage objects
"""

import logging
from typing import Optional

from elasticsearch.dsl import Q

from api.chats.models import ChatDeletionStats
from api.database.database import Database
from common.storage import Storage

logger = logging.getLogger(__name__)


async def _bulk_delete_indices(es_client, index_names: list[str]) -> Optional[str]:
    """
    Attempt to delete multiple indices in a single operation.

    Elasticsearch will delete all existing indices and ignore missing ones.
    If any actual error occurs (permissions, cluster issues), the whole operation fails.

    Args:
        es_client: Elasticsearch client
        index_names: List of index names to delete

    Returns:
        Error message if deletion failed, None if successful
    """
    try:
        await es_client.indices.delete(
            index=index_names,
            ignore_unavailable=True,  # Don't fail if index doesn't exist
            allow_no_indices=True,  # Don't fail if no indices match
        )
        return None
    except Exception as e:
        logger.error(f"Failed to delete indices {index_names}: {e}", exc_info=True)
        return "Failed to delete indices. See server logs for details."


async def delete_chats(database: Database, chat_ids: list[int]) -> int:
    """
    Delete chat records from the chats index.

    Args:
        database: Database instance
        chat_ids: List of chat IDs to delete

    Returns:
        Number of chats deleted

    Raises:
        Exception: If deletion fails
    """
    chats_query = Q("ids", values=chat_ids)
    deleted_count = await database.chats.delete_by_query(query=chats_query)
    logger.info(f"Deleted {deleted_count} chat records: {chat_ids}")
    return deleted_count


async def delete_message_indices(
    database: Database, chat_ids: list[int]
) -> tuple[int, Optional[str]]:
    """
    Delete message indices for specific chats (messages_{chat_id}).

    Args:
        database: Database instance
        chat_ids: List of chat IDs

    Returns:
        Tuple of (number of indices requested for deletion, error message if any)
        Note: The count represents indices we attempted to delete, not confirmed deletions,
        since Elasticsearch silently ignores non-existent indices.
    """
    message_indices = [f"messages_{chat_id}" for chat_id in chat_ids]

    error = await _bulk_delete_indices(database.es_client, message_indices)

    if error:
        logger.warning(f"Failed to delete message indices for chats {chat_ids}")
        return 0, error

    logger.info(
        f"Requested deletion of {len(message_indices)} message indices for chats: {chat_ids}"
    )
    return len(message_indices), None


async def collect_storage_refs_from_chats(
    database: Database, chat_ids: list[int]
) -> set[tuple[str, str]]:
    """
    Collect all storage references from messages in the specified chats.

    Uses scroll API to handle large result sets efficiently.

    Args:
        database: Database instance
        chat_ids: List of chat IDs

    Returns:
        Set of (bucket, object_name) tuples for all storage objects
    """
    storage_refs = set()

    for chat_id in chat_ids:
        index_name = f"messages_{chat_id}"

        try:
            # Check if index exists
            exists = await database.es_client.indices.exists(index=index_name)
            if not exists:
                logger.debug(f"Index {index_name} does not exist, skipping")
                continue

            # Use scroll API to get all messages with attachments
            search_body = {
                "query": {"exists": {"field": "attachment.storage_refs"}},
                "_source": ["attachment.storage_refs"],
                "size": 1000,
            }

            response = await database.es_client.search(
                index=index_name,
                body=search_body,
                scroll="1m",
            )

            scroll_id = response.get("_scroll_id")

            while True:
                hits = response.get("hits", {}).get("hits", [])
                if not hits:
                    break

                for hit in hits:
                    source = hit.get("_source", {})
                    attachment = source.get("attachment", {})
                    refs = attachment.get("storage_refs", [])

                    for ref in refs:
                        if "bucket" in ref and "object" in ref:
                            storage_refs.add((ref["bucket"], ref["object"]))

                try:
                    response = await database.es_client.scroll(
                        scroll_id=scroll_id, scroll="1m"
                    )
                except Exception as scroll_error:
                    logger.error(f"Scroll error: {scroll_error}", exc_info=True)
                    break

            # Clean up scroll
            if scroll_id:
                try:
                    await database.es_client.clear_scroll(scroll_id=scroll_id)
                except Exception:
                    # Ignore scroll cleanup errors - scroll will expire naturally
                    pass

        except Exception as e:
            logger.error(
                f"Error collecting storage refs from chat {chat_id}: {e}", exc_info=True
            )
            continue

    logger.info(f"Collected {len(storage_refs)} storage references from chats")
    return storage_refs


async def delete_chat_metrics(
    database: Database, chat_ids: list[int]
) -> tuple[int, Optional[str]]:
    """
    Delete all metrics associated with specific chats.

    Args:
        database: Database instance
        chat_ids: List of chat IDs

    Returns:
        Tuple of (number of metrics deleted, error message if any)
    """
    try:
        metrics_query = Q("terms", **{"metadata.chat_id": chat_ids})
        deleted_count = await database.metrics.delete_by_query(query=metrics_query)
        logger.info(f"Deleted {deleted_count} metrics for chats: {chat_ids}")
        return deleted_count, None
    except Exception as e:
        logger.error(
            f"Error deleting metrics for chat IDs {chat_ids}: {e}", exc_info=True
        )
        return 0, "Error deleting metrics. See server logs for details."


async def clear_vectorized_indices(
    database: Database, chat_ids: list[int]
) -> tuple[int, Optional[str]]:
    """
    Clear vectorized message indices used for semantic search.

    Args:
        database: Database instance with Elasticsearch client
        chat_ids: List of chat IDs for which to delete vectorized indices

    Returns:
        Tuple of (number of indices requested for deletion, error message if any)
        Note: The count represents indices we attempted to delete, not confirmed deletions,
        since Elasticsearch silently ignores non-existent indices.
    """
    index_names = [f"vectorized_messages_{chat_id}" for chat_id in chat_ids]

    error = await _bulk_delete_indices(database.es_client, index_names)

    if error:
        logger.warning(f"Failed to delete vectorized indices for chats {chat_ids}")
        return 0, error

    logger.info(
        f"Requested deletion of {len(index_names)} vectorized indices for chats: {chat_ids}"
    )
    return len(index_names), None


async def delete_chats_data(
    database: Database, chat_ids: list[int], storage: Optional[Storage] = None
) -> ChatDeletionStats:
    """
    Delete chats and all their related data.

    Orchestrates the deletion of:
    1. Collect storage references from messages (before deletion)
    2. Chat records from the chats index
    3. Message indices for the specified chats (messages_{chat_id})
    4. Metrics associated with the chats
    5. Vectorized message indices for semantic search (if they exist)
    6. Orphaned storage objects (if storage is provided)

    Args:
        database: Database instance with Elasticsearch client
        chat_ids: List of chat IDs to delete
        storage: Optional Storage instance for cleaning up orphaned files

    Returns:
        ChatDeletionStats with deletion statistics and any errors

    Raises:
        Exception: If critical operations fail (chat deletion)
    """
    stats = ChatDeletionStats()

    if not chat_ids:
        logger.warning("No chat IDs provided for deletion")
        return stats

    # 1. Collect storage references BEFORE deleting messages (if storage cleanup requested)
    storage_refs_to_check = set()
    if storage:
        storage_refs_to_check = await collect_storage_refs_from_chats(
            database, chat_ids
        )

    # 2. Delete chats from chats index
    try:
        stats.deleted_chats = await delete_chats(database, chat_ids)
    except Exception as e:
        error_msg = f"Error deleting chats: {e}"
        logger.error(error_msg, exc_info=True)
        stats.errors.append(error_msg)
        raise

    # 3. Delete message indices
    msg_count, msg_error = await delete_message_indices(database, chat_ids)
    stats.deleted_message_indices = msg_count
    if msg_error:
        stats.errors.append(msg_error)

    # 4. Delete metrics
    metrics_count, metrics_error = await delete_chat_metrics(database, chat_ids)
    stats.deleted_metrics = metrics_count
    if metrics_error:
        stats.errors.append(metrics_error)

    # 5. Clear vectorized indices
    vec_count, vec_error = await clear_vectorized_indices(database, chat_ids)
    stats.deleted_vectorized_indices = vec_count
    if vec_error:
        stats.errors.append(vec_error)

    # 6. Cleanup orphaned storage objects (if storage was provided)
    if storage and storage_refs_to_check:
        storage_count, storage_error = await storage.cleanup_orphaned_objects(
            database, storage_refs_to_check
        )
        stats.deleted_storage_objects = storage_count
        if storage_error:
            stats.errors.append(storage_error)

    return stats
