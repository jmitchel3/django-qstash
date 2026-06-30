from __future__ import annotations

import functools
import inspect
import logging
import time
import traceback as traceback_module
import uuid
from collections.abc import Callable
from datetime import datetime
from datetime import timezone
from functools import partial
from typing import Any
from typing import Generic
from typing import TypeVar
from typing import cast
from typing import overload

from asgiref.sync import async_to_sync
from django.apps import apps
from django.core.exceptions import ImproperlyConfigured

from django_qstash.callbacks import get_callback_url
from django_qstash.client import qstash_client
from django_qstash.db.models import TaskStatus
from django_qstash.discovery.utils import discover_tasks
from django_qstash.exceptions import MaxRetriesExceededError
from django_qstash.exceptions import Retry
from django_qstash.exceptions import TaskResultError
from django_qstash.exceptions import TaskTimeoutError
from django_qstash.settings import qstash_settings
from django_qstash.utils import import_string

logger = logging.getLogger(__name__)

R = TypeVar("R")
T = TypeVar("T")

# Celery's default maximum number of retries when a task does not set its own.
DEFAULT_MAX_RETRIES = 3


# Statuses that represent a finished task (no further state transitions expected).
TERMINAL_STATUSES = frozenset(
    {
        TaskStatus.SUCCESS,
        TaskStatus.EXECUTION_ERROR,
        TaskStatus.INTERNAL_ERROR,
        TaskStatus.OTHER_ERROR,
        TaskStatus.UNKNOWN,
    }
)
# Terminal statuses that represent a failure rather than a success.
ERROR_STATUSES = TERMINAL_STATUSES - {TaskStatus.SUCCESS}


def _unwrap_result(stored: Any) -> Any:
    """Reverse the ``{"result": value}`` envelope used by the results backend.

    ``store_task_result`` wraps non-dict return values as ``{"result": value}``
    so they fit the JSONField. This unwraps that single-key envelope so
    ``AsyncResult.result`` returns the original scalar/list. A genuine dict
    return value with more than one key (or different keys) is returned as-is.
    """
    if isinstance(stored, dict) and set(stored.keys()) == {"result"}:
        return stored["result"]
    return stored


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


