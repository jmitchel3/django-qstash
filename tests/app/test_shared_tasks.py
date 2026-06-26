from __future__ import annotations

from datetime import datetime
from datetime import timezone
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from django_qstash.app import stashed_task
from django_qstash.app.base import AsyncResult
from django_qstash.app.base import EagerResult
from django_qstash.app.base import QStashTask
from django_qstash.app.base import _delay
from django_qstash.app.base import _supported_kwargs
from django_qstash.app.base import _timestamp
from django_qstash.db.models import TaskStatus
from django_qstash.exceptions import TaskResultError
from django_qstash.exceptions import TaskTimeoutError
from django_qstash.results.services import store_task_result


@stashed_task
def sample_task(x, y):
    return x + y


@stashed_task(name="custom_task", deduplicated=True)
def sample_task_with_options(x, y):
    return x * y


@stashed_task(delay_seconds=30)
def sample_task_with_delay_seconds(x, y):
    return x + y


class Calculator:
    @stashed_task
    def double(self, value):
        return value * 2


@pytest.fixture(autouse=True)
def mock_qstash_client():
    """Mock QStash client for all tests"""
    with patch("django_qstash.app.base.qstash_client") as mock_client:
        # Create a mock for the message object
        mock_message = Mock()
        mock_response = Mock()
        mock_response.message_id = "test-id-123"
        mock_message.publish_json = Mock(return_value=mock_response)
        mock_message.enqueue_json = Mock(return_value=mock_response)

        # Attach the mock message object to the client
        mock_client.message = mock_message
        yield mock_client


