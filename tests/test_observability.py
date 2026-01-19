from __future__ import annotations

import json
import logging
import time
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.http import HttpRequest

from django_qstash.handlers import QStashWebhook
from django_qstash.handlers import correlation_id
from django_qstash.logging import JSONFormatter
from django_qstash.logging import StructuredLogFilter
from django_qstash.signals import task_completed
from django_qstash.signals import task_failed
from django_qstash.signals import task_started
from django_qstash.signals import webhook_received

# Add pytest mark for database access
pytestmark = pytest.mark.django_db


class TestCorrelationId:
    """Tests for correlation ID propagation."""

    def test_correlation_id_default_value(self):
        """Test that correlation_id has an empty string default."""
        # Reset to ensure clean state
        token = correlation_id.set("")
        try:
            assert correlation_id.get() == ""
        finally:
            correlation_id.reset(token)

    def test_correlation_id_set_and_get(self):
        """Test setting and getting correlation ID."""
        test_id = "msg_test123"
        token = correlation_id.set(test_id)
        try:
            assert correlation_id.get() == test_id
        finally:
            correlation_id.reset(token)

    def test_correlation_id_extracted_from_request(self):
        """Test that correlation ID is extracted from Upstash-Message-Id header."""
        webhook = QStashWebhook()
        request = Mock(spec=HttpRequest)
        request.body = json.dumps(
            {"function": "test_func", "module": "test_module", "args": [], "kwargs": {}}
        ).encode()
        message_id = "msg_abc123xyz"
        request.headers = {
            "Upstash-Signature": "valid",
            "Upstash-Message-Id": message_id,
        }
        request.build_absolute_uri.return_value = "https://example.com"
        request.META = {"REMOTE_ADDR": "127.0.0.1"}

        # Reset correlation_id before test
        token = correlation_id.set("")

        try:
            with (
                patch.object(webhook, "verify_signature"),
                patch.object(webhook, "execute_task") as mock_execute,
            ):
                mock_execute.return_value = "result"
                webhook.handle_request(request)

            # Verify correlation_id was set during request handling
            # Note: In real async context this would persist, but in sync test
            # we verify by checking the call was made with correct ID
            assert correlation_id.get() == message_id
        finally:
            correlation_id.reset(token)


class TestStructuredLogFilter:
    """Tests for StructuredLogFilter."""

    def test_filter_adds_correlation_id(self):
        """Test that filter adds correlation_id to log records."""
        log_filter = StructuredLogFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )

        # Set a correlation ID
        test_id = "msg_filter_test"
        token = correlation_id.set(test_id)
        try:
            result = log_filter.filter(record)
            assert result is True
            assert hasattr(record, "correlation_id")
            assert record.correlation_id == test_id
        finally:
            correlation_id.reset(token)

    def test_filter_adds_timestamp(self):
        """Test that filter adds timestamp to log records."""
        log_filter = StructuredLogFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )

        result = log_filter.filter(record)
        assert result is True
        assert hasattr(record, "timestamp")
        # Verify timestamp is ISO format
        assert "T" in record.timestamp
        assert "+" in record.timestamp or "Z" in record.timestamp


