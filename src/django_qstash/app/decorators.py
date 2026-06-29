from __future__ import annotations

from collections.abc import Callable
from typing import Any
from typing import TypeVar
from typing import overload

from django_qstash.app.base import QStashTask

R = TypeVar("R")


@overload
def stashed_task(
    func: Callable[..., R],
    name: str | None = None,
    deduplicated: bool = False,
    bind: bool = False,
    **options: Any,
) -> QStashTask[R]: ...


@overload
def stashed_task(
    func: None = None,
    name: str | None = None,
    deduplicated: bool = False,
    bind: bool = False,
    **options: Any,
) -> Callable[[Callable[..., R]], QStashTask[R]]: ...


def stashed_task(
    func: Callable[..., R] | None = None,
    name: str | None = None,
    deduplicated: bool = False,
    bind: bool = False,
    **options: Any,
) -> QStashTask[R] | Callable[[Callable[..., R]], QStashTask[R]]:
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

    With ``bind=True`` the task body receives a bound ``self`` first argument
    exposing ``self.request`` (id, retries, correlation_id, task_name, args,
    kwargs) plus the task's own ``delay``/``apply_async`` for self-rescheduling:

        @stashed_task(bind=True)
        def my_task(self, value):
            print(self.request.id, self.request.retries)
    """
    if func is not None:
        return QStashTask(
            func, name=name, deduplicated=deduplicated, bind=bind, **options
        )
    return lambda f: QStashTask(
        f, name=name, deduplicated=deduplicated, bind=bind, **options
    )


@overload
def shared_task(
    func: Callable[..., R],
    bind: bool = False,
    **options: Any,
) -> QStashTask[R]: ...


@overload
def shared_task(
    func: None = None,
    bind: bool = False,
    **options: Any,
) -> Callable[[Callable[..., R]], QStashTask[R]]: ...


def shared_task(
    func: Callable[..., R] | None = None,
    bind: bool = False,
    **options: Any,
) -> QStashTask[R] | Callable[[Callable[..., R]], QStashTask[R]]:
    """
    Decorator that is a drop-in replacement for Celery's shared_task.

    Can be used as:

        from django_qstash import shared_task

        @shared_task
        def my_task():
            pass

        @shared_task(bind=True)
        def my_task(self):
            pass
    """
    return stashed_task(func, bind=bind, **options)
