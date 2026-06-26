from __future__ import annotations

from django import forms

from django_qstash.discovery.fields import TaskChoiceField
from django_qstash.schedules.models import TaskSchedule


class TaskScheduleForm(forms.ModelForm):
    task = TaskChoiceField()

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