class TestJSONFormatter:
    """Tests for JSONFormatter."""

    def test_format_basic_log(self):
        """Test basic log formatting as JSON."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="django_qstash.handlers",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="task_completed",
            args=(),
            exc_info=None,
        )
        record.correlation_id = "msg_json_test"
        record.timestamp = "2024-01-15T12:34:56.789012+00:00"

        output = formatter.format(record)
        data = json.loads(output)

        assert data["level"] == "INFO"
        assert data["logger"] == "django_qstash.handlers"
        assert data["message"] == "task_completed"
        assert data["correlation_id"] == "msg_json_test"
        assert data["timestamp"] == "2024-01-15T12:34:56.789012+00:00"

    def test_format_with_extra_fields(self):
        """Test that extra fields are included in JSON output."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="django_qstash.handlers",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="task_completed",
            args=(),
            exc_info=None,
        )
        record.correlation_id = "msg_extra_test"
        record.timestamp = "2024-01-15T12:34:56.789012+00:00"
        record.task = "myapp.tasks.process_data"
        record.duration_seconds = 0.1234
        record.status = "success"

        output = formatter.format(record)
        data = json.loads(output)

        assert data["task"] == "myapp.tasks.process_data"
        assert data["duration_seconds"] == 0.1234
        assert data["status"] == "success"

    def test_format_with_exception(self):
        """Test that exception info is included in JSON output."""
        formatter = JSONFormatter()

        try:
            raise ValueError("Test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="django_qstash.handlers",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="task_failed",
            args=(),
            exc_info=exc_info,
        )
        record.correlation_id = "msg_exc_test"
        record.timestamp = "2024-01-15T12:34:56.789012+00:00"

        output = formatter.format(record)
        data = json.loads(output)

        assert "exception" in data
        assert "ValueError" in data["exception"]
        assert "Test error" in data["exception"]


class TestTaskExecutionMetrics:
    """Tests for task execution timing metrics."""

    def test_task_duration_logged_on_success(self):
        """Test that task duration is logged on successful execution."""
        webhook = QStashWebhook()

        def mock_task(*args, **kwargs):
            time.sleep(0.01)  # Small delay to ensure measurable duration
            return "result"

        mock_func = Mock()
        mock_func.actual_func = mock_task

        payload = Mock(
            function_path="test.path",
            task_name="test.path",
            args=[],
            kwargs={},
        )

        with (
            patch("django_qstash.handlers.utils.import_string", return_value=mock_func),
            patch("django_qstash.handlers.discover_tasks", return_value=["test.path"]),
            patch("django_qstash.handlers.logger") as mock_logger,
            patch("django_qstash.handlers._emit_signal"),
        ):
            result = webhook.execute_task(payload)

        assert result == "result"
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "task_completed"
        extra = call_args[1]["extra"]
        assert "duration_seconds" in extra
        assert extra["duration_seconds"] >= 0.01
        assert extra["status"] == "success"
        assert extra["task"] == "test.path"

    def test_task_duration_logged_on_failure(self):
        """Test that task duration is logged on failed execution."""
        webhook = QStashWebhook()

        def mock_task(*args, **kwargs):
            time.sleep(0.01)
            raise ValueError("Test error")

        mock_func = Mock()
        mock_func.actual_func = mock_task

        payload = Mock(
            function_path="test.path",
            task_name="test.path",
            args=[],
            kwargs={},
        )

        from django_qstash.exceptions import TaskError

        with (
            patch("django_qstash.handlers.utils.import_string", return_value=mock_func),
            patch("django_qstash.handlers.discover_tasks", return_value=["test.path"]),
            patch("django_qstash.handlers.logger") as mock_logger,
            patch("django_qstash.handlers._emit_signal"),
        ):
            with pytest.raises(TaskError):
                webhook.execute_task(payload)

        mock_logger.exception.assert_called_once()
        call_args = mock_logger.exception.call_args
        assert call_args[0][0] == "task_failed"
        extra = call_args[1]["extra"]
        assert "duration_seconds" in extra
        assert extra["duration_seconds"] >= 0.01
        assert extra["status"] == "error"
        assert extra["error_type"] == "ValueError"

    def test_timing_accuracy(self):
        """Test that timing is reasonably accurate."""
        webhook = QStashWebhook()
        sleep_duration = 0.05

        def mock_task(*args, **kwargs):
            time.sleep(sleep_duration)
            return "result"

        mock_func = Mock()
        mock_func.actual_func = mock_task

        payload = Mock(
            function_path="test.path",
            task_name="test.path",
            args=[],
            kwargs={},
        )

        with (
            patch("django_qstash.handlers.utils.import_string", return_value=mock_func),
            patch("django_qstash.handlers.discover_tasks", return_value=["test.path"]),
            patch("django_qstash.handlers.logger") as mock_logger,
            patch("django_qstash.handlers._emit_signal"),
        ):
            webhook.execute_task(payload)

        extra = mock_logger.info.call_args[1]["extra"]
        # Allow some tolerance for timing
        assert sleep_duration <= extra["duration_seconds"] < sleep_duration + 0.02


