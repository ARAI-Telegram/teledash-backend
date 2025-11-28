from celery.utils.log import get_task_logger

from common.database.models.chat import Chat
from common.database.models.message import Message
from common.database.models.metric import Metric
from worker.utils.containers import ResultsContainer
from worker.utils.helpers import add_metric

logger = get_task_logger(__name__)


def add_chat_metric(chat: Chat, container: ResultsContainer) -> None:
    """Create and add a metric for chat member count.

    Only creates a metric if the chat has a member count available.

    Args:
        chat: Chat to create metric for.
        container: Results container to add metric to.
    """
    if chat.members_count is not None:
        try:
            add_metric("metrics", container, Metric.from_chat, chat)
        except ValueError as e:
            logger.error(f"Failed to create metric for chat {chat.id}: {e}")


def add_message_metric(
    message: Message,
    container: ResultsContainer,
) -> None:
    """Create and add a "new_message_posted" metric for a new message.

    Args:
        message: Message to create metric for.
        container: Results container to add metric to.
    """
    try:
        add_metric("metrics", container, Metric.from_new_message_posted, message)
    except ValueError as e:
        logger.error(f"Failed to create metric for message {message.id}: {e}")
