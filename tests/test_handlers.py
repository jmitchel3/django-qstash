from __future__ import annotations

import json
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.http import HttpRequest
from django.test import override_settings

from django_qstash.db.models import TaskStatus
from django_qstash.exceptions import PayloadError
from django_qstash.exceptions import SignatureError
from django_qstash.exceptions import TaskError
from django_qstash.handlers import QStashWebhook
from django_qstash.handlers import TaskPayload

# Add pytest mark for database access
pytestmark = pytest.mark.django_db


class TestTaskPayload:
    def test_from_dict_valid(self):
        data = {
            "function": "test_func",
            "module": "test_module",
            "args": [1, 2],
            "kwargs": {"key": "value"},
        }
        payload = TaskPayload.from_dict(data)

        assert payload.function == "test_func"
        assert payload.module == "test_module"
        assert payload.args == [1, 2]
        assert payload.kwargs == {"key": "value"}
        assert payload.task_name == "test_module.test_func"
        assert payload.function_path == "test_module.test_func"

    def test_from_dict_invalid(self):
        data = {"invalid": "data"}
        with pytest.raises(PayloadError):
            TaskPayload.from_dict(data)


class TestQStashWebhook:
    @pytest.fixture
    def webhook(self):
        return QStashWebhook()

    def test_verify_signature_missing(self, webhook):
        with pytest.raises(SignatureError, match="Missing Upstash-Signature"):
            webhook.verify_signature("body", "", "http://example.com")

    def test_verify_signature_invalid(self, webhook):
        with pytest.raises(SignatureError, match="Invalid signature"):
            webhook.verify_signature("body", "invalid", "http://example.com")

    def test_parse_payload_invalid_json(self, webhook):
        with pytest.raises(PayloadError, match="Invalid JSON payload"):
            webhook.parse_payload("invalid json")

    def test_execute_task_import_error(self, webhook):
        payload = Mock(function_path="nonexistent.module")
        with patch(
            "django_qstash.handlers.discover_tasks",
            return_value=["nonexistent.module"],
        ):
            with pytest.raises(TaskError, match="Could not import task function"):
                webhook.execute_task(payload)

    def test_handle_request_success(self, webhook):
        request = Mock(spec=HttpRequest)
        request.body = json.dumps(
            {"function": "test_func", "module": "test_module", "args": [], "kwargs": {}}
        ).encode()
        request.headers = {"Upstash-Signature": "valid", "Upstash-Message-Id": "123"}
        request.META = {"REMOTE_ADDR": "127.0.0.1"}
        request.build_absolute_uri.return_value = "https://example.com"

        with (
            patch.object(webhook, "verify_signature"),
            patch.object(webhook, "execute_task") as mock_execute,
        ):
            mock_execute.return_value = "result"
            response, status = webhook.handle_request(request)

        assert status == 200
        assert response["status"] == "success"
        assert response["result"] == "result"

    def test_handle_request_signature_error(self, webhook):
        request = Mock(spec=HttpRequest)
        request.body = json.dumps(
            {"function": "test_func", "module": "test_module", "args": [], "kwargs": {}}
        ).encode()
        request.headers = {}
        request.META = {"REMOTE_ADDR": "127.0.0.1"}
        request.build_absolute_uri.return_value = "https://example.com"

        response, status = webhook.handle_request(request)

        assert status == 400
        assert response["status"] == "error"
        assert response["error_type"] == "SignatureError"

    def test_handle_request_task_error(self, webhook):
        request = Mock(spec=HttpRequest)
        request.body = json.dumps(
            {"function": "test_func", "module": "test_module", "args": [], "kwargs": {}}
        ).encode()
        request.headers = {"Upstash-Signature": "valid", "Upstash-Message-Id": "123"}
        request.META = {"REMOTE_ADDR": "127.0.0.1"}
        request.build_absolute_uri.return_value = "https://example.com"

        with (
            patch.object(webhook, "verify_signature"),
            patch.object(webhook, "execute_task") as mock_execute,
        ):
            mock_execute.side_effect = TaskError("Task failed")
            response, status = webhook.handle_request(request)

        assert status == 422
        assert response["status"] == "error"
        assert response["error_type"] == "TaskError"
        assert response["error"] == "Task failed"
        assert response["task_name"] is not None

    def test_handle_request_unexpected_error(self, webhook):
        request = Mock(spec=HttpRequest)
        request.body = json.dumps(
            {"function": "test_func", "module": "test_module", "args": [], "kwargs": {}}
        ).encode()
        request.headers = {"Upstash-Signature": "valid"}
        request.META = {"REMOTE_ADDR": "127.0.0.1"}
        request.build_absolute_uri.return_value = "https://example.com"

        with patch.object(webhook, "verify_signature") as mock_verify:
            mock_verify.side_effect = Exception("Unexpected error")
            response, status = webhook.handle_request(request)

        assert status == 500
        assert response["status"] == "error"
        assert response["error_type"] == "InternalServerError"
        assert response["error"] == "An unexpected error occurred"
        assert response["task_name"] is None

    def test_execute_task_with_actual_func(self, webhook):
        def actual_function(*args, **kwargs):
            return "actual result"

        mock_func = Mock()
        mock_func.actual_func = actual_function

        payload = Mock(
            function_path="test.path",
            args=[1, 2],
            kwargs={"key": "value"},
            task_name="test.path",
        )

        with (
            patch(
                "django_qstash.handlers.discover_tasks",
                return_value=["test.path"],
            ),
            patch("django_qstash.handlers.utils.import_string", return_value=mock_func),
        ):
            result = webhook.execute_task(payload)

        assert result == "actual result"

    def test_execute_task_plain_callable(self, webhook):
        """A plain callable without actual_func is invoked directly."""

        def plain(*args, **kwargs):
            return "plain result"

        payload = Mock(
            function_path="test.path",
            args=[],
            kwargs={},
            task_name="test.path",
        )
        with (
            patch(
                "django_qstash.handlers.discover_tasks",
                return_value=["test.path"],
            ),
            patch("django_qstash.handlers.utils.import_string", return_value=plain),
            patch("django_qstash.handlers._emit_signal"),
        ):
            result = webhook.execute_task(payload)

        assert result == "plain result"

    def test_handle_request_unexpected_error_stores_result(self, webhook):
        """An unexpected error after the payload is parsed stores an INTERNAL_ERROR."""
        request = Mock(spec=HttpRequest)
        request.body = json.dumps(
            {"function": "test_func", "module": "test_module", "args": [], "kwargs": {}}
        ).encode()
        request.headers = {"Upstash-Signature": "valid", "Upstash-Message-Id": "123"}
        request.META = {"REMOTE_ADDR": "127.0.0.1"}
        request.build_absolute_uri.return_value = "https://example.com"

        with (
            patch.object(webhook, "verify_signature"),
            patch.object(webhook, "execute_task", side_effect=ValueError("kaboom")),
            patch("django_qstash.handlers.store_task_result") as mock_store,
        ):
            response, status = webhook.handle_request(request)

        assert status == 500
        assert response["error_type"] == "InternalServerError"
        mock_store.assert_called_once()
        assert mock_store.call_args[1]["status"] == TaskStatus.INTERNAL_ERROR


