from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin
from django.contrib import messages
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.html import format_html

from django_qstash.results.services import requeue_task_result

from .models import TaskResult

# admin.ModelAdmin is generic for type checkers (django-stubs) but is not
# subscriptable at runtime, so only parametrize it under TYPE_CHECKING.
if TYPE_CHECKING:
    _TaskResultAdminBase = admin.ModelAdmin[TaskResult]
else:
    _TaskResultAdminBase = admin.ModelAdmin


@admin.register(TaskResult)
class TaskResultAdmin(_TaskResultAdminBase):
    actions = ["requeue_selected"]
    date_hierarchy = "date_done"
    list_display = [
        "task_name",
        "status",
        "attempt",
        "correlation_short",
        "task_id_short",
        "parent_task_id_short",
        "duration_display",
        "date_done",
    ]
    list_filter = ["status", "task_name", "date_done"]
    readonly_fields = (
        "task_name",
        "status",
        "date_done",
        "task_id",
        "date_created",
        "function_path",
        "correlation_id",
        "parent_task_id",
        "attempt",
        "duration_ms",
        "formatted_args",
        "formatted_kwargs",
        "formatted_result",
        "formatted_traceback",
    )
    fields = readonly_fields
    search_fields = [
        "task_name",
        "task_id",
        "function_path",
        "correlation_id",
        "parent_task_id",
    ]

    @admin.display(description="Task ID")
    def task_id_short(self, obj: TaskResult) -> str:
        return self._short_id(obj.task_id)

    @admin.display(description="Correlation")
    def correlation_short(self, obj: TaskResult) -> str:
        return self._short_id(obj.correlation_id)

    @admin.display(description="Parent")
    def parent_task_id_short(self, obj: TaskResult) -> str:
        return self._short_id(obj.parent_task_id)

    @admin.display(description="Duration")
    def duration_display(self, obj: TaskResult) -> str:
        if obj.duration_ms is None:
            return "-"
        return f"{obj.duration_ms / 1000:.3f}s"

    @admin.display(description="Args")
    def formatted_args(self, obj: TaskResult) -> str:
        return self._preformatted(obj.args)

    @admin.display(description="Kwargs")
    def formatted_kwargs(self, obj: TaskResult) -> str:
        return self._preformatted(obj.kwargs)

    @admin.display(description="Result")
    def formatted_result(self, obj: TaskResult) -> str:
        return self._preformatted(obj.result)

    @admin.display(description="Traceback")
    def formatted_traceback(self, obj: TaskResult) -> str:
        return self._preformatted(obj.traceback)

    @admin.action(description="Requeue selected failed tasks")
    def requeue_selected(
        self,
        request: HttpRequest,
        queryset: QuerySet[TaskResult],
    ) -> None:
        requeued = 0
        failed = 0
        for task_result in queryset:
            try:
                requeue_task_result(task_result)
            except ValueError:
                failed += 1
            else:
                requeued += 1
        if requeued:
            self.message_user(
                request,
                f"Requeued {requeued} task result(s).",
                messages.SUCCESS,
            )
        if failed:
            self.message_user(
                request,
                f"Skipped {failed} task result(s) that cannot be requeued.",
                messages.WARNING,
            )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def _short_id(self, value: str) -> str:
        if not value:
            return "-"
        if len(value) <= 16:
            return value
        return f"{value[:8]}...{value[-6:]}"

    def _preformatted(self, value: object) -> str:
        if value in (None, ""):
            return "-"
        return format_html("<pre style='white-space: pre-wrap'>{}</pre>", value)
