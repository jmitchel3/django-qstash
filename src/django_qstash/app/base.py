from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_qstash.callbacks import get_callback_url
from django_qstash.client import qstash_client
from django_qstash.settings import DJANGO_QSTASH_DOMAIN
from django_qstash.settings import QSTASH_TOKEN


class QStashTask:
    def __init__(
        self,
        func: Callable | None = None,
        name: str | None = None,
        delay_seconds: int | None = None,
        deduplicated: bool = False,
        **options: dict[str, Any],
    ):
        self.func = func
        self.name = name or (func.__name__ if func else None)
        self.delay_seconds = delay_seconds
        self.deduplicated = deduplicated
        self.options = options

        if func is not None:
            functools.update_wrapper(self, func)

    def __get__(self, obj, objtype):
        """Support for instance methods"""
        return functools.partial(self.__call__, obj)

    def __call__(self, *args, **kwargs):
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

    def delay(self, *args, **kwargs) -> AsyncResult:
        """Celery-compatible delay() method"""
        self._is_delayed = True
        return self(*args, **kwargs)

    def apply_async(
        self,
        args: tuple | None = None,
        kwargs: dict | None = None,
        countdown: int | None = None,
        **options: dict[str, Any],
    ) -> AsyncResult:
        """Celery-compatible apply_async() method"""
        self._is_delayed = True
        if countdown is not None:
            self.delay_seconds = countdown
        self.options.update(options)

        # Fix: Ensure we're passing the arguments correctly
        args = args or ()
        kwargs = kwargs or {}
        return self(*args, **kwargs)


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