def _signed_request(message_id="dup-1"):
    request = Mock(spec=HttpRequest)
    request.body = json.dumps(
        {"function": "test_func", "module": "test_module", "args": [], "kwargs": {}}
    ).encode()
    request.headers = {
        "Upstash-Signature": "valid",
        "Upstash-Message-Id": message_id,
    }
    request.META = {"REMOTE_ADDR": "127.0.0.1"}
    request.build_absolute_uri.return_value = "https://example.com"
    return request


class TestIdempotency:
    """Redelivery of an already-succeeded message is skipped (at-least-once)."""

    @pytest.fixture
    def webhook(self):
        return QStashWebhook()

    def test_duplicate_success_is_skipped(self, webhook):
        from django_qstash.results.services import store_task_result

        store_task_result(
            task_id="dup-1",
            task_name="test_module.test_func",
            status=TaskStatus.SUCCESS,
            result="prior",
        )
        request = _signed_request("dup-1")
        with (
            patch.object(webhook, "verify_signature"),
            patch.object(webhook, "execute_task") as mock_execute,
        ):
            response, status = webhook.handle_request(request)

        assert status == 200
        assert response["status"] == "duplicate"
        mock_execute.assert_not_called()

    def test_prior_failure_still_executes(self, webhook):
        """A prior non-success row does not suppress execution (retries work)."""
        from django_qstash.results.services import store_task_result

        store_task_result(
            task_id="dup-2",
            task_name="test_module.test_func",
            status=TaskStatus.EXECUTION_ERROR,
            traceback="boom",
        )
        request = _signed_request("dup-2")
        with (
            patch.object(webhook, "verify_signature"),
            patch.object(webhook, "execute_task", return_value="ok") as mock_execute,
        ):
            response, status = webhook.handle_request(request)

        assert status == 200
        assert response["status"] == "success"
        mock_execute.assert_called_once()

    @override_settings(DJANGO_QSTASH_DEDUP_SUCCESSFUL=False)
    def test_dedup_disabled_re_executes(self, webhook):
        from django_qstash.results.services import store_task_result

        store_task_result(
            task_id="dup-3",
            task_name="test_module.test_func",
            status=TaskStatus.SUCCESS,
            result="prior",
        )
        request = _signed_request("dup-3")
        with (
            patch.object(webhook, "verify_signature"),
            patch.object(webhook, "execute_task", return_value="ok") as mock_execute,
        ):
            response, status = webhook.handle_request(request)

        assert status == 200
        assert response["status"] == "success"
        mock_execute.assert_called_once()


