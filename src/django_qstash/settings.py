from __future__ import annotations

import warnings

from django.conf import settings

QSTASH_TOKEN = getattr(settings, "QSTASH_TOKEN", None)
DJANGO_QSTASH_DOMAIN = getattr(settings, "DJANGO_QSTASH_DOMAIN", None)
DJANGO_QSTASH_WEBHOOK_PATH = getattr(
    settings, "DJANGO_QSTASH_WEBHOOK_PATH", "/qstash/webhook/"
)

# Observability settings
DJANGO_QSTASH_ENABLE_STRUCTURED_LOGGING = getattr(
    settings, "DJANGO_QSTASH_ENABLE_STRUCTURED_LOGGING", False
)
DJANGO_QSTASH_LOG_TASK_ARGS = getattr(
    settings, "DJANGO_QSTASH_LOG_TASK_ARGS", False  # False by default for security
)
DJANGO_QSTASH_EMIT_SIGNALS = getattr(settings, "DJANGO_QSTASH_EMIT_SIGNALS", True)

# Security settings
# Maximum payload size in bytes (default: 1MB)
DJANGO_QSTASH_MAX_PAYLOAD_SIZE = getattr(
    settings, "DJANGO_QSTASH_MAX_PAYLOAD_SIZE", 1024 * 1024
)

if not QSTASH_TOKEN or not DJANGO_QSTASH_DOMAIN:
    warnings.warn(
        "DJANGO_SETTINGS_MODULE (settings.py required) requires QSTASH_TOKEN and DJANGO_QSTASH_DOMAIN should be set for QStash functionality",
        RuntimeWarning,
        stacklevel=2,
    )
