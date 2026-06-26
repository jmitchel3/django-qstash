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
        task_schedule.retry_delay = "1000 * (1 + retried)"
        task_schedule.delay = "10m"
        task_schedule.queue = "emails"
        task_schedule.label = "scheduled,email"
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
            "retry_delay": "1000 * (1 + retried)",
            "timeout": "30s",
            "delay": "10m",
            "queue": "emails",
            "label": "scheduled,email",
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
        task_schedule.retry_delay = "1000"
        task_schedule.delay = "5m"
        task_schedule.queue = "emails"
        task_schedule.headers = {"X-Trace-Id": "abc"}
        task_schedule.callback = "https://example.com/qstash/callback/"
        task_schedule.callback_headers = {"X-Callback": "yes"}
        task_schedule.failure_callback = "https://example.com/qstash/failure/"
        task_schedule.failure_callback_headers = {"X-Failure": "yes"}
        task_schedule.flow_control = {"key": "emails", "parallelism": 1}
        task_schedule.label = "scheduled,email"
        task_schedule.redact = {"body": True}
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
        assert data["retry_delay"] == "1000"
        assert data["delay"] == "5m"
        assert data["queue"] == "emails"
        assert data["headers"] == {"X-Trace-Id": "abc"}
        assert data["callback"] == "https://example.com/qstash/callback/"
        assert data["callback_headers"] == {"X-Callback": "yes"}
        assert data["failure_callback"] == "https://example.com/qstash/failure/"
        assert data["failure_callback_headers"] == {"X-Failure": "yes"}
        assert data["flow_control"] == {"key": "emails", "parallelism": 1}
        assert data["label"] == "scheduled,email"
        assert data["redact"] == {"body": True}
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

    def test_format_task_schedule_omits_empty_qstash_options(
        self, task_schedule: TaskSchedule
    ):
        data = format_task_schedule_for_qstash(task_schedule)

        for field in [
            "retry_delay",
            "delay",
            "queue",
            "headers",
            "callback",
            "callback_headers",
            "failure_callback",
            "failure_callback_headers",
            "flow_control",
            "label",
            "redact",
        ]:
            assert field not in data
