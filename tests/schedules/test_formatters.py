from __future__ import annotations

import json

import pytest

from django_qstash.callbacks import get_callback_url
from django_qstash.schedules.formatters import format_task_schedule_for_qstash
from django_qstash.schedules.formatters import prepare_qstash_payload
from django_qstash.schedules.models import TaskSchedule


@pytest.mark.django_db
class TestFormatters:
    def test_prepare_qstash_payload(self, task_schedule: TaskSchedule):
        """Test preparing task payload for QStash"""
        # Setup a task schedule
        task_schedule.task_name = "myapp.tasks.sample_task"
        task_schedule.args = [1, 2, 3]
        task_schedule.kwargs = {"key": "value"}
        task_schedule.name = "Test Task"
        task_schedule.retries = 3
        task_schedule.timeout = "30s"
        task_schedule.save()

        # Get payload
        payload = prepare_qstash_payload(task_schedule)

        # Verify payload structure
        assert payload["function"] == "sample_task"
        assert payload["module"] == "myapp.tasks"
        assert payload["args"] == [1, 2, 3]
        assert payload["kwargs"] == {"key": "value"}
        assert payload["task_name"] == "Test Task"
        assert payload["options"] == {
            "max_retries": 3,
            "timeout": "30s",
        }

    def test_format_task_schedule_for_qstash(self, task_schedule: TaskSchedule):
        """Test formatting complete task schedule for QStash"""
        # Setup a task schedule
        task_schedule.task_name = "myapp.tasks.sample_task"
        task_schedule.args = [1, 2, 3]
        task_schedule.kwargs = {"key": "value"}
        task_schedule.name = "Test Task"
        task_schedule.cron = "*/10 * * * *"
        task_schedule.retries = 3
        task_schedule.timeout = "30s"
        task_schedule.schedule_id = "test-schedule-id"
        task_schedule.save()

        # Get formatted data
        data = format_task_schedule_for_qstash(task_schedule)

        # Verify data structure
        assert data["destination"] == get_callback_url()
        assert data["content_type"] == "application/json"
        assert data["cron"] == "*/10 * * * *"
        assert data["retries"] == 3
        assert data["timeout"] == "30s"
        assert data["schedule_id"] == "test-schedule-id"

        # Verify payload in body
        body = json.loads(data["body"])
        assert body["function"] == "sample_task"
        assert body["module"] == "myapp.tasks"
        assert body["args"] == [1, 2, 3]
        assert body["kwargs"] == {"key": "value"}

    def test_format_task_schedule_without_schedule_id(
        self, task_schedule: TaskSchedule
    ):
        """Test formatting task schedule without schedule_id"""
        # Setup a task schedule without schedule_id
        task_schedule.schedule_id = None
        task_schedule.save()

        data = format_task_schedule_for_qstash(task_schedule)

        # Verify schedule_id is not in data
        assert "schedule_id" not in data
