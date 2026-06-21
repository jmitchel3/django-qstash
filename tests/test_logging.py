from __future__ import annotations

import builtins
import json
import logging

from django_qstash.logging import JSONFormatter
from django_qstash.logging import configure_structured_logging
from django_qstash.logging import get_correlation_id


def _make_record(**extra):
    record = logging.LogRecord(
        name="django_qstash.test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="message",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_get_correlation_id_import_error(monkeypatch):
    """If handlers can't be imported, correlation id falls back to ''."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "django_qstash.handlers":
            raise ImportError("boom")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert get_correlation_id() == ""


def test_format_includes_stack_info():
    formatter = JSONFormatter()
    record = _make_record(stack_info="Traceback stack here")
    data = json.loads(formatter.format(record))
    assert data["stack_info"] == "Traceback stack here"


def test_format_non_serializable_extra_falls_back_to_str():
    formatter = JSONFormatter()
    sentinel = object()
    record = _make_record(weird=sentinel)
    data = json.loads(formatter.format(record))
    assert data["weird"] == str(sentinel)


def test_configure_structured_logging():
    logger_name = "django_qstash_test_configure"
    configure_structured_logging(logger_name)
    logger = logging.getLogger(logger_name)
    try:
        assert len(logger.handlers) == 1
        handler = logger.handlers[0]
        assert isinstance(handler.formatter, JSONFormatter)
        assert logger.level == logging.INFO
    finally:
        logger.handlers = []
