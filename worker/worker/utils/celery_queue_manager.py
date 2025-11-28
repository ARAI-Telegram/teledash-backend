"""
Simple task deduplication by checking active queue.
"""

from celery.utils.log import get_task_logger
from worker.main import app

logger = get_task_logger(__name__)


def get_active_tasks(task_names: list[str]) -> list[dict]:
    """
    Get a list of active tasks matching the given task names.
    """
    result = []
    inspect = app.control.inspect()
    if not inspect:
        return result

    active = inspect.active() or {}
    for worker_name, worker_tasks in active.items():
        wanted_tasks = [task for task in worker_tasks if task["name"] in task_names]
        result.extend(wanted_tasks)

    return result


def task_already_reserved(task_name: str) -> bool:
    """
    Check if a task with the given name is already reserved (queued but not yet started).
    """
    inspect = app.control.inspect()
    if not inspect:
        return False

    reserved = inspect.reserved() or {}
    if any(
        task.get("name") == task_name for tasks in reserved.values() for task in tasks
    ):
        logger.info(f"Task {task_name} is already reserved")
        return True

    return False