class TaskRequest:
    """Celery-compatible ``self.request`` context for ``bind=True`` tasks.

    A fresh instance is built for every execution (eager, direct, or webhook),
    so concurrent deliveries never share per-call request state.
    """

    def __init__(
        self,
        *,
        id: str,
        retries: int = 0,
        correlation_id: str = "",
        task_name: str = "",
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.id = id
        self.retries = retries
        self.correlation_id = correlation_id
        self.task_name = task_name
        self.args = args
        self.kwargs = kwargs if kwargs is not None else {}


class BoundTask:
    """Per-call ``self`` passed to a ``bind=True`` task body.

    Holds the :class:`TaskRequest` for this single execution and delegates every
    other attribute (``name``, ``delay``, ``apply_async``, ``s``, ...) to the
    shared :class:`QStashTask`. Building a fresh proxy per call keeps mutable
    request state off the shared task instance, which is required for thread
    safety under concurrent webhook deliveries.
    """

    def __init__(self, task: QStashTask[Any], request: TaskRequest) -> None:
        self._task = task
        self.request = request

    def __getattr__(self, name: str) -> Any:
        # Only reached for attributes not set on the proxy itself
        # (i.e. everything except ``_task`` and ``request``).
        return getattr(self._task, name)

    def retry(
        self,
        *,
        exc: BaseException | None = None,
        countdown: int | None = None,
        eta: datetime | int | float | None = None,
        max_retries: int | None = None,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        throw: bool = True,
        **options: Any,
    ) -> Any:
        """Celery-compatible ``self.retry()`` for ``bind=True`` tasks.

        Aborts the current execution and schedules the task to run again. In a
        live deployment the webhook handler re-enqueues a fresh QStash message
        (honoring ``countdown``/``eta``); in eager mode the body is simply re-run
        inline. ``self.request.retries`` is incremented on each attempt.

        ``max_retries`` defaults to the task's ``max_retries`` option (or
        ``DEFAULT_MAX_RETRIES``). Once ``self.request.retries`` reaches that
        limit, the retry gives up: the original ``exc`` is re-raised if one was
        supplied, otherwise :class:`MaxRetriesExceededError`. Pass ``args`` /
        ``kwargs`` to override the arguments for the next attempt.

        Like Celery, this normally raises (``throw=True``) so ``self.retry()``
        and ``raise self.retry()`` are equivalent. With ``throw=False`` the
        control-flow exception is returned instead of raised, leaving it to the
        caller to raise.
        """
        request = self.request
        retry_args = request.args if args is None else tuple(args)
        retry_kwargs = request.kwargs if kwargs is None else dict(kwargs)
        limit = max_retries if max_retries is not None else self._task.max_retries

        if limit is not None and request.retries >= limit:
            exhausted: BaseException = (
                exc
                if exc is not None
                else MaxRetriesExceededError(
                    f"Can't retry {self._task.name or 'task'} [{request.id}]: "
                    f"max_retries ({limit}) exceeded"
                )
            )
            if throw:
                raise exhausted
            return exhausted

        signal = Retry(
            args=retry_args,
            kwargs=retry_kwargs,
            retries=request.retries + 1,
            countdown=countdown,
            eta=eta,
            exc=exc,
        )
        if throw:
            raise signal
        return signal


class Signature:
    """A lightweight, serializable reference to a task call (Celery ``.s()``).

    Captures the target task's function path plus the args/kwargs/options to
    invoke it with. Used by ``apply_async(link=...)`` to chain a follow-up task
    after the parent succeeds. The parent's return value is intentionally not
    forwarded to the linked task (see the chaining docs).
    """

    def __init__(
        self,
        function: str,
        module: str,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        immutable: bool = False,
    ) -> None:
        self.function = function
        self.module = module
        self.args = args
        self.kwargs = kwargs if kwargs is not None else {}
        self.options = options if options is not None else {}
        self.immutable = immutable

    @property
    def function_path(self) -> str:
        return f"{self.module}.{self.function}"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the JSON-friendly form stored in a task's payload."""
        return {
            "function": self.function,
            "module": self.module,
            "args": list(self.args),
            "kwargs": self.kwargs,
            "options": self.options,
        }


def _normalize_links(
    link: Signature | list[Signature] | tuple[Signature, ...] | None,
) -> list[Signature]:
    """Coerce a ``link=`` value into a list of :class:`Signature` objects."""
    if link is None:
        return []
    if isinstance(link, Signature):
        return [link]
    return list(link)


def enqueue_links(links: list[dict[str, Any]]) -> None:
    """Resolve and enqueue serialized success-link signatures.

    Each link is validated against the registered-task allowlist
    (``discover_tasks``); links that are not registered, cannot be imported, or
    fail to enqueue are logged and skipped so a chaining problem never fails the
    parent task. In eager mode each linked task runs inline (its own
    ``apply_async`` is eager).
    """
    if not links:
        return
    try:
        registered = set(discover_tasks(locations_only=True))
    except Exception as exc:
        logger.warning("Could not resolve linked tasks for chaining: %s", exc)
        return
    for link in links:
        function_path = f"{link.get('module')}.{link.get('function')}"
        if function_path not in registered:
            logger.warning(
                "Skipping linked task %s: not a registered @stashed_task",
                function_path,
            )
            continue
        try:
            task = import_string(function_path)
            options = dict(link.get("options") or {})
            task.apply_async(
                args=tuple(link.get("args") or ()),
                kwargs=dict(link.get("kwargs") or {}),
                **options,
            )
        except Exception as exc:
            logger.warning("Failed to enqueue linked task %s: %s", function_path, exc)
            continue


class QStashTask(Generic[R]):
    def __init__(
        self,
        func: Callable[..., R] | None = None,
        name: str | None = None,
        delay_seconds: int | None = None,
        deduplicated: bool = False,
        bind: bool = False,
        **options: Any,
    ) -> None:
        self.func = func
        self.name = name or (func.__name__ if func else None)
        self.delay_seconds = delay_seconds
        self.deduplicated = deduplicated
        self.bind = bind
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
        if not qstash_settings.QSTASH_TOKEN or not qstash_settings.DJANGO_QSTASH_DOMAIN:
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
                bind=self.bind,
                **self.options,
            )

        if self.bind:
            return cast(R, self._run_with_retries(args, kwargs))
        return self.func(*args, **kwargs)

    @property
    def max_retries(self) -> int | None:
        """Maximum retry attempts for ``self.retry()`` (Celery ``max_retries``).

        Resolved from the task's ``max_retries`` option, falling back to the
        ``retries`` option (the QStash message-level retry count) and finally to
        :data:`DEFAULT_MAX_RETRIES`. ``None`` means unlimited.
        """
        if "max_retries" in self.options:
            return cast("int | None", self.options["max_retries"])
        if "retries" in self.options:
            return cast("int | None", self.options["retries"])
        return DEFAULT_MAX_RETRIES

    @property
    def actual_func(self) -> Callable[..., Any]:
        """Synchronous callable that runs the task body.

        Used by the webhook handler and eager execution. Coroutine task
        functions are run to completion via ``async_to_sync`` so callers always
        receive a concrete value instead of an un-awaited coroutine.
        """
        return self._run

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        """Run the wrapped function, awaiting it if it is a coroutine function."""
        if self.func is None:
            raise ImproperlyConfigured("QStashTask must wrap a function before running")
        if inspect.iscoroutinefunction(self.func):
            return async_to_sync(self.func)(*args, **kwargs)
        return self.func(*args, **kwargs)

    def run_with_context(self, request: TaskRequest, *args: Any, **kwargs: Any) -> Any:
        """Run the task body, injecting a bound ``self`` when ``bind=True``.

        Context-aware entry point used by the webhook handler and eager
        execution. When ``bind`` is True a fresh :class:`BoundTask` proxy is
        passed as the leading positional argument (carrying ``request``);
        otherwise the body is invoked exactly as a plain call, with no extra
        leading argument. Coroutine task functions are awaited via ``_run``.
        """
        if self.bind:
            bound = BoundTask(self, request)
            return self._run(bound, *args, **kwargs)
        return self._run(*args, **kwargs)

    def _eager_request(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        task_id: str | None = None,
        retries: int = 0,
    ) -> TaskRequest:
        """Build a request for inline execution (direct call / eager / apply)."""
        task_id = task_id or str(uuid.uuid4())
        return TaskRequest(
            id=task_id,
            retries=retries,
            correlation_id=task_id,
            task_name=self.name or "",
            args=tuple(args),
            kwargs=dict(kwargs),
        )

    def _run_with_retries(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        task_id: str | None = None,
    ) -> Any:
        """Run the task body inline, honoring inline ``self.retry()`` calls.

        Each :class:`Retry` raised by ``self.retry()`` re-runs the body with the
        retry's (possibly overridden) args/kwargs and an incremented retry count,
        keeping the same task id across attempts (like Celery). The loop ends
        when the body returns a value or raises any non-:class:`Retry`
        exception (including :class:`MaxRetriesExceededError` once the limit is
        reached), which propagates to the caller. ``countdown``/``eta`` carried
        by a retry are ignored inline: eager retries run immediately.
        """
        task_id = task_id or str(uuid.uuid4())
        retries = 0
        while True:
            request = self._eager_request(
                args, kwargs, task_id=task_id, retries=retries
            )
            try:
                return self.run_with_context(request, *args, **kwargs)
            except Retry as retry_signal:
                args = retry_signal.task_args
                kwargs = retry_signal.task_kwargs
                retries = retry_signal.retries

    def _signature(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        immutable: bool,
    ) -> Signature:
        if self.func is None:
            raise ImproperlyConfigured(
                "QStashTask must wrap a function before building a signature"
            )
        return Signature(
            function=self.func.__name__,
            module=self.func.__module__,
            args=args,
            kwargs=kwargs,
            immutable=immutable,
        )

    def s(self, *args: Any, **kwargs: Any) -> Signature:
        """Celery-compatible signature: capture a call for later chaining."""
        return self._signature(args, kwargs, immutable=False)

    def si(self, *args: Any, **kwargs: Any) -> Signature:
        """Immutable signature variant of :meth:`s` (Celery ``.si()``).

        Behaves identically to ``.s()`` here because django-qstash does not
        forward the parent task's result to linked tasks.
        """
        return self._signature(args, kwargs, immutable=True)

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
        link: Signature | list[Signature] | None = None,
        _retries: int = 0,
        **options: Any,
    ) -> AsyncResult:
        if self.func is None:
            raise ImproperlyConfigured("QStashTask must wrap a function before queuing")

        payload: dict[str, Any] = {
            "function": self.func.__name__,
            "module": self.func.__module__,
            "args": args,
            "kwargs": kwargs,
            "task_name": self.name,
            "options": self.options,
        }

        # Carry the retry attempt number so the next execution's
        # ``self.request.retries`` reflects self.retry()-driven re-enqueues. The
        # name is underscored to keep it distinct from the QStash ``retries``
        # message option (the delivery-level auto-retry count).
        if _retries:
            payload["retries"] = _retries

        links = _normalize_links(link)
        if links:
            payload["on_success"] = [sig.to_dict() for sig in links]

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
        """Celery-compatible delay() method.

        Runs inline (no network, no QStash config required) when
        ``DJANGO_QSTASH_ALWAYS_EAGER`` is set, otherwise publishes to QStash.
        """
        if qstash_settings.DJANGO_QSTASH_ALWAYS_EAGER:
            return self.apply(args=args, kwargs=kwargs)
        return self._enqueue(args=args, kwargs=kwargs)

    def apply_async(
        self,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        countdown: int | None = None,
        eta: datetime | int | float | None = None,
        link: Signature | list[Signature] | None = None,
        **options: Any,
    ) -> AsyncResult:
        """Celery-compatible apply_async() method.

        Runs inline (no network, no QStash config required) when
        ``DJANGO_QSTASH_ALWAYS_EAGER`` is set, otherwise publishes to QStash.

        ``link`` attaches one or more :class:`Signature` success-links: after
        this task succeeds, each linked task is enqueued (in eager mode they run
        inline). Only registered ``@stashed_task`` links are chained.
        """
        args = args or ()
        kwargs = kwargs or {}
        if qstash_settings.DJANGO_QSTASH_ALWAYS_EAGER:
            return self.apply(args=args, kwargs=kwargs, link=link)
        return self._enqueue(
            args=args,
            kwargs=kwargs,
            countdown=countdown,
            eta=eta,
            link=link,
            **options,
        )

    def apply(
        self,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        link: Signature | list[Signature] | None = None,
        **options: Any,
    ) -> EagerResult:
        """Execute the task synchronously and return an :class:`EagerResult`.

        Mirrors Celery's ``Task.apply()``: the task body runs inline in the
        current process and the return value (or raised exception) is captured
        on the result. No QStash token/domain and no network access are required,
        which makes this the primary tool for unit-testing code that calls
        ``.delay()``/``.apply_async()``. The captured value is returned exactly
        (no results-backend round-trip), so types are preserved.

        Honors ``bind=True`` (a :class:`TaskRequest` with a generated uuid id and
        ``retries=0`` is built) and runs any ``link`` signatures inline after a
        successful execution. Inline ``self.retry()`` calls re-run the body
        immediately (ignoring ``countdown``/``eta``) until it succeeds or the
        retry limit is exceeded, at which point the failure is captured on the
        :class:`EagerResult`.

        ``options`` is accepted for Celery signature compatibility and ignored;
        delivery options have no meaning for inline execution.
        """
        args = args or ()
        kwargs = kwargs or {}
        task_id = str(uuid.uuid4())
        try:
            value = self._run_with_retries(args, kwargs, task_id=task_id)
        except Exception as exc:
            return EagerResult(
                task_id,
                exc,
                TaskStatus.EXECUTION_ERROR,
                traceback=traceback_module.format_exc(),
            )
        enqueue_links([sig.to_dict() for sig in _normalize_links(link)])
        return EagerResult(task_id, value, TaskStatus.SUCCESS)


