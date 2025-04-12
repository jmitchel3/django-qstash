from __future__ import annotations


class WebhookError(Exception):
    """Base exception for webhook handling errors."""


class SignatureError(WebhookError):
    """Invalid or missing signature."""


class PayloadError(WebhookError):
    """Invalid payload structure or content."""


class TaskError(WebhookError):
    """Error in task execution."""
