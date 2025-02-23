from __future__ import annotations

import json

from django.conf import settings
from django.core.mail import send_mail

from django_qstash import shared_task


@shared_task
def send_welcome_notification(user_email):
    try:
        # Simulate sending welcome email
        print(f"Sending welcome email to {user_email}")
        # In a real app, you'd use:
        # send_mail(
        #     'Welcome to Our App!',
        #     'Thank you for registering!',
        #     'from@example.com',
        #     [user_email],
        #     fail_silently=False,
        # )

        return json.dumps(
            {
                "status": "success",
                "email": user_email,
                "type": "welcome",
                "message": "Welcome email sent successfully",
            }
        )
    except Exception as e:
        return json.dumps(
            {"status": "error", "email": user_email, "type": "welcome", "error": str(e)}
        )


@shared_task
def send_reminder_notification(user_email):
    try:
        # Simulate sending reminder
        print(f"Sending reminder to {user_email}")
        # In a real app, you'd use:
        # send_mail(
        #     'Don\'t forget to complete your profile!',
        #     'Click here to complete your profile setup.',
        #     'from@example.com',
        #     [user_email],
        #     fail_silently=False,
        # )

        return json.dumps(
            {
                "status": "success",
                "email": user_email,
                "type": "reminder",
                "message": "Reminder sent successfully",
            }
        )
    except Exception as e:
        return json.dumps(
            {
                "status": "error",
                "email": user_email,
                "type": "reminder",
                "error": str(e),
            }
        )