@pytest.mark.django_db
class TestQStashTasks:
    def test_basic_task_execution(self):
        """Test that tasks can be executed directly"""
        result = sample_task(2, 3)
        assert result == 5

    def test_task_with_options(self):
        """Test that tasks with custom options work"""
        result = sample_task_with_options(4, 5)
        assert result == 20

    def test_task_delay(self, mock_qstash_client):
        """Test that delay() sends task to QStash"""
        result = sample_task.delay(2, 3)

        assert result.task_id == "test-id-123"
        mock_qstash_client.message.publish_json.assert_called_once()

    def test_task_apply_async(self, mock_qstash_client):
        """Test that apply_async() works with countdown"""
        result = sample_task.apply_async(args=(2, 3), countdown=60)

        assert result.task_id == "test-id-123"
        call_kwargs = mock_qstash_client.message.publish_json.call_args[1]
        assert call_kwargs["delay"] == "60s"

    def test_task_apply_async_without_countdown(self, mock_qstash_client):
        """apply_async() without countdown still publishes to QStash."""
        result = sample_task.apply_async(args=(2, 3))

        assert result.task_id == "test-id-123"
        mock_qstash_client.message.publish_json.assert_called_once()

    def test_task_apply_async_delay_does_not_leak(self, mock_qstash_client):
        """Per-call delay options do not mutate the shared task wrapper."""
        sample_task.apply_async(args=(2, 3), countdown=60)
        sample_task.apply_async(args=(2, 3))

        first_call = mock_qstash_client.message.publish_json.call_args_list[0]
        second_call = mock_qstash_client.message.publish_json.call_args_list[1]
        assert first_call.kwargs["delay"] == "60s"
        assert "delay" not in second_call.kwargs

    def test_task_apply_async_qstash_options(self, mock_qstash_client):
        """Supported QStash message options are forwarded to publish_json."""
        eta = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)

        result = sample_task.apply_async(
            args=(2, 3),
            delay=10,
            max_retries=5,
            deduplication_id="task-2-3",
            callback="https://example.com/qstash/callback/",
            failure_callback="https://example.com/qstash/failure/",
            headers={"X-Trace-Id": "abc"},
            timeout="30s",
            eta=eta,
        )

        assert result.task_id == "test-id-123"
        call_kwargs = mock_qstash_client.message.publish_json.call_args.kwargs
        assert call_kwargs["delay"] == "10s"
        assert call_kwargs["retries"] == 5
        assert call_kwargs["deduplication_id"] == "task-2-3"
        assert call_kwargs["callback"] == "https://example.com/qstash/callback/"
        assert call_kwargs["failure_callback"] == "https://example.com/qstash/failure/"
        assert call_kwargs["headers"] == {"X-Trace-Id": "abc"}
        assert call_kwargs["timeout"] == "30s"
        assert call_kwargs["not_before"] == int(eta.timestamp())

    def test_task_apply_async_queue_uses_enqueue_json(self, mock_qstash_client):
        """The queue option uses QStash enqueue for FIFO task delivery."""
        result = sample_task.apply_async(args=(2, 3), queue="emails")

        assert result.task_id == "test-id-123"
        mock_qstash_client.message.enqueue_json.assert_called_once()
        call_kwargs = mock_qstash_client.message.enqueue_json.call_args.kwargs
        assert call_kwargs["queue"] == "emails"
        assert call_kwargs["body"]["args"] == (2, 3)

    def test_parameterized_decorator(self):
        """stashed_task(name=...) returns a decorator that wraps the function."""
        decorator = stashed_task(name="mytask")
        assert callable(decorator)

        def myfunc(a):
            return a

        wrapped = decorator(myfunc)
        assert isinstance(wrapped, QStashTask)
        assert wrapped.name == "mytask"
        assert wrapped(5) == 5

    def test_qstashtask_called_with_func_creates_wrapper(self):
        """A QStashTask with no func, called with a function, wraps it."""
        task = QStashTask(name="mytask")
        assert task.func is None

        def myfunc(a):
            return a

        wrapped = task(myfunc)
        assert isinstance(wrapped, QStashTask)
        assert wrapped.name == "mytask"
        assert wrapped(7) == 7

    def test_instance_method_access_and_call(self):
        """Accessing a task on an instance binds it; calling runs it directly."""
        calc = Calculator()
        assert calc.double(4) == 8

    def test_class_access_returns_task(self):
        """Accessing a task on the class returns the QStashTask descriptor."""
        assert isinstance(Calculator.double, QStashTask)

    def test_missing_config_raises(self):
        """Missing QSTASH_TOKEN/DOMAIN raises ImproperlyConfigured on call."""
        with override_settings(QSTASH_TOKEN=""):
            with pytest.raises(ImproperlyConfigured):
                sample_task(2, 3)


class TestTimestampHelper:
    def test_naive_datetime_assumes_utc(self):
        """A naive datetime is treated as UTC before conversion."""
        naive = datetime(2026, 6, 21, 12, 0)
        aware = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
        assert _timestamp(naive) == int(aware.timestamp())

    def test_int_passthrough(self):
        """An int/float eta is passed straight through as an int."""
        assert _timestamp(1000) == 1000
        assert _timestamp(1000.9) == 1000


class TestDelayHelper:
    def test_non_int_passthrough(self):
        """Non-int delay values (e.g. strings) are returned unchanged."""
        assert _delay("30s") == "30s"

    def test_bool_passthrough(self):
        """Booleans are not treated as integer seconds."""
        assert _delay(True) is True


class TestSupportedKwargs:
    def test_all_supported_returns_options(self):
        """When every option maps to a signature parameter, options pass through."""

        def method(url=None, body=None, delay=None):
            return None

        options = {"delay": "30s"}
        assert _supported_kwargs(method, options) == options

    def test_unsupported_option_raises(self):
        """An option missing from the signature raises ImproperlyConfigured."""

        def method(url=None, body=None):
            return None

        with pytest.raises(ImproperlyConfigured):
            _supported_kwargs(method, {"flow_control": {"key": "x"}})


