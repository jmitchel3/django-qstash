from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone

from django_qstash.db.models import TaskStatus


class TaskResult(models.Model):
    id = models.UUIDField(
        primary_key=True, default=uuid.uuid1, editable=False, unique=True
    )
    task_id = models.CharField(max_length=255, db_index=True)
    task_name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=50,
        choices=TaskStatus.choices,
        default=TaskStatus.PENDING,
    )
    date_created = models.DateTimeField(default=timezone.now)
    date_done = models.DateTimeField(null=True)
    result = models.JSONField(null=True)
    traceback = models.TextField(blank=True, null=True)
    function_path = models.TextField(blank=True, null=True)
    args = models.JSONField(null=True)
    kwargs = models.JSONField(null=True)

    class Meta:
        app_label = "django_qstash_results"
        ordering = ["-date_done"]

    def __str__(self) -> str:
        return f"{self.task_name} ({self.task_id})"
