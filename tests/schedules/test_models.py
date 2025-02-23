from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from django_qstash.schedules.models import TaskSchedule


def test_task_schedule_creation(task_schedule):
    """Test basic TaskSchedule creation"""
    assert task_schedule.name == "Test Schedule"
    assert task_schedule.task == "myapp.tasks.sample_task"
    assert task_schedule.cron == "*/5 * * * *"
    assert task_schedule.args == []
    assert task_schedule.kwargs == {}
    assert task_schedule.retries == 3
    assert task_schedule.timeout == "30s"
    assert task_schedule.is_active is True
    assert task_schedule.is_paused is False
    assert task_schedule.is_resumed is True


def test_task_name_persistence(db):
    """Test that task_name is persisted correctly"""
    schedule = TaskSchedule.objects.create(
        name="Test Task Name",
        task="myapp.tasks.test_task",
    )
    assert schedule.task_name == "myapp.tasks.test_task"

    # Test task_name updates when task changes
    schedule.task = "myapp.tasks.new_task"
    schedule.save()
    assert schedule.task_name == "myapp.tasks.new_task"


@pytest.mark.parametrize(
    "is_active,expected_states",
    [
        (
            False,
            {
                "is_active": False,
                "is_paused": True,
                "is_resumed": False,
                "has_paused_at": True,
                "has_resumed_at": False,
                "has_active_at": False,
            },
        ),
        (
            True,
            {
                "is_active": True,
                "is_paused": False,
                "is_resumed": True,
                "has_paused_at": False,
                "has_resumed_at": True,
                "has_active_at": True,
            },
        ),
    ],
)
def test_schedule_state_transitions(db, is_active, expected_states):
    """Test state transitions when activating/deactivating schedule"""
    schedule = TaskSchedule.objects.create(
        name="Test States",
        task="myapp.tasks.test_task",
        is_active=is_active,
    )

    assert schedule.is_active == expected_states["is_active"]
    assert schedule.is_paused == expected_states["is_paused"]
    assert schedule.is_resumed == expected_states["is_resumed"]
    assert bool(schedule.paused_at) == expected_states["has_paused_at"]
    assert bool(schedule.resumed_at) == expected_states["has_resumed_at"]
    assert bool(schedule.active_at) == expected_states["has_active_at"]


def test_did_just_resume(db):
    """Test did_just_resume method"""
    schedule = TaskSchedule.objects.create(
        name="Test Resume",
        task="myapp.tasks.test_task",
        is_active=True,
    )

    # Force update both updated_at and resumed_at to be in the past
    old_time = timezone.now() - timedelta(minutes=2)
    TaskSchedule.objects.filter(pk=schedule.pk).update(
        updated_at=old_time, resumed_at=old_time
    )
    schedule.refresh_from_db()

    assert not schedule.did_just_resume()  # Should be False for old resume

    # Update resumed_at to be recent
    current_time = timezone.now()
    TaskSchedule.objects.filter(pk=schedule.pk).update(
        resumed_at=current_time, updated_at=current_time - timedelta(minutes=1)
    )
    schedule.refresh_from_db()
    assert schedule.did_just_resume()  # Should be True for recent resume

    # Test with custom delta
    assert schedule.did_just_resume(
        delta_seconds=180
    )  # Should be True with 3 minute window


def test_did_just_pause(db):
    """Test did_just_pause method"""
    schedule = TaskSchedule.objects.create(
        name="Test Pause",
        task="myapp.tasks.test_task",
        is_active=False,
    )

    # Force update both updated_at and paused_at to be in the past
    old_time = timezone.now() - timedelta(minutes=2)
    TaskSchedule.objects.filter(pk=schedule.pk).update(
        updated_at=old_time, paused_at=old_time
    )
    schedule = TaskSchedule.objects.get(
        pk=schedule.pk
    )  # Get fresh instance instead of refresh_from_db()

    assert not schedule.did_just_pause()  # Should be False for old pause

    # Update paused_at to be recent
    current_time = timezone.now()
    TaskSchedule.objects.filter(pk=schedule.pk).update(paused_at=current_time)
    schedule = TaskSchedule.objects.get(pk=schedule.pk)  # Get fresh instance

    assert schedule.did_just_pause()  # Should be True for recent pause

    # Test with custom delta
    assert schedule.did_just_pause(
        delta_seconds=180
    )  # Should be True with 3 minute window


@pytest.mark.parametrize(
    "timeout,retries,expected_valid",
    [
        ("60s", 3, True),  # 1 minute
        ("1m", 5, True),  # 1 minute
        ("2h", 0, True),  # 2 hours
        ("100h", 3, True),  # ~4.17 days (valid)
        ("invalid", 3, False),  # invalid format
        ("60s", 6, False),  # invalid retries
        ("200h", 3, False),  # ~8.33 days (invalid)
        ("8d", 3, False),  # 8 days (invalid)
        ("604801s", 3, False),  # > 7 days (invalid)
        ("10081m", 3, False),  # > 7 days (invalid)
        ("169h", 3, False),  # > 7 days (invalid)
    ],
)
def test_task_schedule_validation(db, timeout, retries, expected_valid):
    """Test validation of timeout and retries fields"""
    schedule = TaskSchedule(
        name="Test Validation",
        task="myapp.tasks.test_task",
        timeout=timeout,
        retries=retries,
    )

    try:
        schedule.full_clean()  # This will trigger all validators
        schedule.save()
        assert expected_valid, (
            f"Expected validation to fail for timeout={timeout}, retries={retries}"
        )
    except ValidationError as e:
        assert not expected_valid, f"Unexpected validation error: {str(e)}"


def test_json_field_handling(db):
    """Test handling of complex JSON data in args and kwargs fields"""
    complex_args = [
        1,
        "string",
        {"nested": "dict"},
        ["nested", "list"],
        None,
    ]
    complex_kwargs = {
        "simple": "value",
        "number": 42,
        "nested": {"key": "value"},
        "list": [1, 2, 3],
        "null": None,
    }

    schedule = TaskSchedule.objects.create(
        name="Test JSON",
        task="myapp.tasks.test_task",
        args=complex_args,
        kwargs=complex_kwargs,
    )

    # Refresh from database to ensure proper serialization/deserialization
    schedule.refresh_from_db()

    assert schedule.args == complex_args
    assert schedule.kwargs == complex_kwargs

    # Test defaults
    empty_schedule = TaskSchedule.objects.create(
        name="Empty JSON",
        task="myapp.tasks.test_task",
    )
    assert empty_schedule.args == []
    assert empty_schedule.kwargs == {}
