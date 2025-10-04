from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django_qstash.app.base import QStashTask


def stashed_task(
    func: Callable | None = None,
    name: str | None = None,
    deduplicated: bool = False,
    **options: dict[str, Any],
) -> QStashTask:
    """
    Decorator that mimics Celery's shared_task that maintains
    Celery compatibility.

    Can be used as:

        from django_qstash import shared_task

        @shared_task
        def my_task():
            pass

        @stashed_task(name="custom_name", deduplicated=True)
        def my_task():
            pass
    """
    if func is not None:
        return QStashTask(func, name=name, deduplicated=deduplicated, **options)
    return lambda f: QStashTask(f, name=name, deduplicated=deduplicated, **options)


def shared_task(func: Callable | None = None, **options: dict[str, Any]) -> QStashTask:
    """
    Decorator that is a drop-in replacement for Celery's shared_task.

    Can be used as:

        from django_qstash import shared_task

        @shared_task
        def my_task():
            pass
    """
    return stashed_task(func, **options)
