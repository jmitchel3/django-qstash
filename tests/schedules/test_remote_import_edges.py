from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from django_qstash.schedules.models import TaskSchedule
from django_qstash.schedules.reconcile import ScheduleSpec
from django_qstash.schedules.reconcile import reconcile_schedules
from django_qstash.schedules.services import ScheduleImportError
from django_qstash.schedules.services import _duration
from django_qstash.schedules.services import _flow_control
from django_qstash.schedules.services import _header_map
from django_qstash.schedules.services import parse_remote_schedule_body
from django_qstash.schedules.services import remote_schedule_to_fields

TASK = {"module": "reports.tasks", "function": "nightly"}


def schedule(body, **extra):
    attrs = {"schedule_id": "s1", "cron": "0 3 * * *", "body": body}
    attrs.update(extra)
    return SimpleNamespace(**attrs)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (None, "has no body"),
        ("", "has no body"),
        ("not json", "not JSON"),
        (json.dumps([1, 2]), "not a JSON object"),
        (json.dumps({"function": "f"}), "missing 'module'"),
        (json.dumps({"module": 3, "function": "f"}), "missing 'module'"),
        (json.dumps({"module": "m"}), "missing 'function'"),
        (json.dumps({**TASK, "args": "x"}), "'args' is not a list"),
        (json.dumps({**TASK, "kwargs": []}), "'kwargs' is not an object"),
        (json.dumps({**TASK, "options": [1]}), "'options' is not an object"),
    ],
)
def test_parse_remote_schedule_body_rejects(body, message):
    with pytest.raises(ScheduleImportError, match=message):
        parse_remote_schedule_body(schedule(body))


def test_parse_remote_schedule_body_fills_defaults():
    body = parse_remote_schedule_body(schedule(json.dumps({**TASK, "options": None})))
    assert body["args"] == []
    assert body["kwargs"] == {}
    assert body["options"] == {}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        (True, None),
        (0, None),
        (90, "90s"),
        (2.5, "2s"),
        ("5m", "5m"),
    ],
)
def test_duration(value, expected):
    assert _duration(value) == expected


def test_ms_to_seconds():
    from django_qstash.schedules.services import _ms_to_seconds

    assert _ms_to_seconds(90000) == 90
    assert _ms_to_seconds(1500) == 2
    assert _ms_to_seconds("5m") == "5m"
    assert _ms_to_seconds(None) is None
    assert _ms_to_seconds(True) is True


def test_header_map():
    assert _header_map(None) is None
    assert _header_map({}) == {}
    assert _header_map("not a dict") is None
    assert _header_map(
        {
            "Upstash-Forward-X-Token": "abc",
            "Content-Type": "application/json",
            "X-Multi": ("a", "b"),
        },
        "Upstash-Forward-",
    ) == {"X-Token": "abc", "X-Multi": "a,b"}


def test_flow_control():
    assert _flow_control(None) == {}
    assert _flow_control({"key": "k", "rate": None}) == {"key": "k"}
    assert _flow_control(
        SimpleNamespace(key="k", parallelism=None, rate=5, period=60)
    ) == {"key": "k", "rate": 5, "period": 60}


def test_remote_fields_without_optional_attributes():
    """A minimal remote schedule keeps local defaults for unknown values."""
    fields = remote_schedule_to_fields(
        schedule(json.dumps(TASK), retries=True, timeout=None, headers="bad")
    )
    assert "retries" not in fields
    assert "timeout" not in fields
    assert fields["delay"] == ""
    assert fields["headers"] == {}
    assert fields["flow_control"] == {}
    assert fields["is_active"] is True


@pytest.fixture
def fake_client():
    api = SimpleNamespace(
        list=lambda: [], create=lambda **d: d["schedule_id"], pause=None, resume=None
    )
    with patch(
        "django_qstash.schedules.reconcile.qstash_client",
        SimpleNamespace(schedule=api),
    ):
        yield api


@pytest.mark.django_db
def test_reconcile_spec_without_task_fails(fake_client):
    result = reconcile_schedules(
        [ScheduleSpec(key="a", task="", cron="* * * * *")], namespace="prod"
    )
    assert result.outcomes[0].action == "failed"
    assert result.outcomes[0].error == "spec has no task"
    assert TaskSchedule.objects.count() == 0


@pytest.mark.django_db
def test_reconcile_planning_error_is_reported(fake_client):
    with patch(
        "django_qstash.schedules.reconcile.TaskSchedule.objects.filter",
        side_effect=RuntimeError("db down"),
    ):
        result = reconcile_schedules(
            [ScheduleSpec(key="a", task="m.f", cron="* * * * *")], namespace="prod"
        )
    assert result.outcomes[0].action == "failed"
    assert result.outcomes[0].error == "db down"
    assert result.outcomes[0].local_saved is False


@pytest.mark.django_db
def test_reconcile_unparseable_remote_body_counts_as_drift(fake_client):
    fake_client.list = lambda: [
        SimpleNamespace(
            schedule_id="prod.a",
            destination="https://example.com/qstash/webhook/",
            cron="* * * * *",
            retries=3,
            body="<xml/>",
            paused=False,
        )
    ]
    result = reconcile_schedules(
        [ScheduleSpec(key="a", task="m.f", cron="* * * * *")],
        namespace="prod",
        dry_run=True,
    )
    assert result.outcomes[0].remote_drift == ["payload"]
