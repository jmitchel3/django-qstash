from __future__ import annotations

import logging
from typing import Any
from typing import cast

from django.db import transaction
from qstash.schedule import Schedule

from django_qstash.client import qstash_client
from django_qstash.schedules.formatters import format_task_schedule_for_qstash
from django_qstash.schedules.models import TaskSchedule

logger = logging.getLogger(__name__)


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
