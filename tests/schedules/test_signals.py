from __future__ import annotations

from unittest.mock import patch

import pytest

from django_qstash.schedules import signals
from django_qstash.schedules.models import TaskSchedule


@pytest.mark.django_db
def test_sync_receiver_delegates_to_service(task_schedule):
    with patch(
        "django_qstash.schedules.signals.services.sync_task_schedule_instance_to_qstash"
    ) as mock_sync:
        signals.sync_schedule_to_qstash_receiver(
            TaskSchedule, task_schedule, created=True
        )
        mock_sync.assert_called_once_with(task_schedule)


@pytest.mark.django_db
def test_delete_receiver_delegates_to_service(task_schedule):
    with patch(
        "django_qstash.schedules.signals.services.delete_task_schedule_from_qstash"
    ) as mock_delete:
        signals.delete_schedule_from_qstash_receiver(TaskSchedule, task_schedule)
        mock_delete.assert_called_once_with(task_schedule)


@pytest.mark.django_db
def test_remote_sync_suppressed_skips_save_and_delete_receivers():
    from django_qstash.schedules import services

    obj = TaskSchedule.objects.create(
        name="x", task="myapp.tasks.sample_task", schedule_id="s1"
    )
    with (
        patch.object(services, "sync_task_schedule_instance_to_qstash") as sync,
        patch.object(services, "delete_task_schedule_from_qstash") as delete,
    ):
        with services.remote_sync_suppressed():
            assert services.is_remote_sync_suppressed()
            signals.sync_schedule_to_qstash_receiver(TaskSchedule, obj, created=False)
            signals.delete_schedule_from_qstash_receiver(TaskSchedule, obj)
        assert not services.is_remote_sync_suppressed()
        sync.assert_not_called()
        delete.assert_not_called()

        signals.sync_schedule_to_qstash_receiver(TaskSchedule, obj, created=False)
        signals.delete_schedule_from_qstash_receiver(TaskSchedule, obj)
        sync.assert_called_once_with(obj)
        delete.assert_called_once_with(obj)
