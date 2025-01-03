from __future__ import annotations

from django_qstash.settings import DJANGO_QSTASH_DOMAIN
from django_qstash.settings import DJANGO_QSTASH_WEBHOOK_PATH


def get_callback_url() -> str:
    """
    Get the callback URL based on the settings.
    """
    callback_domain = DJANGO_QSTASH_DOMAIN.rstrip("/")
    if not callback_domain.startswith(("http://", "https://")):
        callback_domain = f"https://{callback_domain}"
    webhook_path = DJANGO_QSTASH_WEBHOOK_PATH.strip("/")
    return f"{callback_domain}/{webhook_path}/"