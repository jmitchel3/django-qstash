from __future__ import annotations


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
