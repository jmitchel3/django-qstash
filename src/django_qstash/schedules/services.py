from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from typing import cast

from django.db import transaction
from qstash.schedule import Schedule

from django_qstash.client import qstash_client
from django_qstash.schedules.formatters import format_task_schedule_for_qstash
from django_qstash.schedules.models import TaskSchedule

logger = logging.getLogger(__name__)

_remote_sync_suppressed: ContextVar[bool] = ContextVar(
    "django_qstash_schedule_remote_sync_suppressed", default=False
)


@contextmanager
def remote_sync_suppressed() -> Iterator[None]:
    """Save or delete ``TaskSchedule`` rows without writing to QStash.

    Inside this block the ``post_save``/``pre_delete`` receivers skip their
    QStash create/update/pause/resume/delete calls. Use it when the local row is
    being made to mirror QStash (for example, importing remote schedules), so
    the import does not rewrite the remote schedule.
    """
    token = _remote_sync_suppressed.set(True)
    try:
        yield
    finally:
        _remote_sync_suppressed.reset(token)


def is_remote_sync_suppressed() -> bool:
    return _remote_sync_suppressed.get()


@transaction.atomic
def sync_task_schedule_instance_to_qstash(instance: TaskSchedule) -> TaskSchedule:
    """Sync a task schedule to QStash.

    Creates a new schedule if none exists, handles pause/resume state changes,
    and updates existing schedules when active.
    """
    data = format_task_schedule_for_qstash(instance)
    schedule_id = qstash_client.schedule.create(**data)
    if not instance.schedule_id:
        TaskSchedule.objects.filter(id=instance.id).update(schedule_id=schedule_id)

    sync_state_changes(instance)

    return instance


def sync_state_changes(instance: TaskSchedule) -> None:
    """Handle pause/resume state changes."""
    if instance.did_just_resume():
        try:
            qstash_client.schedule.resume(cast(str, instance.schedule_id))
        except Exception:
            logger.exception("Failed to resume schedule %s", instance.schedule_id)
    elif instance.did_just_pause():
        try:
            qstash_client.schedule.pause(cast(str, instance.schedule_id))
        except Exception:
            logger.exception("Failed to pause schedule %s", instance.schedule_id)


def get_task_schedule_from_qstash(
    instance: TaskSchedule, as_dict: bool = False
) -> Schedule | dict[Any, Any] | None:
    """Get a schedule from QStash."""
    try:
        response = qstash_client.schedule.get(cast(str, instance.schedule_id))
    except Exception:
        logger.exception("Failed to lookup schedule %s", instance.schedule_id)
        return None
    # schedule.get always returns a Schedule (it raises on lookup failure).
    result: Schedule | dict[Any, Any] = response.__dict__ if as_dict else response
    return result


def delete_task_schedule_from_qstash(instance: TaskSchedule) -> None:
    """Delete a schedule from QStash."""
    try:
        qstash_client.schedule.delete(cast(str, instance.schedule_id))
    except Exception:
        logger.exception("Failed to delete schedule %s", instance.schedule_id)
    return


class ScheduleImportError(ValueError):
    """A remote schedule could not be mapped to a ``TaskSchedule``."""


