from __future__ import annotations

import json
import logging
from datetime import datetime
from datetime import timezone
from typing import Any


def get_correlation_id() -> str:
    """Get the current correlation ID from context.

    This function imports correlation_id from handlers to avoid circular imports.
    """
    try:
        from django_qstash.handlers import correlation_id

        return correlation_id.get("")
    except ImportError:
        return ""


class StructuredLogFilter(logging.Filter):
    """A logging filter that adds correlation_id and timestamp to log records.

    This filter enriches log records with:
    - correlation_id: The current request/task correlation ID from context
    - timestamp: ISO 8601 formatted UTC timestamp

    Usage in Django settings:
        LOGGING = {
            'filters': {
                'correlation_id': {
                    '()': 'django_qstash.logging.StructuredLogFilter',
                },
            },
            'handlers': {
                'console': {
                    'filters': ['correlation_id'],
                    ...
                },
            },
        }
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Add correlation_id and timestamp to the log record."""
        record.correlation_id = get_correlation_id()
        record.timestamp = datetime.now(timezone.utc).isoformat()
        return True


class JSONFormatter(logging.Formatter):
    """A logging formatter that outputs structured JSON logs.

    This formatter produces JSON-formatted log entries suitable for
    log aggregation systems like ELK, Splunk, or CloudWatch.

    Output format:
        {
            "timestamp": "2024-01-15T12:34:56.789012+00:00",
            "level": "INFO",
            "logger": "django_qstash.handlers",
            "message": "task_completed",
            "correlation_id": "msg_abc123",
            ...extra fields...
        }

    Usage in Django settings:
        LOGGING = {
            'formatters': {
                'json': {
                    '()': 'django_qstash.logging.JSONFormatter',
                },
            },
            ...
        }
    """

    # Standard LogRecord attributes to exclude from extra fields
    RESERVED_ATTRS = frozenset(
        {
            "args",
            "asctime",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "taskName",
            "thread",
            "threadName",
            "timestamp",
            "correlation_id",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as a JSON string."""
        log_data: dict[str, Any] = {
            "timestamp": getattr(
                record, "timestamp", datetime.now(timezone.utc).isoformat()
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", ""),
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add stack info if present
        if record.stack_info:
            log_data["stack_info"] = record.stack_info

        # Include extra fields from the log record
        for key, value in record.__dict__.items():
            if key not in self.RESERVED_ATTRS and not key.startswith("_"):
                # Try to serialize the value, fall back to string representation
                try:
                    json.dumps(value)
                    log_data[key] = value
                except (TypeError, ValueError):
                    log_data[key] = str(value)

        return json.dumps(log_data)


def configure_structured_logging(logger_name: str = "django_qstash") -> None:
    """Configure a logger with structured JSON logging.

    This is a convenience function for programmatically enabling
    structured logging for django-qstash.

    Args:
        logger_name: The logger name to configure. Defaults to 'django_qstash'.

    Usage:
        from django_qstash.logging import configure_structured_logging
        configure_structured_logging()
    """
    logger = logging.getLogger(logger_name)

    # Create a handler with JSON formatting
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    handler.addFilter(StructuredLogFilter())

    # Remove existing handlers and add the structured one
    logger.handlers = []
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
