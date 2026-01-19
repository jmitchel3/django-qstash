from __future__ import annotations

import json
import logging
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.http import HttpRequest

from django_qstash.exceptions import TaskError
from django_qstash.handlers import QStashWebhook

pytestmark = pytest.mark.django_db


class TestPayloadSizeValidation:
    """Tests for payload size validation security feature."""

    @pytest.fixture
    def webhook(self):
        return QStashWebhook()

    def test_payload_exceeds_max_size(self, webhook):
        """Test that payloads exceeding max size are rejected."""
        # Create a request with a payload larger than the default 1MB limit
        large_payload = "x" * (1024 * 1024 + 1)  # 1MB + 1 byte
        request = Mock(spec=HttpRequest)
        request.body = large_payload.encode()
        request.headers = {"Upstash-Signature": "valid", "Upstash-Message-Id": "123"}
        request.META = {"REMOTE_ADDR": "127.0.0.1"}
        request.build_absolute_uri.return_value = "https://example.com"

        response, status = webhook.handle_request(request)

        assert status == 400
        assert response["status"] == "error"
        assert response["error_type"] == "PayloadError"
        assert "exceeds maximum allowed size" in response["error"]

    def test_payload_within_max_size(self, webhook):
        """Test that payloads within max size are accepted."""
        payload = json.dumps(
            {"function": "test_func", "module": "test_module", "args": [], "kwargs": {}}
        )
        request = Mock(spec=HttpRequest)
        request.body = payload.encode()
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

    @patch("django_qstash.handlers.DJANGO_QSTASH_MAX_PAYLOAD_SIZE", 100)
    def test_custom_max_payload_size(self):
        """Test that custom max payload size setting is respected."""
        webhook = QStashWebhook()
        payload = "x" * 101  # 101 bytes, exceeds custom limit of 100
        request = Mock(spec=HttpRequest)
        request.body = payload.encode()
        request.headers = {"Upstash-Signature": "valid", "Upstash-Message-Id": "123"}
        request.META = {"REMOTE_ADDR": "127.0.0.1"}
        request.build_absolute_uri.return_value = "https://example.com"

        response, status = webhook.handle_request(request)

        assert status == 400
        assert "exceeds maximum allowed size" in response["error"]


class TestTaskAllowlistValidation:
    """Tests for task allowlist validation security feature."""

    @pytest.fixture
    def webhook(self):
        return QStashWebhook()

    def test_unregistered_task_rejected(self, webhook):
        """Test that unregistered tasks are rejected."""
        payload = Mock(
            function_path="nonexistent.module.fake_task",
            args=[],
            kwargs={},
        )

        with patch(
            "django_qstash.handlers.discover_tasks", return_value=["some.other.task"]
        ):
            with pytest.raises(TaskError, match="is not a registered @stashed_task"):
                webhook.execute_task(payload)

    def test_registered_task_accepted(self, webhook):
        """Test that registered tasks are accepted."""
        payload = Mock(
            function_path="tests.discovery.tasks.debug_task",
            args=[1, 2],
            kwargs={},
        )

        with patch(
            "django_qstash.handlers.discover_tasks",
            return_value=["tests.discovery.tasks.debug_task"],
        ):
            with patch("django_qstash.handlers.utils.import_string") as mock_import:
                mock_func = Mock()
                mock_func.actual_func = lambda x, y: x + y
                mock_import.return_value = mock_func

                result = webhook.execute_task(payload)

        assert result == 3

    def test_unregistered_task_via_handle_request(self, webhook):
        """Test that unregistered tasks are rejected through the full request flow."""
        payload = json.dumps(
            {
                "function": "malicious_func",
                "module": "attacker.module",
                "args": [],
                "kwargs": {},
            }
        )
        request = Mock(spec=HttpRequest)
        request.body = payload.encode()
        request.headers = {"Upstash-Signature": "valid", "Upstash-Message-Id": "123"}
        request.META = {"REMOTE_ADDR": "127.0.0.1"}
        request.build_absolute_uri.return_value = "https://example.com"

        with (
            patch.object(webhook, "verify_signature"),
            patch(
                "django_qstash.handlers.discover_tasks",
                return_value=["safe.module.task"],
            ),
        ):
            response, status = webhook.handle_request(request)

        assert status == 422
        assert response["status"] == "error"
        assert response["error_type"] == "TaskError"
        assert "is not a registered @stashed_task" in response["error"]


