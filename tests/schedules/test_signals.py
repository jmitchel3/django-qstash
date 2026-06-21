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
