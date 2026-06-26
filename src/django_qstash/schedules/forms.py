from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import cast

import django
from django import forms
from django.db import models

from django_qstash.discovery.fields import TaskChoiceField
from django_qstash.schedules.models import TaskSchedule

# forms.ModelForm is generic for type checkers (django-stubs) but is not
# subscriptable at runtime, so only parametrize it under TYPE_CHECKING.
if TYPE_CHECKING:
    _TaskScheduleFormBase = forms.ModelForm[TaskSchedule]
else:
    _TaskScheduleFormBase = forms.ModelForm

# Django 5.0 deprecates the implicit "http" scheme for forms.URLField and emits
# RemovedInDjango60Warning unless assume_scheme is set. The kwarg does not exist
# on Django 4.2, so only pass it where it is supported.
_URLFIELD_SCHEME_KWARGS: dict[str, Any] = (
    {"assume_scheme": "https"} if django.VERSION >= (5, 0) else {}
)


def _url_formfield(field_name: str) -> forms.URLField:
    # get_field returns a union; the targeted fields are concrete URL model
    # fields, so narrow to Field to access its attributes.
    model_field = cast(
        "models.Field[Any, Any]", TaskSchedule._meta.get_field(field_name)
    )
    return forms.URLField(
        max_length=model_field.max_length,
        required=not model_field.blank,
        label=model_field.verbose_name,
        help_text=model_field.help_text,
        **_URLFIELD_SCHEME_KWARGS,
    )


class TaskScheduleForm(_TaskScheduleFormBase):
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

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean() or {}
        # If task_name is not provided, use the task value
        if not cleaned_data.get("task_name") and cleaned_data.get("task"):
            cleaned_data["task_name"] = cleaned_data["task"]
        return cleaned_data
