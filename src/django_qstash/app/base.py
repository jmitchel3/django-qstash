from __future__ import annotations

import functools
import inspect
from datetime import datetime
from datetime import timezone
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


MESSAGE_OPTION_NAMES = frozenset(
    {
        "callback",
        "callback_headers",
        "content_based_deduplication",
        "deduplicated",
        "deduplication_id",
        "delay",
        "failure_callback",
        "failure_callback_headers",
        "flow_control",
        "headers",
        "label",
        "max_retries",
        "method",
        "not_before",
        "queue",
        "redact",
        "retries",
        "retry_delay",
        "timeout",
    }
)


def _timestamp(value: datetime | int | float) -> int:
    """Convert Celery-style eta values to QStash's unix timestamp format."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp())
    return int(value)


def _delay(value: Any) -> Any:
    """Preserve the historical N-seconds string format for integer delays."""
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value}s"
    return value


def _supported_kwargs(
    method: Callable[..., Any], options: dict[str, Any]
) -> dict[str, Any]:
    signature = inspect.signature(method)
    if any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        return options

    supported = {
        name
        for name, parameter in signature.parameters.items()
        if name != "self"
        and parameter.kind
        in (inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    }
    unsupported = sorted(set(options) - supported)
    if unsupported:
        unsupported_list = ", ".join(unsupported)
        raise ImproperlyConfigured(
            "The installed qstash package does not support these message options: "
            f"{unsupported_list}. Upgrade qstash to a version that supports them."
        )
    return options


class QStashTask(Generic[R]):
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

        return self.func(*args, **kwargs)

    def _message_options(
        self,
        options: dict[str, Any],
        countdown: int | None = None,
        eta: datetime | int | float | None = None,
    ) -> dict[str, Any]:
        message_options = dict(self.options)
        message_options.update(options)

        if self.delay_seconds is not None:
            message_options.setdefault("delay", self.delay_seconds)
        if countdown is not None:
            message_options["delay"] = countdown
        if eta is not None:
            message_options["not_before"] = _timestamp(eta)

        max_retries = message_options.pop("max_retries", None)
        if max_retries is not None and "retries" not in message_options:
            message_options["retries"] = max_retries

        deduplicated = message_options.pop("deduplicated", None)
        if (
            deduplicated is not None
            and "content_based_deduplication" not in message_options
        ):
            message_options["content_based_deduplication"] = deduplicated
        if self.deduplicated:
            message_options.setdefault("content_based_deduplication", True)

        if "delay" in message_options:
            message_options["delay"] = _delay(message_options["delay"])

        return {
            key: value
            for key, value in message_options.items()
            if key in MESSAGE_OPTION_NAMES and value is not None
        }

    def _enqueue(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        countdown: int | None = None,
        eta: datetime | int | float | None = None,
        **options: Any,
    ) -> AsyncResult:
        if self.func is None:
            raise ImproperlyConfigured("QStashTask must wrap a function before queuing")

        payload = {
            "function": self.func.__name__,
            "module": self.func.__module__,
            "args": args,
            "kwargs": kwargs,
            "task_name": self.name,
            "options": self.options,
        }

        url = get_callback_url()
        message_options = self._message_options(
            options=options,
            countdown=countdown,
            eta=eta,
        )
        queue = message_options.pop("queue", None)

        response: Any
        if queue is None:
            publish = qstash_client.message.publish_json
            send_options = _supported_kwargs(publish, message_options)
            response = publish(url=url, body=payload, **send_options)
        else:
            enqueue = qstash_client.message.enqueue_json
            send_options = _supported_kwargs(enqueue, message_options)
            response = enqueue(queue=queue, url=url, body=payload, **send_options)

        # Return an AsyncResult-like object for Celery compatibility
        return AsyncResult(response.message_id)

    def delay(self, *args: Any, **kwargs: Any) -> AsyncResult:
        """Celery-compatible delay() method"""
        return self._enqueue(args=args, kwargs=kwargs)

    def apply_async(
        self,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        countdown: int | None = None,
        eta: datetime | int | float | None = None,
        **options: Any,
    ) -> AsyncResult:
        """Celery-compatible apply_async() method"""
        args = args or ()
        kwargs = kwargs or {}
        return self._enqueue(
            args=args,
            kwargs=kwargs,
            countdown=countdown,
            eta=eta,
            **options,
        )


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
