from __future__ import annotations

import contextvars
import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from urllib.parse import urlunparse

from django.conf import settings
from django.http import HttpRequest
from qstash import Receiver

from django_qstash.db.models import TaskStatus
from django_qstash.discovery.utils import discover_tasks
from django_qstash.settings import DJANGO_QSTASH_EMIT_SIGNALS
from django_qstash.settings import DJANGO_QSTASH_LOG_TASK_ARGS
from django_qstash.settings import DJANGO_QSTASH_MAX_PAYLOAD_SIZE

from . import utils
from .exceptions import PayloadError
from .exceptions import SignatureError
from .exceptions import TaskError
from .results.services import store_task_result

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("django_qstash.audit")

# Module-level context variable for correlation ID tracking
correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)


def _emit_signal(signal: Any, **kwargs: Any) -> None:
    """Emit a Django signal if signal emission is enabled."""
    if DJANGO_QSTASH_EMIT_SIGNALS:
        signal.send_robust(sender=None, **kwargs)


@dataclass
class TaskPayload:
    function: str
    module: str
    args: list
    kwargs: dict
    task_name: str
    function_path: str

    @classmethod
    def from_dict(cls, data: dict) -> TaskPayload:
        """Create TaskPayload from dictionary."""
        is_valid, error = utils.validate_task_payload(data)
        if not is_valid:
            raise PayloadError(error)

        function_path = f"{data['module']}.{data['function']}"
        return cls(
            function=data["function"],
            module=data["module"],
            args=data["args"],
            kwargs=data["kwargs"],
            task_name=data.get("task_name", function_path),
            function_path=function_path,
        )


