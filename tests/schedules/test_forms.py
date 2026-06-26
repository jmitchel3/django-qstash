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
        "retry_delay": "",
        "delay": "",
        "queue": "",
        "headers": {},
        "callback": "",
        "callback_headers": {},
        "failure_callback": "",
        "failure_callback_headers": {},
        "flow_control": {},
        "label": "",
        "redact": {},
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
        ("delay", "1d10m", True),  # Valid compound QStash delay
        ("delay", "7d1s", False),  # Invalid delay (> 7 days)
        ("retries", 6, False),  # > 5
        ("retries", 3, True),
        ("cron", "*/70 * * * *", False),  # Invalid minutes value
        ("cron", "* * * * *", True),
        ("cron", "CRON_TZ=America/New_York 0 4 * * *", True),
    ],
)
def test_task_schedule_form_validation(valid_form_data, field, value, expected_valid):
    """Test form validation for specific fields"""
    form_data = valid_form_data.copy()
    form_data[field] = value
    form = TaskScheduleForm(data=form_data)

    is_valid = form.is_valid()
    assert (
        is_valid == expected_valid
    ), f"Form validation for {field}={value} failed. Errors: {form.errors}"


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
    assert (
        form.cleaned_data["task_name"] == form.cleaned_data["task"]
    ), "Task name not auto-populated"


def test_task_schedule_form_qstash_delivery_options(valid_form_data):
    form_data = valid_form_data.copy()
    form_data.update(
        {
            "retry_delay": "1000 * (1 + retried)",
            "delay": "1d10m",
            "queue": "emails",
            "headers": {"X-Trace-Id": "abc"},
            "callback": "https://example.com/qstash/callback/",
            "callback_headers": {"X-Callback": "yes"},
            "failure_callback": "https://example.com/qstash/failure/",
            "failure_callback_headers": {"X-Failure": "yes"},
            "flow_control": {"key": "emails", "parallelism": 1},
            "label": "scheduled,email",
            "redact": {"body": True},
        }
    )

    form = TaskScheduleForm(data=form_data)

    assert form.is_valid(), form.errors
    assert form.cleaned_data["retry_delay"] == "1000 * (1 + retried)"
    assert form.cleaned_data["delay"] == "1d10m"
    assert form.cleaned_data["queue"] == "emails"
    assert form.cleaned_data["headers"] == {"X-Trace-Id": "abc"}
    assert form.cleaned_data["callback"] == "https://example.com/qstash/callback/"
    assert form.cleaned_data["callback_headers"] == {"X-Callback": "yes"}
    assert (
        form.cleaned_data["failure_callback"] == "https://example.com/qstash/failure/"
    )
    assert form.cleaned_data["failure_callback_headers"] == {"X-Failure": "yes"}
    assert form.cleaned_data["flow_control"] == {"key": "emails", "parallelism": 1}
    assert form.cleaned_data["label"] == "scheduled,email"
    assert form.cleaned_data["redact"] == {"body": True}
