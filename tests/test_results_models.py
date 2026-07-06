from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from django.utils import timezone

from django_qstash.results.models import TaskResult


@pytest.mark.django_db(transaction=True)
class TestTaskResult:
    def test_create_task_result(self):
        task_result = TaskResult.objects.create(
            task_id="test-task-123",
            task_name="test_module.test_function",
        )

        assert isinstance(task_result.id, uuid.UUID)
        assert task_result.task_id == "test-task-123"
        assert task_result.task_name == "test_module.test_function"
        assert task_result.status == "PENDING"
        assert isinstance(task_result.date_created, datetime)
        assert task_result.date_done is None
        assert task_result.result is None
        assert task_result.traceback is None
        assert task_result.args is None
        assert task_result.kwargs is None
        assert task_result.correlation_id == ""
        assert task_result.parent_task_id == ""
        assert task_result.attempt == 0
        assert task_result.duration_ms is None
        assert task_result.duration_seconds is None

    def test_str_representation(self):
        task_result = TaskResult.objects.create(
            task_id="test-task-123",
            task_name="test_module.test_function",
        )

        assert str(task_result) == "test_module.test_function (test-task-123)"

    def test_task_result_with_all_fields(self):
        task_result = TaskResult.objects.create(
            task_id="test-task-456",
            task_name="test_module.other_function",
            status="SUCCESS",
            date_done=timezone.now(),
            result={"success": True},
            traceback="No errors",
            args=[1, 2, 3],
            kwargs={"key": "value"},
            correlation_id="root-456",
            parent_task_id="test-task-123",
            attempt=2,
            duration_ms=1500,
        )

        assert task_result.status == "SUCCESS"
        assert isinstance(task_result.date_done, datetime)
        assert task_result.result == {"success": True}
        assert task_result.traceback == "No errors"
        assert task_result.args == [1, 2, 3]
        assert task_result.kwargs == {"key": "value"}
        assert task_result.correlation_id == "root-456"
        assert task_result.parent_task_id == "test-task-123"
        assert task_result.attempt == 2
        assert task_result.duration_seconds == 1.5

    def test_ordering(self):
        # Create tasks with different completion dates
        older_task = TaskResult.objects.create(
            task_id="older-task",
            task_name="test.older",
            status="SUCCESS",
            date_done=timezone.now(),
        )
        newer_task = TaskResult.objects.create(
            task_id="newer-task",
            task_name="test.newer",
            status="SUCCESS",
            date_done=timezone.now(),
        )

        # Get all tasks and verify ordering
        tasks = TaskResult.objects.all()
        assert tasks[0].task_id == newer_task.task_id
        assert tasks[1].task_id == older_task.task_id
