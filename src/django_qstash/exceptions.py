from __future__ import annotations

from datetime import datetime
from typing import Any


class WebhookError(Exception):
    """Base exception for webhook handling errors."""

    pass


class SignatureError(WebhookError):
    """Invalid or missing signature."""

    pass


class PayloadError(WebhookError):
    """Invalid payload structure or content."""

    pass


class TaskError(WebhookError):
    """Error in task execution."""

    pass


class TaskResultError(Exception):
    """Raised when an AsyncResult is resolved for a task that did not succeed.

    Mirrors Celery's behavior of re-raising the task's failure when calling
    ``AsyncResult.get(propagate=True)``. The original traceback string from the
    results backend is preserved in the message.
    """

    pass


class TaskTimeoutError(TaskResultError):
    """Raised when AsyncResult.get(timeout=...) elapses before a terminal result."""

    pass


class Retry(Exception):
    """Internal control-flow signal raised by ``self.retry()`` (Celery ``Retry``).

    Carries everything needed to re-run the task: the (possibly overridden)
    ``args``/``kwargs``, the incremented ``retries`` count, and the scheduling
    delay (``countdown``/``eta``). It is never wrapped as a task failure; instead
    the eager runner re-runs the body inline and the webhook handler re-enqueues
    a fresh QStash message, mirroring Celery's "abort this run, schedule the
    next" semantics.
    """

    def __init__(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        retries: int,
        countdown: int | None = None,
        eta: datetime | int | float | None = None,
        exc: BaseException | None = None,
    ) -> None:
        # Forward every argument to ``Exception.__init__`` so the signal stays
        # copy/pickle-safe (it is only ever caught in-process, but this keeps the
        # exception well-behaved and satisfies flake8-bugbear B042).
        super().__init__(args, kwargs, retries, countdown, eta, exc)
        self.task_args = args
        self.task_kwargs = kwargs
        self.retries = retries
        self.countdown = countdown
        self.eta = eta
        self.exc = exc


class MaxRetriesExceededError(Exception):
    """Raised when ``self.retry()`` is called after the retry limit is reached.

    Mirrors Celery's ``MaxRetriesExceededError``: once ``self.request.retries``
    reaches the task's ``max_retries`` the next ``self.retry()`` gives up. If the
    retry was triggered with an explicit ``exc`` that original exception is
    re-raised instead of this one.
    """

    pass
