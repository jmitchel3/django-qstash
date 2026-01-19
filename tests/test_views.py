from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.test import Client
from django.test import RequestFactory

from django_qstash.views import qstash_webhook_view


@pytest.mark.django_db
class TestQStashWebhook:
    def setup_method(self):
        self.client = Client()
        self.url = "/qstash/webhook/"

    @patch("django_qstash.views.QStashWebhook")
    def test_valid_webhook_request(self, mock_webhook_class):
        """Test webhook with valid signature and payload"""
        # Setup mock webhook instance
        mock_webhook = mock_webhook_class.return_value
        mock_webhook.handle_request.return_value = ({"status": "success"}, 200)

        payload = {
            "function": "sample_task",
            "module": "tests.test_tasks",
            "args": [2, 3],
            "kwargs": {},
            "task_name": "test_task",
        }

        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
            headers={"upstash-signature": "mock-signature"},
        )

        # Verify response
        assert response.status_code == 200
        response_data = json.loads(response.content)
        assert response_data["status"] == "success"

        # Verify webhook was called correctly
        mock_webhook.handle_request.assert_called_once()

    @patch("django_qstash.views.QStashWebhook")
    def test_invalid_request(self, mock_webhook_class):
        """Test webhook with invalid request"""
        # Setup mock webhook instance
        mock_webhook = mock_webhook_class.return_value
        mock_webhook.handle_request.return_value = ({"error": "Invalid request"}, 400)

        response = self.client.post(
            self.url,
            data="invalid json",
            content_type="application/json",
            headers={"upstash-signature": "mock-signature"},
        )

        assert response.status_code == 400
        response_data = json.loads(response.content)
        assert "error" in response_data


class TestContentTypeValidation:
    @pytest.fixture
    def factory(self):
        return RequestFactory()

    def test_rejects_missing_content_type(self, factory):
        """Test webhook rejects request with missing content type."""
        # Create a POST request with explicit empty content type
        request = factory.generic(
            "POST", "/qstash/webhook/", data=b"{}", content_type=""
        )
        response = qstash_webhook_view(request)
        assert response.status_code == 415
        response_data = json.loads(response.content)
        assert response_data["error_type"] == "InvalidContentType"
        assert "none" in response_data["error"]

    def test_rejects_text_plain(self, factory):
        """Test webhook rejects text/plain content type."""
        request = factory.post(
            "/qstash/webhook/", data=b"{}", content_type="text/plain"
        )
        response = qstash_webhook_view(request)
        assert response.status_code == 415
        response_data = json.loads(response.content)
        assert response_data["error_type"] == "InvalidContentType"

    def test_rejects_form_urlencoded(self, factory):
        """Test webhook rejects application/x-www-form-urlencoded content type."""
        request = factory.post(
            "/qstash/webhook/",
            data=b"key=value",
            content_type="application/x-www-form-urlencoded",
        )
        response = qstash_webhook_view(request)
        assert response.status_code == 415
        response_data = json.loads(response.content)
        assert response_data["error_type"] == "InvalidContentType"

    @patch("django_qstash.views.QStashWebhook")
    def test_accepts_application_json(self, mock_webhook_class, factory):
        """Test webhook accepts application/json content type."""
        mock_webhook = mock_webhook_class.return_value
        mock_webhook.handle_request.return_value = ({"status": "success"}, 200)

        request = factory.post(
            "/qstash/webhook/",
            data=b'{"module": "test", "function": "test", "args": [], "kwargs": {}}',
            content_type="application/json",
        )
        response = qstash_webhook_view(request)
        # Should not be 415 (passes content type validation)
        assert response.status_code != 415

    @patch("django_qstash.views.QStashWebhook")
    def test_accepts_json_with_charset(self, mock_webhook_class, factory):
        """Test webhook accepts application/json with charset parameter."""
        mock_webhook = mock_webhook_class.return_value
        mock_webhook.handle_request.return_value = ({"status": "success"}, 200)

        request = factory.post(
            "/qstash/webhook/",
            data=b'{"module": "test", "function": "test", "args": [], "kwargs": {}}',
            content_type="application/json; charset=utf-8",
        )
        response = qstash_webhook_view(request)
        # Should not be 415 (passes content type validation)
        assert response.status_code != 415

    @patch("django_qstash.views.QStashWebhook")
    def test_case_insensitive_content_type(self, mock_webhook_class, factory):
        """Test webhook accepts content type with different casing (Application/JSON)."""
        mock_webhook = mock_webhook_class.return_value
        mock_webhook.handle_request.return_value = ({"status": "success"}, 200)

        request = factory.post(
            "/qstash/webhook/",
            data=b'{"module": "test", "function": "test", "args": [], "kwargs": {}}',
            content_type="Application/JSON",
        )
        response = qstash_webhook_view(request)
        # Should not be 415 (passes content type validation)
        assert response.status_code != 415