class TestSignalEmission:
    """Tests for Django signal emission."""

    def test_webhook_received_signal_emitted(self):
        """Test that webhook_received signal is emitted."""
        received_signals = []

        def signal_handler(sender, **kwargs):
            received_signals.append(kwargs)

        webhook_received.connect(signal_handler)

        try:
            webhook = QStashWebhook()
            request = Mock(spec=HttpRequest)
            request.body = json.dumps(
                {
                    "function": "test_func",
                    "module": "test_module",
                    "args": [],
                    "kwargs": {},
                }
            ).encode()
            request.headers = {
                "Upstash-Signature": "valid",
                "Upstash-Message-Id": "msg_signal_test",
            }
            request.build_absolute_uri.return_value = "https://example.com"
            request.META = {"REMOTE_ADDR": "192.168.1.1"}

            with (
                patch.object(webhook, "verify_signature"),
                patch.object(webhook, "execute_task", return_value="result"),
            ):
                webhook.handle_request(request)

            assert len(received_signals) == 1
            assert received_signals[0]["message_id"] == "msg_signal_test"
            assert received_signals[0]["task_path"] == "test_module.test_func"
            assert received_signals[0]["source_ip"] == "192.168.1.1"
        finally:
            webhook_received.disconnect(signal_handler)

    def test_task_started_signal_emitted(self):
        """Test that task_started signal is emitted."""
        received_signals = []

        def signal_handler(sender, **kwargs):
            received_signals.append(kwargs)

        task_started.connect(signal_handler)

        try:
            webhook = QStashWebhook()

            def mock_task(*args, **kwargs):
                return "result"

            mock_func = Mock()
            mock_func.actual_func = mock_task

            payload = Mock(
                function_path="test.path",
                task_name="my_task",
                args=[1, 2],
                kwargs={"key": "value"},
            )

            with (
                patch(
                    "django_qstash.handlers.utils.import_string", return_value=mock_func
                ),
                patch(
                    "django_qstash.handlers.discover_tasks", return_value=["test.path"]
                ),
            ):
                webhook.execute_task(payload)

            assert len(received_signals) == 1
            assert received_signals[0]["task_name"] == "my_task"
            assert received_signals[0]["args"] == [1, 2]
            assert received_signals[0]["kwargs"] == {"key": "value"}
        finally:
            task_started.disconnect(signal_handler)

    def test_task_completed_signal_emitted(self):
        """Test that task_completed signal is emitted on success."""
        received_signals = []

        def signal_handler(sender, **kwargs):
            received_signals.append(kwargs)

        task_completed.connect(signal_handler)

        try:
            webhook = QStashWebhook()

            def mock_task(*args, **kwargs):
                return "my_result"

            mock_func = Mock()
            mock_func.actual_func = mock_task

            payload = Mock(
                function_path="test.path",
                task_name="my_task",
                args=[],
                kwargs={},
            )

            with (
                patch(
                    "django_qstash.handlers.utils.import_string", return_value=mock_func
                ),
                patch(
                    "django_qstash.handlers.discover_tasks", return_value=["test.path"]
                ),
            ):
                webhook.execute_task(payload)

            assert len(received_signals) == 1
            assert received_signals[0]["task_name"] == "my_task"
            assert received_signals[0]["result"] == "my_result"
            assert "duration" in received_signals[0]
            assert received_signals[0]["duration"] >= 0
        finally:
            task_completed.disconnect(signal_handler)

    def test_task_failed_signal_emitted(self):
        """Test that task_failed signal is emitted on failure."""
        received_signals = []

        def signal_handler(sender, **kwargs):
            received_signals.append(kwargs)

        task_failed.connect(signal_handler)

        try:
            webhook = QStashWebhook()

            def mock_task(*args, **kwargs):
                raise ValueError("Test error")

            mock_func = Mock()
            mock_func.actual_func = mock_task

            payload = Mock(
                function_path="test.path",
                task_name="my_task",
                args=[],
                kwargs={},
            )

            from django_qstash.exceptions import TaskError

            with (
                patch(
                    "django_qstash.handlers.utils.import_string", return_value=mock_func
                ),
                patch(
                    "django_qstash.handlers.discover_tasks", return_value=["test.path"]
                ),
            ):
                with pytest.raises(TaskError):
                    webhook.execute_task(payload)

            assert len(received_signals) == 1
            assert received_signals[0]["task_name"] == "my_task"
            assert isinstance(received_signals[0]["exception"], ValueError)
            assert "duration" in received_signals[0]
        finally:
            task_failed.disconnect(signal_handler)

    def test_signals_not_emitted_when_disabled(self):
        """Test that signals are not emitted when DJANGO_QSTASH_EMIT_SIGNALS is False."""
        received_signals = []

        def signal_handler(sender, **kwargs):
            received_signals.append(kwargs)

        task_started.connect(signal_handler)
        task_completed.connect(signal_handler)

        try:
            webhook = QStashWebhook()

            def mock_task(*args, **kwargs):
                return "result"

            mock_func = Mock()
            mock_func.actual_func = mock_task

            payload = Mock(
                function_path="test.path",
                task_name="my_task",
                args=[],
                kwargs={},
            )

            with (
                patch(
                    "django_qstash.handlers.utils.import_string", return_value=mock_func
                ),
                patch(
                    "django_qstash.handlers.discover_tasks", return_value=["test.path"]
                ),
                patch("django_qstash.handlers.DJANGO_QSTASH_EMIT_SIGNALS", False),
            ):
                webhook.execute_task(payload)

            # No signals should have been received
            assert len(received_signals) == 0
        finally:
            task_started.disconnect(signal_handler)
            task_completed.disconnect(signal_handler)


