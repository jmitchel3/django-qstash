from __future__ import annotations

from django.db import models


class TaskStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    RETRY = "RETRY", "Retry"
    SUCCESS = "SUCCESS", "Success"
    EXECUTION_ERROR = "EXECUTION_ERROR", "Execution Error"
    INTERNAL_ERROR = "INTERNAL_ERROR", "Internal Error"
    OTHER_ERROR = "OTHER_ERROR", "Other Error"
    UNKNOWN = "UNKNOWN", "Unknown"
