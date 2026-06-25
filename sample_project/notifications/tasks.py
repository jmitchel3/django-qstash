from __future__ import annotations

import logging

from django_qstash import shared_task

logger = logging.getLogger(__name__)


@shared_task
def send_welcome_notification(user_email: str) -> dict:
    """Pretend to send a welcome email.

    This runs inside the QStash webhook, not in the request/response cycle.
    In a real app you would send an actual email here, e.g.::

        from django.core.mail import send_mail
        send_mail("Welcome!", "Thanks for registering.", None, [user_email])
    """
    logger.info("Sending welcome email to %s", user_email)
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
    return {
        "status": "success",
        "email": user_email,
        "type": "reminder",
        "message": "Reminder sent successfully",
    }
