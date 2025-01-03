from __future__ import annotations

from django.core.exceptions import ValidationError

from django_qstash.discovery.utils import discover_tasks


def task_exists_validator(task_name):
    """
    Validates that a task name exists in the discovered tasks

    Args:
        task_name: The name of the task to validate

    Raises:
        ValidationError: If the task cannot be found
    """
    tasks = discover_tasks()
    available_tasks = [task[0] for task in tasks]

    if task_name not in available_tasks:
        raise ValidationError(
            f"Task '{task_name}' not found. Available tasks: {', '.join(available_tasks)}"
        )