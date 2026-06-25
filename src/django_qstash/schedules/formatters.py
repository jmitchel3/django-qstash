from __future__ import annotations

import json
from typing import Any

from django_qstash.callbacks import get_callback_url
from django_qstash.schedules.models import TaskSchedule

JSON_CONTENT_TYPE = "application/json"


def prepare_qstash_payload(instance: TaskSchedule) -> dict[str, Any]:
    """Prepare the task payload for QStash"""
    return {
        "function": instance.task_name.split(".")[-1],  # Get function name
        "module": ".".join(instance.task_name.split(".")[:-1]),  # Get module path
        "args": instance.args,
        "kwargs": instance.kwargs,
        "task_name": instance.name,
        "options": {
            "max_retries": instance.retries,
            "timeout": instance.timeout,
        },
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
    if instance.schedule_id:
        data["schedule_id"] = instance.schedule_id
    return data