def parse_remote_schedule_body(schedule: Any) -> dict[str, Any]:
    """Decode a remote schedule body written by django-qstash.

    Raises :class:`ScheduleImportError` for bodies that are not django-qstash
    task payloads (other applications' schedules, non-JSON bodies, and so on).
    """
    raw = getattr(schedule, "body", None)
    if not raw:
        raise ScheduleImportError("schedule has no body")
    try:
        body = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ScheduleImportError(f"body is not JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise ScheduleImportError("body is not a JSON object")
    module = body.get("module")
    function = body.get("function")
    if not isinstance(module, str) or not module:
        raise ScheduleImportError("body is missing 'module'")
    if not isinstance(function, str) or not function:
        raise ScheduleImportError("body is missing 'function'")
    args = body.get("args", [])
    kwargs = body.get("kwargs", {})
    if not isinstance(args, list):
        raise ScheduleImportError("body 'args' is not a list")
    if not isinstance(kwargs, dict):
        raise ScheduleImportError("body 'kwargs' is not an object")
    options = body.get("options") or {}
    if not isinstance(options, dict):
        raise ScheduleImportError("body 'options' is not an object")
    body["args"] = args
    body["kwargs"] = kwargs
    body["options"] = options
    return body


def _duration(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return f"{int(value)}s" if value else None
    return str(value)


def _header_map(value: Any, forward_prefix: str = "") -> dict[str, str] | None:
    if not value:
        return {} if value is not None else None
    if not isinstance(value, dict):
        return None
    result: dict[str, str] = {}
    for key, raw in value.items():
        name = str(key)
        if name.lower() == "content-type":
            continue
        if forward_prefix and name.lower().startswith(forward_prefix.lower()):
            name = name[len(forward_prefix) :]
        if isinstance(raw, (list, tuple)):
            result[name] = ",".join(str(item) for item in raw)
        else:
            result[name] = str(raw)
    return result


def _flow_control(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        source = value
    else:
        source = {
            name: getattr(value, name, None)
            for name in ("key", "parallelism", "rate", "period")
        }
    return {key: item for key, item in source.items() if item is not None}


def remote_schedule_to_fields(schedule: Any) -> dict[str, Any]:
    """Map a QStash ``Schedule`` to ``TaskSchedule`` field values.

    Only fields QStash reports are returned, so local values QStash cannot
    echo back (``redact``, for example) are left untouched on update. Values
    django-qstash wrote into the body ``options`` win over the remote
    attributes because they keep the original strings (``"5m"`` rather than
    ``300``).
    """
    body = parse_remote_schedule_body(schedule)
    options: dict[str, Any] = body["options"]
    function_path = f"{body['module']}.{body['function']}"

    fields: dict[str, Any] = {
        "name": body.get("task_name") or function_path,
        "task": function_path,
        "task_name": function_path,
        "cron": schedule.cron,
        "args": body["args"],
        "kwargs": body["kwargs"],
        "is_active": not bool(getattr(schedule, "paused", False)),
    }

    retries = getattr(schedule, "retries", None)
    if isinstance(retries, int) and not isinstance(retries, bool):
        fields["retries"] = retries

    timeout = _duration(options.get("timeout")) or _duration(
        getattr(schedule, "timeout", None)
    )
    if timeout:
        fields["timeout"] = timeout

    fields["delay"] = (
        _duration(options.get("delay"))
        or _duration(getattr(schedule, "delay", None))
        or ""
    )
    fields["retry_delay"] = str(
        options.get("retry_delay")
        or getattr(schedule, "retry_delay_expression", None)
        or ""
    )
    fields["queue"] = str(
        options.get("queue") or getattr(schedule, "queue", None) or ""
    )
    fields["label"] = str(
        options.get("label") or getattr(schedule, "label", None) or ""
    )
    fields["callback"] = str(getattr(schedule, "callback", None) or "")
    fields["failure_callback"] = str(getattr(schedule, "failure_callback", None) or "")

    for field, attr, prefix in (
        ("headers", "headers", "Upstash-Forward-"),
        ("callback_headers", "callback_headers", "Upstash-Callback-"),
        (
            "failure_callback_headers",
            "failure_callback_headers",
            "Upstash-Failure-Callback-",
        ),
    ):
        mapped = _header_map(getattr(schedule, attr, None), prefix)
        fields[field] = mapped if mapped is not None else {}

    fields["flow_control"] = _flow_control(getattr(schedule, "flow_control", None))

    return fields


def import_remote_schedule(schedule: Any) -> tuple[TaskSchedule, bool]:
    """Create or update the local ``TaskSchedule`` mirroring a QStash schedule.

    This is a remote-to-local import: it performs no QStash writes. Returns
    ``(instance, created)``. Raises :class:`ScheduleImportError` when the
    schedule is not a django-qstash task schedule.
    """
    fields = remote_schedule_to_fields(schedule)
    with remote_sync_suppressed(), transaction.atomic():
        return TaskSchedule.objects.update_or_create(
            schedule_id=schedule.schedule_id, defaults=fields
        )
