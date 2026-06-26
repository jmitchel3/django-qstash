from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin

from .models import TaskResult

# admin.ModelAdmin is generic for type checkers (django-stubs) but is not
# subscriptable at runtime, so only parametrize it under TYPE_CHECKING.
if TYPE_CHECKING:
    _TaskResultAdminBase = admin.ModelAdmin[TaskResult]
else:
    _TaskResultAdminBase = admin.ModelAdmin


@admin.register(TaskResult)
class TaskResultAdmin(_TaskResultAdminBase):
    readonly_fields = [
        "task_name",
        "status",
        "date_done",
        "result",
        "traceback",
        "args",
        "kwargs",
        "task_id",
        "date_created",
        "function_path",
    ]
    search_fields = ["task_name", "task_id", "function_path"]
    list_display = ["task_name", "function_path", "status", "date_done"]
    list_filter = ["status", "date_done"]
