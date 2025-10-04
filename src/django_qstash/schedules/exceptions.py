from __future__ import annotations

from django.core.exceptions import ValidationError


class InvalidDurationStringValidationError(ValidationError):
    """Invalid duration string."""


class InvalidCronStringValidationError(ValidationError):
    """Invalid cron string."""