class TestEnsureHttps:
    """Tests for the _ensure_https() method."""

    def test_http_to_https(self):
        """Test basic http to https conversion."""
        webhook = QStashWebhook()
        webhook.force_https = True
        assert (
            webhook._ensure_https("http://example.com/path")
            == "https://example.com/path"
        )

    def test_uppercase_http_to_https(self):
        """Test uppercase HTTP to https conversion (case-insensitive)."""
        webhook = QStashWebhook()
        webhook.force_https = True
        assert (
            webhook._ensure_https("HTTP://example.com/path")
            == "https://example.com/path"
        )

    def test_mixed_case_http_to_https(self):
        """Test mixed case Http to https conversion."""
        webhook = QStashWebhook()
        webhook.force_https = True
        assert (
            webhook._ensure_https("Http://example.com/path")
            == "https://example.com/path"
        )

    def test_already_https_unchanged(self):
        """Test that already https URLs remain unchanged."""
        webhook = QStashWebhook()
        webhook.force_https = True
        assert (
            webhook._ensure_https("https://example.com/path")
            == "https://example.com/path"
        )

    def test_force_https_disabled_preserves_http(self):
        """Test that http is preserved when force_https is disabled."""
        webhook = QStashWebhook()
        webhook.force_https = False
        assert (
            webhook._ensure_https("http://example.com/path")
            == "http://example.com/path"
        )

    def test_preserves_query_params(self):
        """Test that query parameters are preserved, including http URLs in query strings."""
        webhook = QStashWebhook()
        webhook.force_https = True
        url = "http://example.com/path?redirect=http://other.com&foo=bar"
        result = webhook._ensure_https(url)
        assert result == "https://example.com/path?redirect=http://other.com&foo=bar"

    def test_preserves_port(self):
        """Test that port numbers are preserved."""
        webhook = QStashWebhook()
        webhook.force_https = True
        assert (
            webhook._ensure_https("http://example.com:8080/path")
            == "https://example.com:8080/path"
        )

    def test_preserves_fragment(self):
        """Test that URL fragments are preserved."""
        webhook = QStashWebhook()
        webhook.force_https = True
        assert (
            webhook._ensure_https("http://example.com/path#section")
            == "https://example.com/path#section"
        )
