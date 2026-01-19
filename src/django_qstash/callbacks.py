from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from django_qstash.settings import DJANGO_QSTASH_DOMAIN
from django_qstash.settings import DJANGO_QSTASH_WEBHOOK_PATH


def get_callback_url() -> str:
    """
    Get the callback URL based on the settings.
    """
    if DJANGO_QSTASH_DOMAIN is None:
        raise ImproperlyConfigured("DJANGO_QSTASH_DOMAIN is not set")
    if DJANGO_QSTASH_WEBHOOK_PATH is None:
        raise ImproperlyConfigured("DJANGO_QSTASH_WEBHOOK_PATH is not set")
    callback_domain = DJANGO_QSTASH_DOMAIN.rstrip("/")
    if not callback_domain.startswith(("http://", "https://")):
        force_https = getattr(settings, "DJANGO_QSTASH_FORCE_HTTPS", True)
        protocol = "https" if force_https else "http"
        callback_domain = f"{protocol}://{callback_domain}"
    webhook_path = DJANGO_QSTASH_WEBHOOK_PATH.strip("/")
    return f"{callback_domain}/{webhook_path}/"