class TestLogTaskArgsSettings:
    """Tests for DJANGO_QSTASH_LOG_TASK_ARGS setting."""

    def test_args_not_logged_by_default(self):
        """Test that task args are not logged when setting is False."""
        webhook = QStashWebhook()

        def mock_task(*args, **kwargs):
            return "result"

        mock_func = Mock()
        mock_func.actual_func = mock_task

        payload = Mock(
            function_path="test.path",
            task_name="test.path",
            args=["sensitive_data"],
            kwargs={"password": "secret"},
        )

        with (
            patch("django_qstash.handlers.utils.import_string", return_value=mock_func),
            patch("django_qstash.handlers.discover_tasks", return_value=["test.path"]),
            patch("django_qstash.handlers.logger") as mock_logger,
            patch("django_qstash.handlers.DJANGO_QSTASH_LOG_TASK_ARGS", False),
            patch("django_qstash.handlers._emit_signal"),
        ):
            webhook.execute_task(payload)

        extra = mock_logger.info.call_args[1]["extra"]
        assert "args" not in extra
        assert "kwargs" not in extra

    def test_args_logged_when_enabled(self):
        """Test that task args are logged when setting is True."""
        webhook = QStashWebhook()

        def mock_task(*args, **kwargs):
            return "result"

        mock_func = Mock()
        mock_func.actual_func = mock_task

        payload = Mock(
            function_path="test.path",
            task_name="test.path",
            args=["data"],
            kwargs={"key": "value"},
        )

        with (
            patch("django_qstash.handlers.utils.import_string", return_value=mock_func),
            patch("django_qstash.handlers.discover_tasks", return_value=["test.path"]),
            patch("django_qstash.handlers.logger") as mock_logger,
            patch("django_qstash.handlers.DJANGO_QSTASH_LOG_TASK_ARGS", True),
            patch("django_qstash.handlers._emit_signal"),
        ):
            webhook.execute_task(payload)

        extra = mock_logger.info.call_args[1]["extra"]
        assert extra["args"] == ["data"]
        assert extra["kwargs"] == {"key": "value"}
