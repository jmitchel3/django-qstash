from __future__ import annotations

from django.apps import AppConfig


class SchedulesConfig(AppConfig):
    name = "django_qstash.schedules"
    label = "django_qstash_schedules"
    verbose_name = "django_qstash_schedules"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        import django_qstash.schedules.signals  # noqa: F401
