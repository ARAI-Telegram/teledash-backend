"""
Get active Celery tasks by name.
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
