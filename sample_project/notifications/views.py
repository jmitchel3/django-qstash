from __future__ import annotations

from datetime import timedelta

from django.shortcuts import render
from django.utils import timezone

from django_qstash.results.models import TaskResult
from django_qstash.results.services import calculate_task_metrics

from .tasks import send_reminder_notification
from .tasks import send_welcome_notification

# Create your views here.


def register_user(request):
    if request.method == "POST":
        email = request.POST.get("email")

        # Send immediate welcome
        welcome_task = send_welcome_notification.delay(email)

        # Schedule reminder for 24 hours later
        reminder_task = send_reminder_notification.apply_async(
            args=[email],
            countdown=86400,  # 24 hours
        )

        return render(
            request,
            "notifications/registration_success.html",
            {
                "email": email,
                "welcome_task_id": welcome_task.task_id,
                "reminder_task_id": reminder_task.task_id,
            },
        )

    return render(request, "notifications/register.html")


def task_dashboard(request):
    # Get all tasks from the last 24 hours
    recent_tasks = TaskResult.objects.filter(
        date_done__gte=timezone.now() - timedelta(days=1)
    ).order_by("-date_done")
    metrics = calculate_task_metrics(window_seconds=86400)

    return render(
        request,
        "notifications/task_dashboard.html",
        {
            "tasks": recent_tasks,
            "metrics": metrics,
        },
    )
