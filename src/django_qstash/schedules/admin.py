from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django.contrib import admin
from qstash.schedule import Schedule

from django_qstash.schedules import services
from django_qstash.schedules.forms import TaskScheduleForm
from django_qstash.schedules.models import TaskSchedule

# admin.ModelAdmin is generic for type checkers (django-stubs) but is not
# subscriptable at runtime, so only parametrize it under TYPE_CHECKING.
if TYPE_CHECKING:
    _TaskScheduleAdminBase = admin.ModelAdmin[TaskSchedule]
else:
    _TaskScheduleAdminBase = admin.ModelAdmin


@admin.register(TaskSchedule)
class TaskScheduleAdmin(_TaskScheduleAdminBase):
    list_display = [
        "schedule_id",
        "display_task_name",
        "display_task_path",
        "cron",
        "queue",
        "label",
        "is_active",
    ]
    readonly_fields = [
        "schedule_id",
        "task_name",
        "get_qstash_schedule_details",
        "paused_at",
        "resumed_at",
        "active_at",
    ]
    form = TaskScheduleForm

    fieldsets = [
        (
            "Name",
            {
                "fields": ["name", "schedule_id", "is_active"],
            },
        ),
        (
            "Task Selection",
            {
                "fields": ["task", "task_name"],
            },
        ),
        (
            "Arguments",
            {
                "fields": ["args", "kwargs"],
            },
        ),
        (
            "Schedule",
            {
                "fields": [
                    "cron",
                    "retries",
                    "retry_delay",
                    "timeout",
                    "delay",
                    "queue",
                    "label",
                ],
            },
        ),
        (
            "Headers and Callbacks",
            {
                "fields": [
                    "headers",
                    "callback",
                    "callback_headers",
                    "failure_callback",
                    "failure_callback_headers",
                ],
                "classes": ["collapse"],
            },
        ),
        (
            "Flow Control and Redaction",
            {
                "fields": ["flow_control", "redact"],
                "classes": ["collapse"],
            },
        ),
        (
            "QStash Metadata",
            {
                "fields": [
                    "paused_at",
                    "resumed_at",
                    "active_at",
                    "get_qstash_schedule_details",
                ],
                "classes": ["collapse"],
            },
        ),
    ]

    @admin.display(description="Raw")
    def get_qstash_schedule_details(
        self, obj: TaskSchedule
    ) -> str | Schedule | dict[Any, Any] | None:
        if not obj.schedule_id:
            return "No schedule ID yet"
        return services.get_task_schedule_from_qstash(obj, as_dict=True)

    @admin.display(description="Task Name", ordering="name")
    def display_task_name(self, obj: TaskSchedule) -> str:
        return obj.name or obj.task_name or obj.task

    @admin.display(description="Task Path", ordering="task")
    def display_task_path(self, obj: TaskSchedule) -> str:
        return obj.task or obj.task_name
