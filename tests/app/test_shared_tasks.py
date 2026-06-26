from __future__ import annotations

from datetime import datetime
from datetime import timezone
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_qstash.app import stashed_task
from django_qstash.app.base import AsyncResult
from django_qstash.app.base import QStashTask
from django_qstash.app.base import _delay
from django_qstash.app.base import _supported_kwargs
from django_qstash.app.base import _timestamp


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

    def test_missing_config_raises(self, monkeypatch):
        """Missing QSTASH_TOKEN/DOMAIN raises ImproperlyConfigured on call."""
        monkeypatch.setattr("django_qstash.app.base.QSTASH_TOKEN", "")
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


class TestAsyncResult:
    def test_id_property(self):
        result = AsyncResult("abc-123")
        assert result.id == "abc-123"
        assert result.task_id == "abc-123"

    def test_get_not_implemented(self):
        result = AsyncResult("abc-123")
        with pytest.raises(NotImplementedError):
            result.get()
