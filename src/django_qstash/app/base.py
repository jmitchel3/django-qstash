from __future__ import annotations

import functools
from functools import partial
from typing import Any
from typing import Callable
from typing import Generic
from typing import TypeVar
from typing import overload

from django.core.exceptions import ImproperlyConfigured

from django_qstash.callbacks import get_callback_url
from django_qstash.client import qstash_client
from django_qstash.settings import DJANGO_QSTASH_DOMAIN
from django_qstash.settings import QSTASH_TOKEN

R = TypeVar("R")
T = TypeVar("T")


class QStashTask(Generic[R]):
    _is_delayed: bool

    def __init__(
        self,
        func: Callable[..., R] | None = None,
        name: str | None = None,
        delay_seconds: int | None = None,
        deduplicated: bool = False,
        **options: Any,
    ) -> None:
        self.func = func
        self.name = name or (func.__name__ if func else None)
        self.delay_seconds = delay_seconds
        self.deduplicated = deduplicated
        self.options: dict[str, Any] = dict(options)
        self._is_delayed = False

        if func is not None:
            functools.update_wrapper(self, func)

    @overload
    def __get__(self, obj: None, objtype: type[T]) -> QStashTask[R]: ...

    @overload
    def __get__(
        self, obj: T, objtype: type[T] | None = None
    ) -> partial[R | QStashTask[R] | AsyncResult]: ...

    def __get__(
        self, obj: T | None, objtype: type[T] | None = None
    ) -> QStashTask[R] | partial[R | QStashTask[R] | AsyncResult]:
        """Support for instance methods"""
        if obj is None:
            return self
        return functools.partial(self.__call__, obj)

    def __call__(self, *args: Any, **kwargs: Any) -> R | QStashTask[R] | AsyncResult:
        """
        Execute the task, either directly or via QStash based on context
        """
        if not QSTASH_TOKEN or not DJANGO_QSTASH_DOMAIN:
            raise ImproperlyConfigured(
                "QSTASH_TOKEN and DJANGO_QSTASH_DOMAIN must be set to use django-qstash"
            )
        # Handle the case when the decorator is used without parameters
        if self.func is None:
            return self.__class__(
                args[0],
                name=self.name,
                delay_seconds=self.delay_seconds,
                deduplicated=self.deduplicated,
                **self.options,
            )

        # If called directly (not through delay/apply_async), execute the function
        if not getattr(self, "_is_delayed", False):
            return self.func(*args, **kwargs)

        # Reset the delayed flag
        self._is_delayed = False

        # Prepare the payload
        payload = {
            "function": self.func.__name__,
            "module": self.func.__module__,
            "args": args,  # Send args as-is
            "kwargs": kwargs,
            "task_name": self.name,
            "options": self.options,
        }

        url = get_callback_url()
        # Send to QStash using the official SDK
        response = qstash_client.message.publish_json(
            url=url,
            body=payload,
            delay=f"{self.delay_seconds}s" if self.delay_seconds else None,
            retries=self.options.get("max_retries", 3),
            content_based_deduplication=self.deduplicated,
        )
        # Return an AsyncResult-like object for Celery compatibility
        return AsyncResult(response.message_id)

    def delay(self, *args: Any, **kwargs: Any) -> AsyncResult:
        """Celery-compatible delay() method"""
        self._is_delayed = True
        result = self(*args, **kwargs)
        # When _is_delayed is True, __call__ returns AsyncResult
        assert isinstance(result, AsyncResult)
        return result

    def apply_async(
        self,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        countdown: int | None = None,
        **options: Any,
    ) -> AsyncResult:
        """Celery-compatible apply_async() method"""
        self._is_delayed = True
        if countdown is not None:
            self.delay_seconds = countdown
        self.options.update(options)

        # Fix: Ensure we're passing the arguments correctly
        args = args or ()
        kwargs = kwargs or {}
        result = self(*args, **kwargs)
        # When _is_delayed is True, __call__ returns AsyncResult
        assert isinstance(result, AsyncResult)
        return result


class AsyncResult:
    """Minimal Celery AsyncResult-compatible class"""

    def __init__(self, task_id: str):
        self.task_id = task_id

    def get(self, timeout: int | None = None) -> Any:
        """Simulate Celery's get() method"""
        raise NotImplementedError("QStash doesn't support result retrieval")

    @property
    def id(self) -> str:
        return self.task_id
