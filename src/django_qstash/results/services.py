from __future__ import annotations

import json
import logging
import math
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.apps import apps
from django.db.models import Count
from django.db.models import Model
from django.db.models import Q
from django.utils import timezone

from django_qstash.callbacks import get_callback_url
from django_qstash.client import qstash_client
from django_qstash.db.models import TaskStatus

logger = logging.getLogger(__name__)

REQUEUEABLE_STATUSES = frozenset(
    {
        TaskStatus.EXECUTION_ERROR,
        TaskStatus.INTERNAL_ERROR,
        TaskStatus.OTHER_ERROR,
        TaskStatus.UNKNOWN,
    }
)


@dataclass(frozen=True)
class RequeueResult:
    message_id: str
    correlation_id: str
    parent_task_id: str


def duration_to_ms(duration_seconds: float | None) -> int | None:
    """Convert a duration in seconds to rounded milliseconds."""
    if duration_seconds is None:
        return None
    return max(0, round(duration_seconds * 1000))


def function_result_to_dict(result: Any) -> dict[str, Any] | None:
    """
    Convert a task result to a Python dict for the result JSONField.

    Args:
        result: Any Python value to be converted

    Returns:
        dict: A dictionary representation of the result
        None: If the input is None
    """
    if result is None:
        return None
    elif isinstance(result, dict):
        return result
    elif isinstance(result, str):
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                return parsed
            return {"result": parsed}
        except json.JSONDecodeError as e:
            logger.info("Task result is not a JSON string: %s", str(e))
            return {"result": result}
    return {"result": result}


def successful_result_exists(task_id: str | None) -> bool:
    """Return True if a SUCCESS TaskResult already exists for this message id.

    Used by the webhook handler to make redelivery idempotent: QStash is
    at-least-once, so the same message (same ``task_id``) can arrive more than
    once. If a prior attempt already succeeded, the task should not run again.

    Returns False when ``task_id`` is missing or the results app is not
    installed (in which case no dedup is possible).
    """
    if not task_id:
        return False
    try:
        TaskResult = apps.get_model("django_qstash_results", "TaskResult")
    except LookupError:
        return False
    return bool(
        TaskResult.objects.filter(task_id=task_id, status=TaskStatus.SUCCESS).exists()
    )


def store_task_result(
    task_id: str | None,
    task_name: str,
    status: str,
    result: Any = None,
    traceback: str | None = None,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    error: str | None = None,
    function_path: str | None = None,
    correlation_id: str = "",
    parent_task_id: str = "",
    attempt: int = 0,
    duration_ms: int | None = None,
) -> Model | None:
    """
    Store task result if the results app is installed.

    Args:
        task_id: QStash message ID for the task
        task_name: Human-readable name of the task
        status: Task execution status (from TaskStatus enum)
        result: Task return value (optional)
        traceback: Error traceback string (optional)
        args: Positional arguments passed to the task
        kwargs: Keyword arguments passed to the task
        error: Error message string (optional, deprecated - use traceback)
        function_path: Full dotted path to the task function
        correlation_id: Stable root id shared by retries and linked tasks
        parent_task_id: Message id that scheduled this task, when any
        attempt: Zero-based retry attempt number for this task lifecycle
        duration_ms: Execution duration in milliseconds

    Returns:
        TaskResult model instance if created, None if results app not installed
    """
    if status not in TaskStatus.values:
        status = TaskStatus.UNKNOWN

    try:
        TaskResult = apps.get_model("django_qstash_results", "TaskResult")
        task_result: Model = TaskResult.objects.create(
            task_id=task_id or "",
            task_name=task_name,
            status=status,
            date_done=timezone.now(),
            result=function_result_to_dict(result),
            traceback=traceback,
            args=args,
            kwargs=kwargs,
            function_path=function_path,
            correlation_id=correlation_id,
            parent_task_id=parent_task_id,
            attempt=max(0, attempt),
            duration_ms=duration_ms,
        )
        return task_result
    except LookupError:
        # Model isn't installed, skip storage
        logger.debug(
            "Django QStash Results not installed. Add `django_qstash.results` to INSTALLED_APPS and run migrations."
        )
        return None


def _empty_metrics(
    *,
    window_seconds: int,
    since: Any,
    until: Any,
) -> dict[str, Any]:
    return {
        "window_seconds": window_seconds,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "total": 0,
        "counts_by_status": {},
        "success_rate": 0.0,
        "duration_ms": {
            "p50": None,
            "p95": None,
        },
    }


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil((percentile / 100) * len(ordered)) - 1)
    return ordered[index]


