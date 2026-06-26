from __future__ import annotations

import json
from typing import Any

from django_qstash.callbacks import get_callback_url
from django_qstash.schedules.models import TaskSchedule

JSON_CONTENT_TYPE = "application/json"


def _compact_qstash_options(options: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in options.items()
        if value is not None
        and value != ""
        and not (isinstance(value, (dict, list, tuple)) and not value)
    }


def _task_options(instance: TaskSchedule) -> dict[str, Any]:
    return _compact_qstash_options(
        {
            "max_retries": instance.retries,
            "retry_delay": instance.retry_delay,
            "timeout": instance.timeout,
            "delay": instance.delay,
            "queue": instance.queue,
            "label": instance.label,
        }
    )


def prepare_qstash_payload(instance: TaskSchedule) -> dict[str, Any]:
    """Prepare the task payload for QStash"""
    return {
        "function": instance.task_name.split(".")[-1],  # Get function name
        "module": ".".join(instance.task_name.split(".")[:-1]),  # Get module path
        "args": instance.args,
        "kwargs": instance.kwargs,
        "task_name": instance.name,
        "options": _task_options(instance),
    }


def format_task_schedule_for_qstash(instance: TaskSchedule) -> dict[str, Any]:
    payload = prepare_qstash_payload(instance)
    callback_url = get_callback_url()
    data = {
        "destination": callback_url,
        "body": json.dumps(payload),
        "content_type": JSON_CONTENT_TYPE,
        "cron": instance.cron,
        "retries": instance.retries,
        "timeout": instance.timeout,
    }
    data.update(
        _compact_qstash_options(
            {
                "headers": instance.headers,
                "callback_headers": instance.callback_headers,
                "failure_callback_headers": instance.failure_callback_headers,
                "retry_delay": instance.retry_delay,
                "callback": instance.callback,
                "failure_callback": instance.failure_callback,
                "delay": instance.delay,
                "queue": instance.queue,
                "flow_control": instance.flow_control,
                "label": instance.label,
                "redact": instance.redact,
            }
        )
    )
    if instance.schedule_id:
        data["schedule_id"] = instance.schedule_id
    return data
