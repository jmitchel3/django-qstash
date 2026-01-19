from __future__ import annotations

import json
import logging
from typing import Any

from django.apps import apps
from django.db.models import Model
from django.utils import timezone

from django_qstash.db.models import TaskStatus

logger = logging.getLogger(__name__)


def function_result_to_dict(result: Any) -> dict[str, Any] | None:
    """
    Convert a task result to a Python dict for the result JSONField.

    Args:
        result: Any Python value to be converted

    Returns:
        dict: A dictionary representation of the result
        None: If the input is None
    """
    if result is None:
        return None
    elif isinstance(result, dict):
        return result
    elif isinstance(result, str):
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                return parsed
            return {"result": parsed}
        except json.JSONDecodeError as e:
            logger.info("Task result is not a JSON string: %s", str(e))
            return {"result": result}
    return {"result": result}


def store_task_result(
    task_id: str | None,
    task_name: str,
    status: str,
    result: Any = None,
    traceback: str | None = None,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    error: str | None = None,
    function_path: str | None = None,
) -> Model | None:
    """
    Store task result if the results app is installed.

    Args:
        task_id: QStash message ID for the task
        task_name: Human-readable name of the task
        status: Task execution status (from TaskStatus enum)
        result: Task return value (optional)
        traceback: Error traceback string (optional)
        args: Positional arguments passed to the task
        kwargs: Keyword arguments passed to the task
        error: Error message string (optional, deprecated - use traceback)
        function_path: Full dotted path to the task function

    Returns:
        TaskResult model instance if created, None if results app not installed
    """
    if status not in TaskStatus.values:
        status = TaskStatus.UNKNOWN

    try:
        TaskResult = apps.get_model("django_qstash_results", "TaskResult")
        task_result: Model = TaskResult.objects.create(
            task_id=task_id,
            task_name=task_name,
            status=status,
            date_done=timezone.now(),
            result=function_result_to_dict(result),
            traceback=traceback,
            args=args,
            kwargs=kwargs,
            function_path=function_path,
        )
        return task_result
    except LookupError:
        # Model isn't installed, skip storage
        logger.debug(
            "Django QStash Results not installed. Add `django_qstash.results` to INSTALLED_APPS and run migrations."
        )
        return None
