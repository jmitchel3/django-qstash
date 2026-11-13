from __future__ import annotations

from unittest.mock import patch

import pytest

from django_qstash.app.base import AsyncResult
from django_qstash.db.models import TaskStatus
from django_qstash.exceptions import TaskResultError
from django_qstash.exceptions import TaskTimeoutError
from django_qstash.results.services import store_task_result

pytestmark = pytest.mark.django_db


def store(task_id, status, **overrides):
    fields = {
        "task_id": task_id,
        "task_name": "run",
        "function_path": "reports.tasks.run",
        "correlation_id": "root",
        "status": status,
    }
    fields.update(overrides)
    return store_task_result(**fields)


def test_follows_multiple_retries_without_selecting_success_links():
    store("root", TaskStatus.RETRY, result={"retry_task_id": "retry-1"})
    store(
        "retry-1",
        TaskStatus.RETRY,
        parent_task_id="root",
        result={"retry_task_id": "retry-2"},
    )
    store("retry-2", TaskStatus.SUCCESS, parent_task_id="retry-1", result=42)
    # A later linked task can have the same function and correlation id.
    store("success-link", TaskStatus.SUCCESS, parent_task_id="retry-2", result=99)

    result = AsyncResult("root")

    assert result.status == result.state == TaskStatus.SUCCESS
    assert result.ready() is True
    assert result.successful() is True
    assert result.failed() is False
    assert result.result == result.get(timeout=0) == 42
    assert result.traceback is None
    assert result.task_id == result.id == "root"


def test_terminal_retry_failure_is_exposed_and_propagated():
    store("root", TaskStatus.RETRY, result={"retry_task_id": "retry-1"})
    store(
        "retry-1",
        TaskStatus.EXECUTION_ERROR,
        parent_task_id="root",
        traceback="replacement failed",
        result={"error": "unavailable"},
    )
    result = AsyncResult("root")

    assert result.failed() is True
    assert result.ready() is True
    assert result.successful() is False
    assert result.traceback == "replacement failed"
    with pytest.raises(TaskResultError, match="replacement failed"):
        result.get(timeout=0)
    assert result.get(timeout=0, propagate=False) == {"error": "unavailable"}


def test_pending_replacement_remains_retry_and_is_refreshed():
    store("root", TaskStatus.RETRY, result={"retry_task_id": "retry-1"})
    result = AsyncResult("root")

    assert result.state == TaskStatus.RETRY
    assert result.ready() is False
    assert result.result == {"retry_task_id": "retry-1"}
    with pytest.raises(TaskTimeoutError):
        result.get(timeout=0)

    # Polling must re-read the replacement rather than cache the RETRY row.
    with patch(
        "django_qstash.app.base.time.sleep",
        side_effect=lambda _: store(
            "retry-1", TaskStatus.SUCCESS, parent_task_id="root", result=42
        ),
    ) as sleep:
        assert result.get(timeout=1) == 42
    sleep.assert_called_once()


def test_legacy_retry_without_explicit_link_does_not_guess_by_correlation():
    store("root", TaskStatus.RETRY)
    store("another", TaskStatus.SUCCESS, result=99)

    result = AsyncResult("root")

    assert result.state == TaskStatus.RETRY
    assert result.ready() is False
    assert result.result is None


@pytest.mark.parametrize("retry_task_id", [None, "", 123, ["retry-1"], {}])
def test_malformed_retry_link_stays_nonterminal(retry_task_id):
    store("root", TaskStatus.RETRY, result={"retry_task_id": retry_task_id})

    assert AsyncResult("root").state == TaskStatus.RETRY


@pytest.mark.parametrize(
    "overrides",
    [
        {"function_path": "reports.tasks.other"},
        {"correlation_id": "unrelated"},
        {"parent_task_id": "unrelated"},
    ],
)
def test_conflicting_replacement_lineage_is_not_followed(overrides):
    store("root", TaskStatus.RETRY, result={"retry_task_id": "retry-1"})
    store("retry-1", TaskStatus.SUCCESS, result=99, **overrides)

    result = AsyncResult("root")

    assert result.state == TaskStatus.RETRY
    assert result.ready() is False
    assert result.result == {"retry_task_id": "retry-1"}


def test_explicit_link_can_follow_legacy_rows_without_optional_lineage():
    store(
        "root",
        TaskStatus.RETRY,
        function_path=None,
        correlation_id="",
        result={"retry_task_id": "retry-1"},
    )
    store(
        "retry-1", TaskStatus.SUCCESS, function_path=None, correlation_id="", result=42
    )

    assert AsyncResult("root").get(timeout=0) == 42


def test_retry_cycle_stops_without_hanging():
    store("root", TaskStatus.RETRY, result={"retry_task_id": "retry-1"})
    store(
        "retry-1",
        TaskStatus.RETRY,
        parent_task_id="root",
        result={"retry_task_id": "root"},
    )

    result = AsyncResult("root")

    assert result.state == TaskStatus.RETRY
    with pytest.raises(TaskTimeoutError):
        result.get(timeout=0)


def test_terminal_results_are_not_interpreted_as_retry_links():
    store("root", TaskStatus.SUCCESS, result={"retry_task_id": "other"})
    store("other", TaskStatus.SUCCESS, result=99)

    assert AsyncResult("root").get(timeout=0) == {"retry_task_id": "other"}