def calculate_task_metrics(
    *,
    window_seconds: int = 3600,
    now: Any = None,
) -> dict[str, Any]:
    """Return lightweight TaskResult aggregates for a recent time window."""
    until = now or timezone.now()
    since = until - timedelta(seconds=window_seconds)

    try:
        TaskResult = apps.get_model("django_qstash_results", "TaskResult")
    except LookupError:
        return _empty_metrics(
            window_seconds=window_seconds,
            since=since,
            until=until,
        )

    queryset = TaskResult.objects.filter(date_done__gte=since, date_done__lte=until)
    counts_by_status = {
        row["status"]: row["count"]
        for row in queryset.values("status").annotate(count=Count("id"))
    }
    total = sum(counts_by_status.values())
    successes = counts_by_status.get(TaskStatus.SUCCESS, 0)
    durations = [
        value
        for value in queryset.exclude(duration_ms__isnull=True).values_list(
            "duration_ms", flat=True
        )
        if value is not None
    ]

    return {
        "window_seconds": window_seconds,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "total": total,
        "counts_by_status": counts_by_status,
        "success_rate": round(successes / total, 4) if total else 0.0,
        "duration_ms": {
            "p50": _percentile(durations, 50),
            "p95": _percentile(durations, 95),
        },
    }


def _split_function_path(function_path: str | None) -> tuple[str, str]:
    if not function_path or "." not in function_path:
        raise ValueError("TaskResult has no importable function_path to requeue")
    module, function = function_path.rsplit(".", 1)
    return module, function


def _publish_payload(
    payload: dict[str, Any],
    *,
    queue: str | None = None,
    url: str | None = None,
    delivery_options: dict[str, Any] | None = None,
) -> RequeueResult:
    target_url = url or get_callback_url()
    options = delivery_options or {}
    response: Any
    if queue:
        response = qstash_client.message.enqueue_json(
            queue=queue,
            url=target_url,
            body=payload,
            **options,
        )
    else:
        response = qstash_client.message.publish_json(
            url=target_url, body=payload, **options
        )
    message_id = str(getattr(response, "message_id", ""))
    if not message_id:
        raise ValueError("QStash did not return a message id for the requeued task")
    return RequeueResult(
        message_id=message_id,
        correlation_id=str(payload.get("correlation_id") or message_id),
        parent_task_id=str(payload.get("parent_task_id") or ""),
    )


def build_requeue_payload(task_result: Any) -> dict[str, Any]:
    """Build a QStash task payload from a failed TaskResult row."""
    module, function = _split_function_path(getattr(task_result, "function_path", None))
    parent_task_id = str(getattr(task_result, "task_id", "") or "")
    correlation_id = str(
        getattr(task_result, "correlation_id", "")
        or parent_task_id
        or getattr(task_result, "id", "")
    )
    attempt = int(getattr(task_result, "attempt", 0) or 0) + 1
    return {
        "function": function,
        "module": module,
        "args": getattr(task_result, "args", None) or [],
        "kwargs": getattr(task_result, "kwargs", None) or {},
        "task_name": getattr(task_result, "task_name", None) or f"{module}.{function}",
        "correlation_id": correlation_id,
        "parent_task_id": parent_task_id,
        "attempt": attempt,
    }


def requeue_task_result(
    task_result: Any,
    *,
    queue: str | None = None,
    force: bool = False,
) -> RequeueResult:
    """Re-dispatch a failed TaskResult row as a new QStash message."""
    status = getattr(task_result, "status", "")
    if not force and status not in REQUEUEABLE_STATUSES:
        raise ValueError(f"TaskResult with status {status!r} is not requeueable")
    return _publish_payload(build_requeue_payload(task_result), queue=queue)


def requeue_task_result_by_id(
    identifier: str,
    *,
    queue: str | None = None,
    force: bool = False,
) -> RequeueResult:
    """Find a TaskResult by UUID primary key or QStash task_id and requeue it."""
    TaskResult = apps.get_model("django_qstash_results", "TaskResult")
    query = Q(task_id=identifier)
    try:
        query = query | Q(id=uuid.UUID(identifier))
    except ValueError:
        pass
    task_result = (
        TaskResult.objects.filter(query).order_by("-date_done", "-date_created").first()
    )
    if task_result is None:
        raise ValueError(f"No TaskResult found for {identifier!r}")
    return requeue_task_result(task_result, queue=queue, force=force)


