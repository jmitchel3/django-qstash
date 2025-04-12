from __future__ import annotations

from datetime import timedelta
from io import StringIO

import pytest
from django.utils import timezone

from django_qstash.db.models import TaskStatus
from django_qstash.results.models import TaskResult
from django_qstash.results.tasks import DJANGO_QSTASH_RESULT_TTL
from django_qstash.results.tasks import clear_stale_results_task
from django_qstash.results.tasks import clear_task_errors_task


@pytest.fixture
def create_task_result():
    def _create_task_result(task_id, age=None, status=TaskStatus.SUCCESS):
        date_done = timezone.now()
        if age:
            if isinstance(age, int | float):
                date_done -= timedelta(seconds=age)
            else:
                date_done -= age

        return TaskResult.objects.create(
            task_id=task_id,
            task_name=f"test.{task_id}",
            status=status,
            date_done=date_done,
        )

    return _create_task_result


@pytest.fixture
def stdout():
    return StringIO()


@pytest.mark.django_db
class TestClearStaleResults:
    def test_clear_stale_results_basic(self):
        # Create a stale task result (older than default 7 days)
        stale_date = timezone.now() - timedelta(days=8)
        TaskResult.objects.create(
            task_id="stale-task",
            task_name="test.stale",
            status=TaskStatus.SUCCESS,
            date_done=stale_date,
        )

        # Create a recent task result
        recent_task = TaskResult.objects.create(
            task_id="recent-task",
            task_name="test.recent",
            status=TaskStatus.SUCCESS,
            date_done=timezone.now(),
        )

        # Run the task directly instead of management command
        stdout = StringIO()
        clear_stale_results_task(stdout=stdout)

        # Verify output message
        output = stdout.getvalue()
        assert "Successfully deleted 1 stale results" in output

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
            status=TaskStatus.SUCCESS,
            date_done=four_hours_old,
        )

        # Create a task result that's 2 hours old
        two_hours_old = timezone.now() - timedelta(hours=2)
        newer_task = TaskResult.objects.create(
            task_id="newer-task",
            task_name="test.newer",
            status=TaskStatus.SUCCESS,
            date_done=two_hours_old,
        )

        # Run the task directly with custom since
        stdout = StringIO()
        clear_stale_results_task(since=10800, stdout=stdout)

        # Verify output message
        output = stdout.getvalue()
        assert "Successfully deleted 1 stale results" in output

        # Verify that only the 4-hour-old task was deleted
        remaining_tasks = TaskResult.objects.all()
        assert len(remaining_tasks) == 1
        assert remaining_tasks[0].task_id == newer_task.task_id

    @pytest.mark.parametrize(
        "status",
        [
            TaskStatus.SUCCESS,
            TaskStatus.PENDING,
            TaskStatus.UNKNOWN,
        ],
    )
    def test_clear_stale_results_different_statuses(
        self, create_task_result, stdout, status
    ):
        # Create one stale task with the given status
        create_task_result(f"stale-task-{status}", age=timedelta(days=8), status=status)
        create_task_result("recent-task")  # Create a recent task

        clear_stale_results_task(stdout=stdout)

        output = stdout.getvalue()
        assert "Successfully deleted 1 stale results" in output
        assert TaskResult.objects.count() == 1
        assert TaskResult.objects.first().task_id == "recent-task"

    @pytest.mark.parametrize(
        "status",
        [
            TaskStatus.EXECUTION_ERROR,
            TaskStatus.INTERNAL_ERROR,
            TaskStatus.OTHER_ERROR,
        ],
    )
    def test_clear_stale_error_different_statuses(
        self, create_task_result, stdout, status
    ):
        # Create one stale task with the given status
        create_task_result(f"stale-task-{status}", age=timedelta(days=8), status=status)
        create_task_result("recent-task")  # Create a recent task

        clear_task_errors_task(stdout=stdout)

        output = stdout.getvalue()
        assert "Successfully deleted 1 stale results" in output
        assert TaskResult.objects.count() == 1
        assert TaskResult.objects.first().task_id == "recent-task"

    def test_clear_stale_results_error_handling(
        self, create_task_result, stdout, monkeypatch
    ):
        create_task_result("stale-task", age=timedelta(days=8))

        # Mock the queryset's delete method to raise an exception
        def mock_filter(*args, **kwargs):
            class MockQuerySet:
                def delete(self):
                    raise Exception("Test error")

                def exists(self):
                    return True

                def count(self):
                    return 1

                def exclude(self, **kwargs):
                    assert kwargs == {
                        "status__in": [
                            TaskStatus.EXECUTION_ERROR,
                            TaskStatus.INTERNAL_ERROR,
                            TaskStatus.OTHER_ERROR,
                        ]
                    }
                    return self

            return MockQuerySet()

        monkeypatch.setattr(
            "django_qstash.results.models.TaskResult.objects.filter", mock_filter
        )

        with pytest.raises(Exception) as exc_info:
            clear_stale_results_task(stdout=stdout)

        assert str(exc_info.value) == "Test error"
        assert "Error deleting stale results: Test error" in stdout.getvalue()

    def test_clear_stale_results_exact_ttl_boundary(self, create_task_result, stdout):
        # Create tasks right at the TTL boundary
        create_task_result("boundary-task", age=DJANGO_QSTASH_RESULT_TTL)
        create_task_result("just-under-task", age=DJANGO_QSTASH_RESULT_TTL - 1)

        clear_stale_results_task(stdout=stdout)

        assert TaskResult.objects.count() == 1
        assert TaskResult.objects.first().task_id == "just-under-task"

    @pytest.mark.parametrize(
        "user_input,expected_count",
        [
            ("y", 0),
            ("Y", 0),
            ("n", 1),
            ("N", 1),
            ("", 1),
        ],
    )
    def test_clear_stale_results_user_confirmation_variations(
        self, create_task_result, stdout, monkeypatch, user_input, expected_count
    ):
        create_task_result("stale-task", age=timedelta(days=8))
        monkeypatch.setattr("builtins.input", lambda _: user_input)

        clear_stale_results_task(stdout=stdout, user_confirm=True)

        assert TaskResult.objects.count() == expected_count

    def test_clear_stale_results_no_results(self):
        stdout = StringIO()
        clear_stale_results_task(stdout=stdout)

        assert "No stale Django QStash task results found" in stdout.getvalue()
