from __future__ import annotations

from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from django_qstash.settings import DJANGO_QSTASH_DOMAIN
from django_qstash.settings import DJANGO_QSTASH_WEBHOOK_PATH


def validate_domain(domain: str) -> str:
    """
    Validate and normalize a domain for callback URLs.

    Args:
        domain: The domain string to validate

    Returns:
        Normalized domain string (scheme + netloc only)

    Raises:
        ImproperlyConfigured: If domain is invalid
    """
    # Strip whitespace
    domain = domain.strip()

    # Check for empty domain
    if not domain:
        raise ImproperlyConfigured("DJANGO_QSTASH_DOMAIN cannot be empty")

    # Check for invalid protocols (any protocol that's not http/https)
    if "://" in domain and not domain.startswith(("http://", "https://")):
        # Extract the protocol for the error message
        protocol = domain.split("://")[0]
        raise ImproperlyConfigured(
            f"Invalid protocol in DJANGO_QSTASH_DOMAIN: {protocol}"
        )

    # Add protocol if missing for parsing
    if not domain.startswith(("http://", "https://")):
        force_https = getattr(settings, "DJANGO_QSTASH_FORCE_HTTPS", True)
        protocol = "https" if force_https else "http"
        domain = f"{protocol}://{domain}"

    # Parse and validate
    try:
        parsed = urlparse(domain)
    except Exception as e:
        raise ImproperlyConfigured(f"Invalid DJANGO_QSTASH_DOMAIN: {e}")

    # Validate scheme
    if parsed.scheme not in ("http", "https"):
        raise ImproperlyConfigured(
            f"Invalid protocol in DJANGO_QSTASH_DOMAIN: {parsed.scheme}"
        )

    # Validate hostname exists
    if not parsed.netloc:
        raise ImproperlyConfigured("DJANGO_QSTASH_DOMAIN must include a hostname")

    # Check for suspicious patterns
    if ".." in parsed.netloc or "@" in parsed.netloc:
        raise ImproperlyConfigured("Invalid characters in DJANGO_QSTASH_DOMAIN")

    # Reconstruct clean URL (scheme + netloc only)
    return f"{parsed.scheme}://{parsed.netloc}"


def get_callback_url() -> str:
    """
    Get the callback URL based on the settings.
    """
    if DJANGO_QSTASH_DOMAIN is None:
        raise ImproperlyConfigured("DJANGO_QSTASH_DOMAIN is not set")
    if DJANGO_QSTASH_WEBHOOK_PATH is None:
        raise ImproperlyConfigured("DJANGO_QSTASH_WEBHOOK_PATH is not set")

    callback_domain = validate_domain(DJANGO_QSTASH_DOMAIN)
    webhook_path = DJANGO_QSTASH_WEBHOOK_PATH.strip("/")

    return f"{callback_domain}/{webhook_path}/"