class AsyncResult:
    """Celery ``AsyncResult``-compatible handle backed by the results backend.

    Looks up :class:`~django_qstash.results.models.TaskResult` rows by the
    QStash message id (``task_id``) to expose ``status``/``state``, ``result``,
    and a polling ``get()``. Results are eventually consistent: a row only
    exists once the webhook has executed the task, so ``status`` is ``PENDING``
    until then. If ``django_qstash.results`` is not installed, every lookup
    resolves to ``PENDING`` and ``get()`` will time out.
    """

    def __init__(self, task_id: str):
        self.task_id = task_id

    @property
    def id(self) -> str:
        return self.task_id

    def _row(self) -> Any:
        """Return the most recent TaskResult row for this task_id, or None."""
        try:
            TaskResult = apps.get_model("django_qstash_results", "TaskResult")
        except LookupError:
            return None
        return (
            TaskResult.objects.filter(task_id=self.task_id)
            .order_by("-date_done", "-date_created")
            .first()
        )

    @property
    def status(self) -> str:
        row = self._row()
        return row.status if row is not None else TaskStatus.PENDING

    # Celery exposes both .status and .state as aliases.
    @property
    def state(self) -> str:
        return self.status

    @property
    def result(self) -> Any:
        row = self._row()
        if row is None:
            return None
        return _unwrap_result(row.result)

    @property
    def traceback(self) -> str | None:
        row = self._row()
        return row.traceback if row is not None else None

    def ready(self) -> bool:
        """True once a terminal result row exists for this task."""
        return self.status in TERMINAL_STATUSES

    def successful(self) -> bool:
        return self.status == TaskStatus.SUCCESS

    def failed(self) -> bool:
        return self.status in ERROR_STATUSES

    def get(
        self,
        timeout: float | None = None,
        interval: float | None = None,
        propagate: bool = True,
    ) -> Any:
        """Block until a terminal result is available, then return it.

        Polls the results backend every ``interval`` seconds (defaults to
        ``DJANGO_QSTASH_RESULT_POLL_INTERVAL``). With ``timeout=None`` (Celery's
        default) it waits indefinitely; otherwise :class:`TaskTimeoutError` is
        raised once ``timeout`` seconds elapse. When the task failed and
        ``propagate`` is True, :class:`TaskResultError` is raised carrying the
        stored traceback.
        """
        if interval is None:
            interval = qstash_settings.DJANGO_QSTASH_RESULT_POLL_INTERVAL
        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            row = self._row()
            if row is not None and row.status in TERMINAL_STATUSES:
                if propagate and row.status in ERROR_STATUSES:
                    raise TaskResultError(
                        row.traceback or f"Task {self.task_id} failed: {row.status}"
                    )
                return _unwrap_result(row.result)

            if deadline is not None and time.monotonic() >= deadline:
                raise TaskTimeoutError(
                    f"Timed out after {timeout}s waiting for result of task "
                    f"{self.task_id}"
                )
            time.sleep(interval)


class EagerResult(AsyncResult):
    """AsyncResult returned by :meth:`QStashTask.apply` for inline execution.

    Carries the captured return value (or exception) in memory, so no
    results-backend round-trip is needed and the original value type is
    preserved exactly.
    """

    def __init__(
        self,
        task_id: str,
        value: Any,
        status: str,
        traceback: str | None = None,
    ) -> None:
        super().__init__(task_id)
        self._value = value
        self._status = status
        self._traceback = traceback

    @property
    def status(self) -> str:
        return self._status

    @property
    def state(self) -> str:
        return self._status

    @property
    def result(self) -> Any:
        return self._value

    @property
    def traceback(self) -> str | None:
        return self._traceback

    def ready(self) -> bool:
        return True

    def successful(self) -> bool:
        return self._status == TaskStatus.SUCCESS

    def failed(self) -> bool:
        return self._status in ERROR_STATUSES

    def get(
        self,
        timeout: float | None = None,
        interval: float | None = None,
        propagate: bool = True,
    ) -> Any:
        if self._status == TaskStatus.SUCCESS:
            return self._value
        if propagate and isinstance(self._value, BaseException):
            raise self._value
        return self._value
