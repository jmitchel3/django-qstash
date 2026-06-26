from __future__ import annotations

from unittest.mock import patch

import pytest
from qstash.schedule import Schedule

from django_qstash.schedules.services import delete_task_schedule_from_qstash
from django_qstash.schedules.services import get_task_schedule_from_qstash
from django_qstash.schedules.services import sync_state_changes
from django_qstash.schedules.services import sync_task_schedule_instance_to_qstash


@pytest.mark.django_db
def test_sync_task_schedule_instance_to_qstash(task_schedule):
    """Test syncing a task schedule to QStash"""
    task_schedule.queue = "emails"
    task_schedule.retry_delay = "1000"
    task_schedule.save()

    with patch(
        "django_qstash.schedules.services.qstash_client.schedule.create"
    ) as mock_create:
        # Configure mock to return a schedule ID
        mock_create.return_value = "test-schedule-id"

        result = sync_task_schedule_instance_to_qstash(task_schedule)

        mock_create.assert_called_once()  # Verify the mock was called
        assert mock_create.call_args.kwargs["queue"] == "emails"
        assert mock_create.call_args.kwargs["retry_delay"] == "1000"
        assert result == task_schedule


@pytest.mark.django_db
def test_sync_state_changes_resume(task_schedule):
    """Test syncing state changes when resuming"""
    with (
        patch(
            "django_qstash.schedules.services.qstash_client.schedule.resume"
        ) as mock_resume,
        patch.object(task_schedule, "did_just_resume", return_value=True),
        patch.object(task_schedule, "did_just_pause", return_value=False),
    ):
        sync_state_changes(task_schedule)
        mock_resume.assert_called_once_with(task_schedule.schedule_id)


@pytest.mark.django_db
def test_sync_state_changes_pause(task_schedule):
    """Test syncing state changes when pausing"""
    with (
        patch(
            "django_qstash.schedules.services.qstash_client.schedule.pause"
        ) as mock_pause,
        patch.object(task_schedule, "did_just_resume", return_value=False),
        patch.object(task_schedule, "did_just_pause", return_value=True),
    ):
        sync_state_changes(task_schedule)
        mock_pause.assert_called_once_with(task_schedule.schedule_id)


@pytest.mark.django_db
def test_get_task_schedule_from_qstash(task_schedule):
    """Test getting a schedule from QStash"""
    mock_schedule = Schedule(
        schedule_id="test-id",
        destination="https://example.com/task",
        cron="*/5 * * * *",
        created_at=1704067200,
        body="test body",
        body_base64=None,
        method="POST",
        headers={},
        callback_headers=None,
        failure_callback_headers=None,
        retries=3,
        retry_delay_expression=None,
        callback=None,
        failure_callback=None,
        queue=None,
        delay=None,
        timeout=None,
        caller_ip=None,
        paused=False,
        flow_control=None,
        last_schedule_time=None,
        next_schedule_time=None,
        last_schedule_states=None,
        error=None,
        label=None,
    )

    with patch(
        "django_qstash.schedules.services.qstash_client.schedule.get",
        return_value=mock_schedule,
    ) as mock_get:
        # Test normal response
        result = get_task_schedule_from_qstash(task_schedule)
        assert isinstance(result, Schedule)
        mock_get.assert_called_once_with(task_schedule.schedule_id)

        # Test dict response
        result_dict = get_task_schedule_from_qstash(task_schedule, as_dict=True)
        assert isinstance(result_dict, dict)

        # Test error handling
        mock_get.side_effect = Exception("API Error")
        result = get_task_schedule_from_qstash(task_schedule)
        assert result is None


@pytest.mark.django_db
def test_sync_does_not_overwrite_existing_schedule_id(task_schedule):
    """When a schedule_id already exists, it is not overwritten on sync."""
    task_schedule.schedule_id = "existing-id"
    task_schedule.save()
    with patch(
        "django_qstash.schedules.services.qstash_client.schedule.create",
        return_value="new-id",
    ):
        sync_task_schedule_instance_to_qstash(task_schedule)
    task_schedule.refresh_from_db()
    assert task_schedule.schedule_id == "existing-id"


@pytest.mark.django_db
def test_sync_state_changes_noop(task_schedule):
    """No resume/pause transition leaves QStash untouched."""
    with (
        patch(
            "django_qstash.schedules.services.qstash_client.schedule.resume"
        ) as mock_resume,
        patch(
            "django_qstash.schedules.services.qstash_client.schedule.pause"
        ) as mock_pause,
        patch.object(task_schedule, "did_just_resume", return_value=False),
        patch.object(task_schedule, "did_just_pause", return_value=False),
    ):
        sync_state_changes(task_schedule)
        mock_resume.assert_not_called()
        mock_pause.assert_not_called()


@pytest.mark.django_db
def test_sync_state_changes_resume_exception_swallowed(task_schedule):
    with (
        patch(
            "django_qstash.schedules.services.qstash_client.schedule.resume",
            side_effect=Exception("API Error"),
        ),
        patch.object(task_schedule, "did_just_resume", return_value=True),
        patch.object(task_schedule, "did_just_pause", return_value=False),
    ):
        sync_state_changes(task_schedule)  # should not raise


@pytest.mark.django_db
def test_sync_state_changes_pause_exception_swallowed(task_schedule):
    with (
        patch(
            "django_qstash.schedules.services.qstash_client.schedule.pause",
            side_effect=Exception("API Error"),
        ),
        patch.object(task_schedule, "did_just_resume", return_value=False),
        patch.object(task_schedule, "did_just_pause", return_value=True),
    ):
        sync_state_changes(task_schedule)  # should not raise


@pytest.mark.django_db
def test_get_task_schedule_falsy_response(task_schedule):
    """A falsy (but non-error) response returns None."""
    with patch(
        "django_qstash.schedules.services.qstash_client.schedule.get",
        return_value=None,
    ):
        assert get_task_schedule_from_qstash(task_schedule) is None


@pytest.mark.django_db
def test_delete_task_schedule_from_qstash(task_schedule):
    """Test deleting a schedule from QStash"""
    with patch(
        "django_qstash.schedules.services.qstash_client.schedule.delete"
    ) as mock_delete:
        delete_task_schedule_from_qstash(task_schedule)
        mock_delete.assert_called_once_with(task_schedule.schedule_id)

        # Test error handling
        mock_delete.side_effect = Exception("API Error")
        delete_task_schedule_from_qstash(task_schedule)  # Should not raise