class QStashWebhook:
    def __init__(self):
        self.receiver = Receiver(
            current_signing_key=settings.QSTASH_CURRENT_SIGNING_KEY,
            next_signing_key=settings.QSTASH_NEXT_SIGNING_KEY,
        )
        self.force_https = getattr(settings, "DJANGO_QSTASH_FORCE_HTTPS", True)

    def _ensure_https(self, url: str) -> str:
        """
        Ensure URL uses HTTPS protocol if force_https is enabled.

        Uses proper URL parsing instead of string replacement to avoid
        edge cases and ensure correct protocol handling.

        Args:
            url: The URL to process

        Returns:
            URL with https scheme if force_https is True and scheme was http,
            otherwise returns the URL unchanged.
        """
        if not self.force_https:
            return url

        parsed = urlparse(url)

        # Only replace if scheme is http (case-insensitive)
        if parsed.scheme.lower() == "http":
            # Reconstruct with https scheme, preserving all other components
            return urlunparse(("https",) + parsed[1:])

        return url

    def verify_signature(self, body: str, signature: str, url: str) -> None:
        """Verify QStash signature."""
        if not signature:
            raise SignatureError("Missing Upstash-Signature header")

        url = self._ensure_https(url)

        try:
            self.receiver.verify(body=body, signature=signature, url=url)
        except Exception as e:
            raise SignatureError(f"Invalid signature: {e}")

    def parse_payload(self, body: str) -> TaskPayload:
        """Parse and validate webhook payload."""
        try:
            data = json.loads(body)
            return TaskPayload.from_dict(data)
        except json.JSONDecodeError as e:
            raise PayloadError(f"Invalid JSON payload: {e}")

    def execute_task(self, payload: TaskPayload) -> Any:
        """Import and execute the task function with timing metrics."""
        from django_qstash.signals import task_completed as task_completed_signal
        from django_qstash.signals import task_failed as task_failed_signal
        from django_qstash.signals import task_started as task_started_signal

        # Validate that the task is a registered @stashed_task
        registered_tasks = discover_tasks(locations_only=True)
        if payload.function_path not in registered_tasks:
            raise TaskError(
                f"Task '{payload.function_path}' is not a registered @stashed_task. "
                f"Only tasks decorated with @stashed_task can be executed via webhook."
            )

        try:
            task_func = utils.import_string(payload.function_path)
        except ImportError as e:
            raise TaskError(f"Could not import task function: {e}")

        current_correlation_id = correlation_id.get("")

        # Build log extra with optional args/kwargs
        log_extra: dict[str, Any] = {
            "task": payload.function_path,
            "correlation_id": current_correlation_id,
        }
        if DJANGO_QSTASH_LOG_TASK_ARGS:
            log_extra["args"] = payload.args
            log_extra["kwargs"] = payload.kwargs

        # Emit task_started signal
        _emit_signal(
            task_started_signal,
            task_name=payload.task_name,
            correlation_id=current_correlation_id,
            args=payload.args,
            kwargs=payload.kwargs,
        )

        start_time = time.perf_counter()
        try:
            if callable(task_func) and hasattr(task_func, "actual_func"):
                result = task_func.actual_func(*payload.args, **payload.kwargs)
            else:
                result = task_func(*payload.args, **payload.kwargs)

            duration = time.perf_counter() - start_time
            logger.info(
                "task_completed",
                extra={
                    **log_extra,
                    "duration_seconds": round(duration, 4),
                    "status": "success",
                },
            )

            # Emit task_completed signal
            _emit_signal(
                task_completed_signal,
                task_name=payload.task_name,
                correlation_id=current_correlation_id,
                duration=duration,
                result=result,
            )

            return result

        except Exception as e:
            duration = time.perf_counter() - start_time
            logger.exception(
                "task_failed",
                extra={
                    **log_extra,
                    "duration_seconds": round(duration, 4),
                    "status": "error",
                    "error_type": type(e).__name__,
                },
            )

            # Emit task_failed signal
            _emit_signal(
                task_failed_signal,
                task_name=payload.task_name,
                correlation_id=current_correlation_id,
                duration=duration,
                exception=e,
            )

            raise TaskError(f"Task execution failed: {e}")

    def _get_client_ip(self, request: HttpRequest) -> str:
        """Extract client IP from request headers."""
        x_forwarded_for = request.headers.get("x-forwarded-for")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "unknown")

    def handle_request(self, request: HttpRequest) -> tuple[dict, int]:
        """Process webhook request and return response data and status code."""
        from django_qstash.signals import webhook_received as webhook_received_signal

        payload = None
        task_id = request.headers.get("Upstash-Message-Id")
        content_length = len(request.body)
        source_ip = self._get_client_ip(request)

        # Set correlation ID from Upstash-Message-Id header for request tracing
        if task_id:
            correlation_id.set(task_id)

        try:
            # Check payload size before processing
            if content_length > DJANGO_QSTASH_MAX_PAYLOAD_SIZE:
                raise PayloadError(
                    f"Payload size {content_length} bytes exceeds maximum allowed "
                    f"size of {DJANGO_QSTASH_MAX_PAYLOAD_SIZE} bytes"
                )

            body = request.body.decode()
            self.verify_signature(
                body=body,
                signature=request.headers.get("Upstash-Signature"),
                url=request.build_absolute_uri(),
            )

            payload = self.parse_payload(body)

            # Audit log the webhook request
            audit_logger.info(
                "webhook_received",
                extra={
                    "message_id": task_id,
                    "source_ip": source_ip,
                    "task_path": payload.function_path,
                    "content_length": content_length,
                    "correlation_id": correlation_id.get(""),
                },
            )

            # Emit webhook_received signal
            _emit_signal(
                webhook_received_signal,
                message_id=task_id,
                task_path=payload.function_path,
                source_ip=source_ip,
            )

            result = self.execute_task(payload)
            store_task_result(
                task_id=task_id,
                task_name=payload.task_name,
                status=TaskStatus.SUCCESS,
                result=result,
                args=payload.args,
                kwargs=payload.kwargs,
                function_path=payload.function_path,
            )

            return {
                "status": "success",
                "task_name": payload.task_name,
                "result": result if result is not None else "null",
            }, 200

        except (SignatureError, PayloadError) as e:
            logger.exception("Authentication error: %s", str(e))
            return {
                "status": "error",
                "error_type": e.__class__.__name__,
                "error": str(e),
                "task_name": getattr(payload, "task_name", None),
            }, 400

        except TaskError as e:
            logger.exception("Task execution error: %s", str(e))
            store_task_result(
                task_id=task_id,
                task_name=payload.task_name,
                status=TaskStatus.EXECUTION_ERROR,
                traceback=str(e),
                args=payload.args,
                kwargs=payload.kwargs,
                function_path=payload.function_path,
            )
            return {
                "status": "error",
                "error_type": e.__class__.__name__,
                "error": str(e),
                "task_name": payload.task_name,
            }, 422

        except Exception as e:
            logger.exception("Unexpected error in webhook handler: %s", str(e))
            if payload:  # Store unexpected errors only if payload was parsed
                store_task_result(
                    task_id=task_id,
                    task_name=payload.task_name,
                    status=TaskStatus.INTERNAL_ERROR,
                    traceback=str(e),
                    args=payload.args,
                    kwargs=payload.kwargs,
                    function_path=payload.function_path,
                )
            return {
                "status": "error",
                "error_type": "InternalServerError",
                "error": "An unexpected error occurred",
                "task_name": getattr(payload, "task_name", None),
            }, 500
