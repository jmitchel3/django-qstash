from __future__ import annotations

from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_qstash.callbacks import get_callback_url
from django_qstash.callbacks import validate_domain


class TestValidateDomain:
    def test_valid_https_domain(self):
        assert validate_domain("https://example.com") == "https://example.com"

    def test_valid_http_domain(self, settings):
        settings.DJANGO_QSTASH_FORCE_HTTPS = False
        assert validate_domain("http://example.com") == "http://example.com"

    def test_domain_without_protocol_uses_https(self, settings):
        settings.DJANGO_QSTASH_FORCE_HTTPS = True
        assert validate_domain("example.com") == "https://example.com"

    def test_domain_without_protocol_uses_http_when_force_https_false(self, settings):
        settings.DJANGO_QSTASH_FORCE_HTTPS = False
        assert validate_domain("example.com") == "http://example.com"

    def test_domain_with_port(self):
        assert validate_domain("https://example.com:8080") == "https://example.com:8080"

    def test_strips_path(self):
        # Path should be stripped, only domain kept
        assert validate_domain("https://example.com/path") == "https://example.com"

    def test_strips_path_with_multiple_segments(self):
        assert (
            validate_domain("https://example.com/path/to/endpoint")
            == "https://example.com"
        )

    def test_strips_whitespace(self):
        assert validate_domain("  https://example.com  ") == "https://example.com"

    def test_empty_domain_raises(self):
        with pytest.raises(ImproperlyConfigured, match="cannot be empty"):
            validate_domain("")

    def test_whitespace_only_domain_raises(self):
        with pytest.raises(ImproperlyConfigured, match="cannot be empty"):
            validate_domain("   ")

    def test_invalid_protocol_raises(self):
        with pytest.raises(ImproperlyConfigured, match="Invalid protocol"):
            validate_domain("ftp://example.com")

    def test_file_protocol_raises(self):
        with pytest.raises(ImproperlyConfigured, match="Invalid protocol"):
            validate_domain("file:///etc/passwd")

    def test_path_traversal_raises(self):
        with pytest.raises(ImproperlyConfigured, match="Invalid characters"):
            validate_domain("https://example..com")

    def test_credential_injection_raises(self):
        with pytest.raises(ImproperlyConfigured, match="Invalid characters"):
            validate_domain("https://user:pass@example.com")

    def test_username_only_injection_raises(self):
        with pytest.raises(ImproperlyConfigured, match="Invalid characters"):
            validate_domain("https://user@example.com")

    def test_preserves_subdomain(self):
        assert validate_domain("https://api.example.com") == "https://api.example.com"

    def test_preserves_complex_subdomain(self):
        assert (
            validate_domain("https://api.v1.staging.example.com")
            == "https://api.v1.staging.example.com"
        )


@pytest.mark.parametrize(
    "domain,webhook_path,expected",
    [
        # Domain without protocol
        (
            "example.com",
            "webhook",
            "https://example.com/webhook/",
        ),
        # Domain with http protocol
        (
            "http://example.com",
            "webhook",
            "http://example.com/webhook/",
        ),
        # Domain with https protocol
        (
            "https://example.com",
            "webhook",
            "https://example.com/webhook/",
        ),
        # Domain with trailing slash
        (
            "example.com/",
            "webhook",
            "https://example.com/webhook/",
        ),
        # Webhook path with leading slash
        (
            "example.com",
            "/webhook",
            "https://example.com/webhook/",
        ),
        # Webhook path with trailing slash
        (
            "example.com",
            "webhook/",
            "https://example.com/webhook/",
        ),
        # Complex path
        (
            "example.com",
            "api/v1/webhook",
            "https://example.com/api/v1/webhook/",
        ),
    ],
)
def test_get_callback_url(domain, webhook_path, expected):
    with (
        patch("django_qstash.callbacks.DJANGO_QSTASH_DOMAIN", domain),
        patch("django_qstash.callbacks.DJANGO_QSTASH_WEBHOOK_PATH", webhook_path),
    ):
        assert get_callback_url() == expected
