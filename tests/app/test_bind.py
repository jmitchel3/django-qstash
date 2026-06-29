from __future__ import annotations

from unittest.mock import Mock
from unittest.mock import patch

import pytest

from django_qstash.app import shared_task
from django_qstash.app import stashed_task
from django_qstash.app.base import BoundTask
from django_qstash.app.base import QStashTask
from django_qstash.app.base import TaskRequest


@stashed_task(bind=True)
def bound_task(self, x, y):
    return {
        "id": self.request.id,
        "retries": self.request.retries,
        "correlation_id": self.request.correlation_id,
        "task_name": self.request.task_name,
        "args": self.request.args,
        "kwargs": self.request.kwargs,
        "sum": x + y,
    }


@shared_task(bind=True)
def bound_shared_task(self, value):
    return self.request.id, value


@stashed_task(bind=True)
async def bound_async_task(self, x, y):
    return self.request.retries, x + y


@stashed_task
def unbound_task(x, y):
    return x + y


@pytest.fixture(autouse=True)
def mock_qstash_client():
    with patch("django_qstash.app.base.qstash_client") as mock_client:
        mock_message = Mock()
        mock_response = Mock()
        mock_response.message_id = "bind-msg-1"
        mock_message.publish_json = Mock(return_value=mock_response)
        mock_message.enqueue_json = Mock(return_value=mock_response)
        mock_client.message = mock_message
        yield mock_client


class TestBindDecorator:
    def test_bind_flag_set(self):
        """bind=True is recorded on the task; default is False."""
        assert bound_task.bind is True
        assert unbound_task.bind is False

    def test_shared_task_bind_propagates(self):
        """@shared_task(bind=True) routes bind through to the QStashTask."""
        assert bound_shared_task.bind is True


class TestBindDirectCall:
    def test_direct_call_injects_self(self):
        """A bound task called directly receives a self with a request."""
        out = bound_task(2, 3)
        assert out["sum"] == 5
        assert isinstance(out["id"], str) and out["id"]
        assert out["retries"] == 0
        assert out["args"] == (2, 3)
        assert out["kwargs"] == {}

    def test_unbound_direct_call_unchanged(self):
        """A non-bound task is called with no extra leading argument."""
        assert unbound_task(2, 3) == 5


class TestBindEager:
    def test_apply_injects_request_with_uuid(self):
        """apply() honors bind, building a uuid id and retries=0."""
        result = bound_task.apply(args=(4, 5)).get()
        assert result["sum"] == 9
        assert result["retries"] == 0
        # In eager mode correlation_id mirrors the generated id.
        assert result["correlation_id"] == result["id"]
        assert result["task_name"] == "bound_task"

    def test_apply_async_async_task_with_bind(self):
        """async def + bind runs to completion via apply()."""
        retries, total = bound_async_task.apply(args=(2, 3)).get()
        assert (retries, total) == (0, 5)


class TestRunWithContext:
    def test_run_with_context_bind_passes_self(self):
        """run_with_context injects the bound proxy for bind=True tasks."""
        request = TaskRequest(id="msg-7", retries=3, task_name="bound_task")
        out = bound_task.run_with_context(request, 1, 1)
        assert out["id"] == "msg-7"
        assert out["retries"] == 3
        assert out["sum"] == 2

    def test_run_with_context_async_bind(self):
        """run_with_context awaits coroutine bound tasks."""
        request = TaskRequest(id="msg-async", retries=1)
        retries, total = bound_async_task.run_with_context(request, 2, 2)
        assert (retries, total) == (1, 4)

    def test_run_with_context_unbound_no_extra_arg(self):
        """A non-bound task receives only its own args (no leading self)."""
        request = TaskRequest(id="ignored")
        assert unbound_task.run_with_context(request, 2, 3) == 5


class TestBoundTaskProxy:
    def test_delegates_to_underlying_task(self):
        """The bound proxy exposes name and delegates delay/apply_async."""
        request = TaskRequest(id="msg-1")
        bound = BoundTask(bound_task, request)
        assert bound.request is request
        assert bound.name == "bound_task"
        # delay is delegated to the shared task and publishes to QStash.
        result = bound.delay(1, 2)
        assert result.task_id == "bind-msg-1"

    def test_self_reschedule_via_apply_async(self, mock_qstash_client):
        """A bound task can re-schedule itself through self.apply_async."""
        request = TaskRequest(id="msg-1")
        bound = BoundTask(bound_task, request)
        bound.apply_async(args=(3, 4))
        mock_qstash_client.message.publish_json.assert_called_once()


class TestTaskRequestDefaults:
    def test_defaults(self):
        """TaskRequest fills sensible defaults for optional fields."""
        request = TaskRequest(id="x")
        assert request.retries == 0
        assert request.correlation_id == ""
        assert request.task_name == ""
        assert request.args == ()
        assert request.kwargs == {}

    def test_signature_requires_func(self):
        """Building a signature on a func-less task raises."""
        from django.core.exceptions import ImproperlyConfigured

        task: QStashTask = QStashTask()
        with pytest.raises(ImproperlyConfigured):
            task.s()
