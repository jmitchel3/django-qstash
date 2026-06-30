from __future__ import annotations

import logging

from django_qstash import shared_task

logger = logging.getLogger(__name__)

# In-memory call log so the eager-mode tests can assert what ran without a
# database round-trip. A real app would inspect the results backend instead.
CALL_LOG: list[tuple[str, str]] = []


class TransientCRMError(Exception):
    """A retryable error, e.g. a CRM API returning 503."""


@shared_task
def send_welcome_notification(user_email: str) -> dict:
    """Pretend to send a welcome email.

    This runs inside the QStash webhook, not in the request/response cycle.
    In a real app you would send an actual email here, e.g.::

        from django.core.mail import send_mail
        send_mail("Welcome!", "Thanks for registering.", None, [user_email])
    """
    logger.info("Sending welcome email to %s", user_email)
    CALL_LOG.append(("welcome", user_email))
    return {
        "status": "success",
        "email": user_email,
        "type": "welcome",
        "message": "Welcome email sent successfully",
    }


@shared_task
def send_reminder_notification(user_email: str) -> dict:
    """Pretend to send a reminder, scheduled for ~24h after signup."""
    logger.info("Sending reminder email to %s", user_email)
    CALL_LOG.append(("reminder", user_email))
    return {
        "status": "success",
        "email": user_email,
        "type": "reminder",
        "message": "Reminder sent successfully",
    }


@shared_task
def record_signup_metric(user_email: str) -> dict:
    """Follow-up task chained after the welcome email succeeds (``link=``).

    Demonstrates sequential chaining: this only runs once
    ``send_welcome_notification`` has completed successfully.
    """
    logger.info("Recording signup metric for %s", user_email)
    CALL_LOG.append(("metric", user_email))
    return {"status": "success", "email": user_email, "type": "metric"}


@shared_task(bind=True, max_retries=3)
def sync_user_to_crm(self, user_email: str, fail_times: int = 0) -> dict:
    """Sync a user to an external CRM, retrying on transient failures.

    Demonstrates ``self.retry()``: the simulated CRM is flaky and 503s
    ``fail_times`` times before succeeding. Each failure aborts the current run
    and reschedules it (a fresh QStash message in production; an inline re-run in
    eager mode), incrementing ``self.request.retries``. Once ``max_retries`` is
    exhausted the ``TransientCRMError`` propagates as the task's failure.
    """
    attempt = self.request.retries
    CALL_LOG.append(("crm_attempt", user_email))
    if attempt < fail_times:
        logger.warning(
            "CRM sync for %s failed (attempt %s), retrying", user_email, attempt
        )
        raise self.retry(
            exc=TransientCRMError("CRM returned 503"),
            countdown=5,
        )
    logger.info("CRM sync for %s succeeded on attempt %s", user_email, attempt)
    return {"status": "success", "email": user_email, "attempts": attempt + 1}
