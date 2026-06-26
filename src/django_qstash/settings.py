from __future__ import annotations

from typing import Any

from django.conf import settings as django_settings

# Documented django-qstash settings and their defaults. Every key here is
# resolved lazily against Django settings, so @override_settings and any runtime
# configuration change is always reflected (no import-time snapshotting).
DEFAULTS: dict[str, Any] = {
    # Core / required
    "QSTASH_TOKEN": None,
    "DJANGO_QSTASH_DOMAIN": None,
    "DJANGO_QSTASH_WEBHOOK_PATH": "/qstash/webhook/",
    # Observability
    "DJANGO_QSTASH_ENABLE_STRUCTURED_LOGGING": False,
    # False by default for security (avoid logging task payloads).
    "DJANGO_QSTASH_LOG_TASK_ARGS": False,
    "DJANGO_QSTASH_EMIT_SIGNALS": True,
    # Security: maximum webhook payload size in bytes (default: 1MB).
    "DJANGO_QSTASH_MAX_PAYLOAD_SIZE": 1024 * 1024,
    # When True (default), the webhook short-circuits redelivery of a message
    # whose task already succeeded, so at-least-once delivery does not re-run
    # side effects. Set False to always execute (e.g. for idempotent tasks).
    "DJANGO_QSTASH_DEDUP_SUCCESSFUL": True,
    # Testing / execution
    # When True, .delay()/.apply_async() run inline (Celery's ALWAYS_EAGER).
    "DJANGO_QSTASH_ALWAYS_EAGER": False,
    # Seconds between polls when AsyncResult.get() waits on the results backend.
    "DJANGO_QSTASH_RESULT_POLL_INTERVAL": 0.5,
}


class QStashSettings:
    """Lazy accessor for django-qstash settings.

    Reads from Django settings at attribute-access time and falls back to the
    documented defaults when a setting is not configured. Because nothing is
    captured at import time, ``@override_settings`` and runtime configuration
    changes take effect immediately and the library can be imported before
    Django settings are fully configured.

    Usage::

        from django_qstash.settings import qstash_settings

        if qstash_settings.DJANGO_QSTASH_ALWAYS_EAGER:
            ...
    """

    defaults = DEFAULTS

    def __getattr__(self, name: str) -> Any:
        if name not in self.defaults:
            raise AttributeError(f"Invalid django-qstash setting: {name!r}")
        return getattr(django_settings, name, self.defaults[name])


qstash_settings = QStashSettings()


def __getattr__(name: str) -> Any:
    """Module-level lazy access for backward compatibility (PEP 562).

    Lets ``from django_qstash.settings import QSTASH_TOKEN`` keep working while
    resolving the value live, so importers no longer snapshot a stale value at
    import time.
    """
    if name in DEFAULTS:
        return getattr(django_settings, name, DEFAULTS[name])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
