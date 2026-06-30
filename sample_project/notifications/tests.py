"""Eager-mode tests for the notifications example app.

These show how to test django-qstash tasks the Celery way: flip
``DJANGO_QSTASH_ALWAYS_EAGER`` on (or call ``.apply()``) so ``.delay()`` /
``.apply_async()`` run inline and return an ``EagerResult``. No QStash token,
domain, broker, or network is needed, so the whole signup workflow,
chaining, and retry behavior are exercised together in plain unit tests.
"""

from __future__ import annotations

import pytest

from .tasks import CALL_LOG
from .tasks import record_signup_metric
from .tasks import send_reminder_notification
from .tasks import send_welcome_notification
from .tasks import sync_user_to_crm

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def eager_mode(settings):
    """Run every task inline (no QStash, no network) for the whole module."""
    settings.DJANGO_QSTASH_ALWAYS_EAGER = True
    CALL_LOG.clear()
    yield
    CALL_LOG.clear()


class TestEagerExecution:
    def test_welcome_runs_inline(self):
        """.delay() runs inline under eager mode and returns the value."""
        result = send_welcome_notification.delay("user@example.com")
        assert result.successful() is True
        assert result.result["type"] == "welcome"
        assert ("welcome", "user@example.com") in CALL_LOG

    def test_apply_needs_no_eager_setting(self):
        """.apply() always runs inline, independent of any setting."""
        result = send_reminder_notification.apply(args=["user@example.com"])
        assert result.get()["type"] == "reminder"


class TestChaining:
    def test_metric_runs_after_welcome(self):
        """link= chains the metric task after the welcome email succeeds."""
        send_welcome_notification.apply_async(
            args=["user@example.com"],
            link=record_signup_metric.s("user@example.com"),
        )
        labels = [name for name, _ in CALL_LOG]
        assert labels == ["welcome", "metric"]


class TestRetry:
    def test_retries_until_success(self):
        """sync_user_to_crm retries past transient failures, then succeeds."""
        result = sync_user_to_crm.apply(
            args=["user@example.com"], kwargs={"fail_times": 2}
        )
        assert result.successful() is True
        # 2 failed attempts + 1 success = 3 CRM calls, succeeding on attempt #3.
        assert result.result["attempts"] == 3
        assert [name for name, _ in CALL_LOG] == ["crm_attempt"] * 3

    def test_gives_up_after_max_retries(self):
        """Exhausting max_retries surfaces the transient error as a failure."""
        result = sync_user_to_crm.apply(
            args=["user@example.com"], kwargs={"fail_times": 99}
        )
        assert result.failed() is True
        # max_retries=3 -> attempts at retries 0,1,2,3 then the exc propagates.
        assert isinstance(result.result, Exception)
        assert len([n for n, _ in CALL_LOG if n == "crm_attempt"]) == 4
