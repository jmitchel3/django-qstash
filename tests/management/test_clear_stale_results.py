from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from django_qstash.results.models import TaskResult


@pytest.mark.django_db
class TestClearStaleResults:
    def test_clear_stale_results_basic(self):
        # Create a stale task result (older than default 7 days)
        stale_date = timezone.now() - timedelta(days=8)
        TaskResult.objects.create(
            task_id="stale-task",
            task_name="test.stale",
            status="SUCCESS",
            date_done=stale_date,
        )

        # Create a recent task result
        recent_task = TaskResult.objects.create(
            task_id="recent-task",
            task_name="test.recent",
            status="SUCCESS",
            date_done=timezone.now(),
        )

        # Run the management command
        call_command("clear_stale_results", "--no-input")

        # Verify that only the stale task was deleted
        remaining_tasks = TaskResult.objects.all()
        assert len(remaining_tasks) == 1
        assert remaining_tasks[0].task_id == recent_task.task_id

    def test_clear_stale_results_custom_since(self):
        # Create a task result that's 4 hours old
        four_hours_old = timezone.now() - timedelta(hours=4)
        TaskResult.objects.create(
            task_id="older-task",
            task_name="test.older",
            status="SUCCESS",
            date_done=four_hours_old,
        )

        # Create a task result that's 2 hours old
        two_hours_old = timezone.now() - timedelta(hours=2)
        newer_task = TaskResult.objects.create(
            task_id="newer-task",
            task_name="test.newer",
            status="SUCCESS",
            date_done=two_hours_old,
        )

        # Run the command with 3-hour threshold (10800 seconds)
        call_command("clear_stale_results", "--since=10800", "--no-input")

        # Verify that only the 4-hour-old task was deleted
        remaining_tasks = TaskResult.objects.all()
        assert len(remaining_tasks) == 1
        assert remaining_tasks[0].task_id == newer_task.task_id

    def test_clear_stale_results_different_statuses(self):
        stale_date = timezone.now() - timedelta(days=8)

        # Create stale tasks with different statuses
        for status in ["SUCCESS", "FAILURE", "PENDING", "STARTED"]:
            TaskResult.objects.create(
                task_id=f"stale-task-{status}",
                task_name=f"test.stale.{status.lower()}",
                status=status,
                date_done=stale_date,
            )
        # Create a recent task
        recent_task = TaskResult.objects.create(
            task_id="recent-task",
            task_name="test.recent",
            status="SUCCESS",
            date_done=timezone.now(),
        )

        # Run the management command
        call_command("clear_stale_results", "--no-input")

        # Verify that all stale tasks were deleted regardless of status
        remaining_tasks = TaskResult.objects.all()
        assert len(remaining_tasks) == 1
        assert remaining_tasks[0].task_id == recent_task.task_id

    def test_clear_stale_results_delay_offloads_to_qstash(self):
        """The --delay flag offloads the work via the task's delay()."""
        with patch(
            "django_qstash.results.tasks.clear_stale_results_task.delay"
        ) as mock_delay:
            call_command("clear_stale_results", "--no-input", "--delay")

        mock_delay.assert_called_once()
        assert mock_delay.call_args[1]["user_confirm"] is False
