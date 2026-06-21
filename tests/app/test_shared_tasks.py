from __future__ import annotations

from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_qstash.app import stashed_task
from django_qstash.app.base import AsyncResult
from django_qstash.app.base import QStashTask


@stashed_task
def sample_task(x, y):
    return x + y


@stashed_task(name="custom_task", deduplicated=True)
def sample_task_with_options(x, y):
    return x * y


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


class TestAsyncResult:
    def test_id_property(self):
        result = AsyncResult("abc-123")
        assert result.id == "abc-123"
        assert result.task_id == "abc-123"

    def test_get_not_implemented(self):
        result = AsyncResult("abc-123")
        with pytest.raises(NotImplementedError):
            result.get()