class TestAuditLogging:
    """Tests for audit logging security feature."""

    @pytest.fixture
    def webhook(self):
        return QStashWebhook()

    def test_audit_log_on_webhook_received(self, webhook, caplog):
        """Test that webhook_received is logged with required fields."""
        payload = json.dumps(
            {"function": "test_func", "module": "test_module", "args": [], "kwargs": {}}
        )
        request = Mock(spec=HttpRequest)
        request.body = payload.encode()
        request.headers = {
            "Upstash-Signature": "valid",
            "Upstash-Message-Id": "test-msg-123",
        }
        request.META = {"REMOTE_ADDR": "192.168.1.100"}
        request.build_absolute_uri.return_value = "https://example.com"

        with (
            caplog.at_level(logging.INFO, logger="django_qstash.audit"),
            patch.object(webhook, "verify_signature"),
            patch.object(webhook, "execute_task") as mock_execute,
        ):
            mock_execute.return_value = "result"
            webhook.handle_request(request)

        # Check that audit log was generated
        audit_records = [r for r in caplog.records if r.name == "django_qstash.audit"]
        assert len(audit_records) == 1
        record = audit_records[0]

        assert record.message == "webhook_received"
        assert record.message_id == "test-msg-123"
        assert record.source_ip == "192.168.1.100"
        assert record.task_path == "test_module.test_func"
        assert record.content_length == len(payload.encode())
        # Also verify correlation_id is included
        assert hasattr(record, "correlation_id")

    def test_audit_log_with_x_forwarded_for(self, webhook, caplog):
        """Test that X-Forwarded-For header is used for source IP."""
        payload = json.dumps(
            {"function": "test_func", "module": "test_module", "args": [], "kwargs": {}}
        )
        request = Mock(spec=HttpRequest)
        request.body = payload.encode()
        request.headers = {
            "Upstash-Signature": "valid",
            "Upstash-Message-Id": "123",
            "x-forwarded-for": "203.0.113.50, 70.41.3.18, 150.172.238.178",
        }
        request.META = {"REMOTE_ADDR": "127.0.0.1"}
        request.build_absolute_uri.return_value = "https://example.com"

        with (
            caplog.at_level(logging.INFO, logger="django_qstash.audit"),
            patch.object(webhook, "verify_signature"),
            patch.object(webhook, "execute_task") as mock_execute,
        ):
            mock_execute.return_value = "result"
            webhook.handle_request(request)

        audit_records = [r for r in caplog.records if r.name == "django_qstash.audit"]
        record = audit_records[0]
        # Should use the first IP from X-Forwarded-For
        assert record.source_ip == "203.0.113.50"

    def test_no_audit_log_on_payload_size_error(self, webhook, caplog):
        """Test that audit log is not generated when payload size validation fails."""
        large_payload = "x" * (1024 * 1024 + 1)
        request = Mock(spec=HttpRequest)
        request.body = large_payload.encode()
        request.headers = {"Upstash-Signature": "valid", "Upstash-Message-Id": "123"}
        request.META = {"REMOTE_ADDR": "127.0.0.1"}
        request.build_absolute_uri.return_value = "https://example.com"

        with caplog.at_level(logging.INFO, logger="django_qstash.audit"):
            webhook.handle_request(request)

        # No audit log should be generated for payload size errors
        audit_records = [r for r in caplog.records if r.name == "django_qstash.audit"]
        assert len(audit_records) == 0

    def test_no_audit_log_on_signature_error(self, webhook, caplog):
        """Test that audit log is not generated when signature verification fails."""
        payload = json.dumps(
            {"function": "test_func", "module": "test_module", "args": [], "kwargs": {}}
        )
        request = Mock(spec=HttpRequest)
        request.body = payload.encode()
        request.headers = {"Upstash-Message-Id": "123"}  # Missing signature
        request.META = {"REMOTE_ADDR": "127.0.0.1"}
        request.build_absolute_uri.return_value = "https://example.com"

        with caplog.at_level(logging.INFO, logger="django_qstash.audit"):
            webhook.handle_request(request)

        # No audit log should be generated for signature errors
        audit_records = [r for r in caplog.records if r.name == "django_qstash.audit"]
        assert len(audit_records) == 0