@pytest.mark.django_db
class TestMessageOptionBranches:
    def test_delay_seconds_sets_delay(self, mock_qstash_client):
        """A task configured with delay_seconds sets the delay option."""
        sample_task_with_delay_seconds.delay(2, 3)

        call_kwargs = mock_qstash_client.message.publish_json.call_args.kwargs
        assert call_kwargs["delay"] == "30s"

    def test_deduplicated_option_sets_content_based_dedup(self, mock_qstash_client):
        """Passing deduplicated= maps to content_based_deduplication."""
        sample_task.apply_async(args=(2, 3), deduplicated=True)

        call_kwargs = mock_qstash_client.message.publish_json.call_args.kwargs
        assert call_kwargs["content_based_deduplication"] is True

    def test_task_deduplicated_flag_sets_content_based_dedup(self, mock_qstash_client):
        """A task constructed with deduplicated=True enables content dedup."""
        sample_task_with_options.delay(4, 5)

        call_kwargs = mock_qstash_client.message.publish_json.call_args.kwargs
        assert call_kwargs["content_based_deduplication"] is True

    def test_enqueue_without_func_raises(self):
        """_enqueue raises when the task does not wrap a function."""
        task = QStashTask()
        with pytest.raises(ImproperlyConfigured):
            task._enqueue(args=(), kwargs={})


@stashed_task
async def sample_async_task(x, y):
    return x + y


@stashed_task
def failing_task():
    raise ValueError("boom")


class TestAsyncResult:
    def test_id_property(self):
        result = AsyncResult("abc-123")
        assert result.id == "abc-123"
        assert result.task_id == "abc-123"

    @pytest.mark.django_db
    def test_pending_when_no_row(self):
        """Status is PENDING and result is None until a backend row exists."""
        result = AsyncResult("no-such-id")
        assert result.status == TaskStatus.PENDING
        assert result.state == TaskStatus.PENDING
        assert result.ready() is False
        assert result.successful() is False
        assert result.result is None

    @pytest.mark.django_db
    def test_reads_success_from_backend(self):
        """status/result/get() resolve from a stored SUCCESS TaskResult row."""
        store_task_result(
            task_id="msg-1",
            task_name="t",
            status=TaskStatus.SUCCESS,
            result=42,
        )
        result = AsyncResult("msg-1")
        assert result.status == TaskStatus.SUCCESS
        assert result.ready() is True
        assert result.successful() is True
        # 42 was wrapped as {"result": 42}; AsyncResult unwraps it.
        assert result.result == 42
        assert result.get(timeout=1) == 42

    @pytest.mark.django_db
    def test_dict_result_is_not_unwrapped(self):
        """A genuine multi-key dict result round-trips unchanged."""
        store_task_result(
            task_id="msg-dict",
            task_name="t",
            status=TaskStatus.SUCCESS,
            result={"a": 1, "b": 2},
        )
        assert AsyncResult("msg-dict").result == {"a": 1, "b": 2}

    @pytest.mark.django_db
    def test_get_propagates_failure(self):
        """get() raises TaskResultError for a failed task, carrying traceback."""
        store_task_result(
            task_id="msg-2",
            task_name="t",
            status=TaskStatus.EXECUTION_ERROR,
            traceback="Traceback: boom",
        )
        result = AsyncResult("msg-2")
        assert result.failed() is True
        with pytest.raises(TaskResultError, match="boom"):
            result.get(timeout=1)

    @pytest.mark.django_db
    def test_get_no_propagate_returns_result(self):
        """get(propagate=False) returns the stored value instead of raising."""
        store_task_result(
            task_id="msg-3",
            task_name="t",
            status=TaskStatus.EXECUTION_ERROR,
            traceback="boom",
        )
        assert AsyncResult("msg-3").get(timeout=1, propagate=False) is None

    @pytest.mark.django_db
    def test_get_times_out(self):
        """get() raises TaskTimeoutError when no terminal row arrives in time."""
        result = AsyncResult("never")
        with pytest.raises(TaskTimeoutError):
            result.get(timeout=0.05, interval=0.01)

    @pytest.mark.django_db
    def test_traceback_property(self):
        """traceback exposes the stored traceback string (or None)."""
        assert AsyncResult("missing").traceback is None
        store_task_result(
            task_id="msg-tb",
            task_name="t",
            status=TaskStatus.EXECUTION_ERROR,
            traceback="the traceback",
        )
        assert AsyncResult("msg-tb").traceback == "the traceback"

    def test_pending_when_results_app_missing(self):
        """When the results model is unavailable, status falls back to PENDING."""
        with patch("django_qstash.app.base.apps.get_model", side_effect=LookupError):
            result = AsyncResult("any")
            assert result.status == TaskStatus.PENDING
            assert result.result is None


