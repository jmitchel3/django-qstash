from __future__ import annotations

import django
from django import forms

from django_qstash.discovery.fields import TaskChoiceField
from django_qstash.schedules.models import TaskSchedule

# Django 5.0 deprecates the implicit "http" scheme for forms.URLField and emits
# RemovedInDjango60Warning unless assume_scheme is set. The kwarg does not exist
# on Django 4.2, so only pass it where it is supported.
_URLFIELD_SCHEME_KWARGS = {"assume_scheme": "https"} if django.VERSION >= (5, 0) else {}


def _url_formfield(field_name: str) -> forms.URLField:
    model_field = TaskSchedule._meta.get_field(field_name)
    return forms.URLField(
        max_length=model_field.max_length,
        required=not model_field.blank,
        label=model_field.verbose_name,
        help_text=model_field.help_text,
        **_URLFIELD_SCHEME_KWARGS,
    )


class TaskScheduleForm(forms.ModelForm):
    task = TaskChoiceField()
    callback = _url_formfield("callback")
    failure_callback = _url_formfield("failure_callback")

    class Meta:
        model = TaskSchedule
        fields = [
            "name",
            "task",
            "task_name",
            "args",
            "kwargs",
            "schedule_id",
            "cron",
            "retries",
            "retry_delay",
            "timeout",
            "delay",
            "queue",
            "headers",
            "callback",
            "callback_headers",
            "failure_callback",
            "failure_callback_headers",
            "flow_control",
            "label",
            "redact",
        ]

    def clean(self):
        cleaned_data = super().clean()
        # If task_name is not provided, use the task value
        if not cleaned_data.get("task_name") and cleaned_data.get("task"):
            cleaned_data["task_name"] = cleaned_data["task"]
        return cleaned_data
