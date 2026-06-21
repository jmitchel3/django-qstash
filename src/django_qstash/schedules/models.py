from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models
from django.utils import timezone

from django_qstash.discovery.models import TaskField
from django_qstash.schedules.validators import validate_cron_expression
from django_qstash.schedules.validators import validate_duration_string

DJANGO_QSTASH_DOMAIN = getattr(settings, "DJANGO_QSTASH_DOMAIN", None)
DJANGO_QSTASH_WEBHOOK_PATH = getattr(
    settings, "DJANGO_QSTASH_WEBHOOK_PATH", "/qstash/webhook/"
)


class TaskSchedule(models.Model):
    """
    A model that represents a QStash Schedule for any given django-qstash Task.
    """

    schedule_id = models.CharField(
        max_length=255,
        unique=True,
        blank=True,
        null=True,
        verbose_name="Schedule ID",
        help_text="The schedule ID stored in QStash",
        db_index=True,
    )
    name = models.CharField(
        max_length=200,
        verbose_name="Name",
        help_text="Short Description For This Task Schedule",
    )
    task = TaskField()
    task_name = models.CharField(
        max_length=255, help_text="Original Python location of task", blank=True
    )
    args = models.JSONField(
        blank=True,
        default=list,
        verbose_name="Positional Arguments",
        help_text='JSON encoded positional arguments (Example: ["arg1", "arg2"])',
    )
    kwargs = models.JSONField(
        blank=True,
        default=dict,
        verbose_name="Keyword Arguments",
        help_text='JSON encoded keyword arguments (Example: {"argument": "value"})',
    )
    # Configured for Upstash Cron
    # https://upstash.com/docs/qstash/api/schedules/create#param-upstash-cron
    cron = models.CharField(
        max_length=255,
        default="*/5 * * * *",
        validators=[validate_cron_expression],
        verbose_name="Cron Expression",
        help_text="Cron expression for scheduling the task",
    )
    # Configured for Upstash Retries
    # https://upstash.com/docs/qstash/api/schedules/create#param-upstash-retries
    retries = models.IntegerField(
        default=3,
        verbose_name="Retries",
        validators=[MaxValueValidator(5)],
        help_text="Number of times to retry the task if it fails",
    )
    # Configured for Upstash Timeout
    # https://upstash.com/docs/qstash/api/schedules/create#param-upstash-timeout
    timeout = models.CharField(
        max_length=10,
        default="60s",
        verbose_name="Timeout",
        validators=[validate_duration_string],
        help_text="Duration string for task timeout (e.g., '1s', '5m', '2h'). "
        "See Max HTTP Connection Timeout on QStash pricing page for allowed values for your Upstash account.",
    )
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    active_at = models.DateTimeField(null=True, blank=True, default=timezone.now)
    is_paused = models.BooleanField(default=False)
    paused_at = models.DateTimeField(null=True, blank=True)
    is_resumed = models.BooleanField(default=False)
    resumed_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        current_task_name = self.task
        if not self.pk or self.task_name != current_task_name:
            self.task_name = current_task_name

        if not self.is_active:
            self.is_paused = True
            self.is_resumed = False
            self.paused_at = timezone.now()
            self.resumed_at = None
            self.active_at = None
            self.is_active = False
        else:
            self.is_paused = False
            self.is_resumed = True
            self.paused_at = None
            self.resumed_at = timezone.now()
            self.active_at = timezone.now()
        super().save(*args, **kwargs)

    def did_just_resume(self, delta_seconds: int = 60) -> bool:
        if not self.is_resumed or not self.resumed_at:
            return False
        now = timezone.now()
        delta_window = now - timedelta(seconds=delta_seconds)
        return self.resumed_at >= delta_window

    def did_just_pause(self, delta_seconds: int = 60) -> bool:
        if not self.is_paused or not self.paused_at:
            return False
        now = timezone.now()
        delta_window = now - timedelta(seconds=delta_seconds)
        return self.paused_at >= delta_window
