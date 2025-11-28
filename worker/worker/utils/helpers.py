"""Generic scraping utility functions.

This module contains reusable helper functions for scraping operations
that don't belong to specific managers or API calls.
"""

from typing import Callable, List

from celery.utils.log import get_task_logger

from common.database.models.metric import Metric
from common.database.models.user import User
from common.settings import settings
from common.storage import StorageBucketNames
from common.utils import flatten
from worker.utils.containers import ResultsContainer

ClientChatMap = List[tuple[str, set[int]]]
logger = get_task_logger(__name__)


def exclude_duplicate_chat_ids(clients: ClientChatMap) -> ClientChatMap:
    """
    Make each client have a unique set of chat ids.

    For clients with overlapping chat access, this function removes duplicates
    such that each chat is assigned to exactly one client. Clients with more
    chats are prioritized.

    Args:
        clients: List of tuples (client_id, chat_ids_set).

    Returns:
        List of tuples with unique chat IDs per client.
    """
    if len(clients) <= 1:
        return clients

    # sort list, entry with most chat ids to the top
    clients.sort(key=lambda x: len(x[1]), reverse=True)

    # find duplicate chat ids and remove them
    for index, client in enumerate(clients):
        client_id, chat_ids = client
        duplicates = flatten(
            [
                [id for id in ch_ids if id in chat_ids]
                for cl_id, ch_ids in clients
                if cl_id != client_id
            ]
        )
        clients[index] = (client_id, {id for id in chat_ids if id not in duplicates})

    return clients


def add_metric(
    key: str, container: ResultsContainer, metric_creator: Callable[..., Metric], *args
) -> None:
    """
    Create a metric and add it to a results container.

    Args:
        key: The container key for metrics (usually "metrics").
        container: Results container to add the metric to.
        metric_creator: Function to create the metric (e.g., Metric.from_chat).
        *args: Arguments to pass to the metric_creator function.
    """
    try:
        metric = metric_creator(*args)
        container.add(key, metric)
    except ValueError as e:
        logger.error(f"Failed to create metric: {e}")


def bucket_name_from_attachment_type(attachment_type: str) -> str:
    """Get storage bucket name for an attachment type.

    Args:
        attachment_type: Type of attachment (photo, video, etc.)

    Returns:
        Bucket name string.
    """
    return StorageBucketNames(attachment_type.replace("_", "-") + "s").value


def add_users_if_enabled(
    users: List[User],
    container: ResultsContainer,
) -> None:
    """Add users to container if user scraping is enabled.

    Args:
        users: List of users to process.
        container: Results container to add users to.
    """
    if not users or not settings.scrape_users:
        return

    for user in users:
        if not container.has("users", "_id", user.id):
            container.add("users", user)
