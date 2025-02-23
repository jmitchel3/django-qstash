from __future__ import annotations

import re

from django.utils.safestring import mark_safe

from django_qstash import cron
from django_qstash.schedules.exceptions import InvalidCronStringValidationError
from django_qstash.schedules.exceptions import InvalidDurationStringValidationError


def validate_duration_string(value):
    if not re.match(r"^\d+[smhd]$", value):
        raise InvalidDurationStringValidationError(
            'Invalid duration format. Must be a number followed by s (seconds), m (minutes), h (hours), or d (days). E.g., "60s", "5m", "2h", "7d"'
        )

    # Extract number and unit
    number = int(value[:-1])
    unit = value[-1]

    # Convert to days
    days = {
        "s": number / (24 * 60 * 60),  # seconds to days
        "m": number / (24 * 60),  # minutes to days
        "h": number / 24,  # hours to days
        "d": number,  # already in days
    }[unit]

    if days > 7:
        raise InvalidDurationStringValidationError(
            "Duration too long. Maximum allowed: 7 days (equivalent to: 604800s, 10080m, 168h, 7d)"
        )


def validate_cron_expression(value: str) -> None:
    """Validates a standard cron expression with 5 fields (minute, hour, day of month, month, day of week)."""
    parts = value.split()
    if len(parts) != 5:
        raise InvalidCronStringValidationError(
            'Invalid cron format. Must contain 5 fields: "minute hour day_of_month month day_of_week"'
        )

    field_descriptions = {
        "minute": "0-59",
        "hour": "0-23",
        "day_of_month": "1-31",
        "month": "1-12",
        "day_of_week": "0-6 (0=Sunday, 6=Saturday)",
    }
    field_label = {
        "minute": "minute",
        "hour": "hour",
        "day_of_month": "day of the month",
        "month": "month",
        "day_of_week": "day of the week",
    }
    patterns = {
        "minute": cron.minute_re,
        "hour": cron.hour_re,
        "day_of_month": cron.day_of_month_re,
        "month": cron.month_re,
        "day_of_week": cron.day_of_week_re,
    }

    for sub_value, (field, pattern) in zip(parts, patterns.items(), strict=True):
        if not re.match(pattern, sub_value):
            invalid_msg = f"""<b>{sub_value}</b> is not a valid {field_label[field]}. <br/>Must be in range {field_descriptions[field]}. <br/><a target="_blank" href="https://crontab.guru/">crontab.guru</a> is also helpful."""
            raise InvalidCronStringValidationError(mark_safe(invalid_msg))