class TestApply:
    def test_apply_runs_inline_and_returns_value(self):
        """apply() executes the task body and captures the return value."""
        result = sample_task.apply(args=(2, 3))
        assert isinstance(result, EagerResult)
        assert result.successful() is True
        assert result.result == 5
        assert result.get() == 5

    def test_apply_requires_no_qstash_config(self):
        """apply() works even when QStash token/domain are unset."""
        with override_settings(QSTASH_TOKEN="", DJANGO_QSTASH_DOMAIN=""):
            assert sample_task.apply(args=(4, 5)).get() == 9

    def test_apply_captures_exception(self):
        """A raising task yields a failed EagerResult that re-raises on get()."""
        result = failing_task.apply()
        assert result.failed() is True
        assert result.status == TaskStatus.EXECUTION_ERROR
        assert result.traceback is not None
        with pytest.raises(ValueError, match="boom"):
            result.get()

    def test_apply_get_no_propagate_returns_exception(self):
        """get(propagate=False) returns the captured exception instead of raising."""
        result = failing_task.apply()
        returned = result.get(propagate=False)
        assert isinstance(returned, ValueError)

    def test_apply_runs_async_task(self):
        """apply() runs coroutine task functions to completion."""
        assert sample_async_task.apply(args=(2, 3)).get() == 5

    def test_eager_result_state_and_ready(self):
        """EagerResult exposes Celery-style state/ready accessors."""
        result = sample_task.apply(args=(1, 1))
        assert result.state == TaskStatus.SUCCESS
        assert result.ready() is True

    def test_run_without_func_raises(self):
        """_run on a task that wraps no function raises ImproperlyConfigured."""
        task = QStashTask()
        with pytest.raises(ImproperlyConfigured):
            task.actual_func()


class TestAlwaysEager:
    @override_settings(DJANGO_QSTASH_ALWAYS_EAGER=True)
    def test_delay_runs_inline(self, mock_qstash_client):
        """With ALWAYS_EAGER, delay() runs inline and skips QStash."""
        result = sample_task.delay(2, 3)
        assert isinstance(result, EagerResult)
        assert result.get() == 5
        mock_qstash_client.message.publish_json.assert_not_called()

    @override_settings(DJANGO_QSTASH_ALWAYS_EAGER=True)
    def test_apply_async_runs_inline(self, mock_qstash_client):
        """With ALWAYS_EAGER, apply_async() runs inline and skips QStash."""
        result = sample_task.apply_async(args=(4, 5))
        assert result.get() == 9
        mock_qstash_client.message.publish_json.assert_not_called()

    @override_settings(
        DJANGO_QSTASH_ALWAYS_EAGER=True, QSTASH_TOKEN="", DJANGO_QSTASH_DOMAIN=""
    )
    def test_eager_needs_no_config(self, mock_qstash_client):
        """Eager delay() does not require QStash token/domain."""
        assert sample_task.delay(1, 1).get() == 2


class TestActualFunc:
    def test_actual_func_runs_sync(self):
        """actual_func runs the wrapped sync function directly."""
        assert sample_task.actual_func(2, 3) == 5

    def test_actual_func_runs_async(self):
        """actual_func runs a coroutine task function to completion."""
        assert sample_async_task.actual_func(2, 3) == 5
