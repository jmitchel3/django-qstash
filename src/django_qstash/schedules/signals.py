from __future__ import annotations

from typing import Any

from django.db.models.signals import post_save
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from django_qstash.schedules import services
from django_qstash.schedules.models import TaskSchedule


@receiver(post_save, sender=TaskSchedule)
def sync_schedule_to_qstash_receiver(
    sender: type[TaskSchedule],
    instance: TaskSchedule,
    created: bool,
    **kwargs: Any,
) -> None:
    """
    Sync the django-qstash TaskSchedule to QStash on save.
    """
    services.sync_task_schedule_instance_to_qstash(instance)


@receiver(pre_delete, sender=TaskSchedule)
def delete_schedule_from_qstash_receiver(
    sender: type[TaskSchedule],
    instance: TaskSchedule,
    **kwargs: Any,
) -> None:
    services.delete_task_schedule_from_qstash(instance)