def _coerce_dlq_body(body: Any) -> dict[str, Any]:
    if isinstance(body, bytes):
        body = body.decode()
    if isinstance(body, str):
        data = json.loads(body)
    elif isinstance(body, dict):
        data = dict(body)
    else:
        raise ValueError("DLQ message body is not a JSON object")
    if not isinstance(data, dict):
        raise ValueError("DLQ message body is not a JSON object")
    return data


def build_dlq_requeue_payload(message: Any) -> dict[str, Any]:
    """Build a requeue payload from a QStash DLQ message object."""
    payload = _coerce_dlq_body(getattr(message, "body", None))
    parent_task_id = str(getattr(message, "message_id", "") or "")
    correlation_id = str(payload.get("correlation_id") or parent_task_id)
    # self.retry() writes "retries", while manual requeues historically wrote
    # only "attempt". Keep both names in sync so the webhook cannot prefer a
    # stale counter, and retain the highest known count in older mixed bodies.
    attempt = (
        max(int(payload.get("retries") or 0), int(payload.get("attempt") or 0), 0) + 1
    )
    payload["correlation_id"] = correlation_id
    payload["parent_task_id"] = parent_task_id
    payload["attempt"] = attempt
    payload["retries"] = attempt
    return payload


def _dlq_delivery_options(
    message: Any, payload: dict[str, Any], *, queue: str | None
) -> dict[str, Any]:
    """Keep delivery controls while starting a fresh, immediate delivery.

    QStash returns header values as lists, whereas publishing accepts strings.
    Its DLQ model does not expose timeout or redaction, so those can only be
    recovered when django-qstash recorded them in the task body's options.
    Original scheduling and deduplication settings are deliberately not reused.
    """
    options: dict[str, Any] = {}
    for name, attr in (
        ("method", "method"),
        ("retry_delay", "retry_delay_expression"),
        ("callback", "callback"),
        ("failure_callback", "failure_callback"),
        ("label", "label"),
    ):
        value = getattr(message, attr, None)
        if isinstance(value, str) and value:
            options[name] = value

    retries = getattr(message, "max_retries", None)
    if isinstance(retries, int) and not isinstance(retries, bool):
        options["retries"] = retries

    for name in ("headers", "callback_headers", "failure_callback_headers"):
        headers = getattr(message, name, None)
        if isinstance(headers, dict):
            options[name] = {
                str(key): (
                    ",".join(str(item) for item in value)
                    if isinstance(value, (list, tuple))
                    else str(value)
                )
                for key, value in headers.items()
            }

    # enqueue_json does not support flow_control; queue settings govern queued
    # deliveries, including when the caller explicitly selects a new queue.
    flow_control = getattr(message, "flow_control", None)
    if not queue and flow_control is not None:
        fields = ("key", "parallelism", "rate", "period")
        values = {
            name: (
                flow_control.get(name)
                if isinstance(flow_control, dict)
                else getattr(flow_control, name, None)
            )
            for name in fields
        }
        if isinstance(values["key"], str) and values["key"]:
            options["flow_control"] = {
                name: value for name, value in values.items() if value is not None
            }

    recorded = payload.get("options")
    if isinstance(recorded, dict):
        timeout = recorded.get("timeout")
        if isinstance(timeout, (str, int)) and not isinstance(timeout, bool):
            options["timeout"] = timeout
        redact = recorded.get("redact")
        if isinstance(redact, dict):
            options["redact"] = dict(redact)
    return options


def requeue_dlq_message(
    dlq_id: str,
    *,
    delete_after_requeue: bool = False,
    queue: str | None = None,
) -> RequeueResult:
    """Re-publish a DLQ task with its delivery controls and optionally delete it.

    The original queue is retained unless ``queue`` is supplied. Passing an
    empty string explicitly switches a queued message to direct publishing.
    """
    message = qstash_client.dlq.get(dlq_id)
    payload = build_dlq_requeue_payload(message)
    if queue is None:
        original_queue = getattr(message, "queue", None)
        queue = original_queue if isinstance(original_queue, str) else None
    result = _publish_payload(
        payload,
        queue=queue,
        url=getattr(message, "url", None),
        delivery_options=_dlq_delivery_options(message, payload, queue=queue),
    )
    if delete_after_requeue:
        qstash_client.dlq.delete(dlq_id)
    return result
