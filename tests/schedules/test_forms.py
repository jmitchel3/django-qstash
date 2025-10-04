from __future__ import annotations

import pytest

from django_qstash.schedules.forms import TaskScheduleForm


@pytest.fixture
def valid_form_data():
    return {
        "name": "Test Schedule",
        "task": "tests.discovery.tasks.debug_task",
        "task_name": "tests.discovery.tasks.debug_task",
        "args": [],
        "kwargs": {},
        "cron": "*/5 * * * *",
        "retries": 3,
        "timeout": "30s",
    }


def test_task_schedule_form_valid(valid_form_data):
    """Test form with valid data"""
    form = TaskScheduleForm(data=valid_form_data)
    assert form.is_valid()


@pytest.mark.parametrize(
    "field,value,expected_valid",
    [
        ("timeout", "invalid", False),  # No number or unit
        ("timeout", "30", False),  # Missing unit
        ("timeout", "30x", False),  # Invalid unit
        ("timeout", "-30s", False),  # Negative number
        ("timeout", "200h", False),  # > 7 days
        ("timeout", "30s", True),  # Valid seconds
        ("timeout", "5m", True),  # Valid minutes
        ("timeout", "2h", True),  # Valid hours
        ("timeout", "7d", True),  # Valid days (max)
        ("timeout", "8d", False),  # Invalid days (> 7)
        ("retries", 6, False),  # > 5
        ("retries", 3, True),
        ("cron", "*/70 * * * *", False),  # Invalid minutes value
        ("cron", "* * * * *", True),
    ],
)
def test_task_schedule_form_validation(valid_form_data, field, value, expected_valid):
    """Test form validation for specific fields"""
    form_data = valid_form_data.copy()
    form_data[field] = value
    form = TaskScheduleForm(data=form_data)

    is_valid = form.is_valid()
    assert is_valid == expected_valid, (
        f"Form validation for {field}={value} failed. Errors: {form.errors}"
    )


def test_task_schedule_form_json_fields(valid_form_data):
    """Test handling of JSON fields (args and kwargs)"""
    form_data = valid_form_data.copy()
    form_data["args"] = [1, "test", {"nested": "value"}]
    form_data["kwargs"] = {"key": "value", "nested": {"data": True}}

    form = TaskScheduleForm(data=form_data)
    assert form.is_valid()

    cleaned_data = form.cleaned_data
    assert cleaned_data["args"] == form_data["args"]
    assert cleaned_data["kwargs"] == form_data["kwargs"]


def test_task_name_auto_population(valid_form_data):
    """Test that task_name is automatically populated from task field"""
    form_data = valid_form_data.copy()
    del form_data["task_name"]  # Remove task_name completely instead of setting to None

    form = TaskScheduleForm(data=form_data)
    assert form.is_valid(), f"Form validation failed. Errors: {form.errors}"
    assert form.cleaned_data["task"] == form_data["task"], "Task field mismatch"
    assert form.cleaned_data["task_name"] == form.cleaned_data["task"], (
        "Task name not auto-populated"
    )
