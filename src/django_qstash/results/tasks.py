from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.apps import apps
from django.conf import settings
from django.utils import timezone

from django_qstash import stashed_task
from django_qstash.db.models import TaskStatus

DJANGO_QSTASH_RESULT_TTL = getattr(settings, "DJANGO_QSTASH_RESULT_TTL", 604800)

logger = logging.getLogger(__name__)


@stashed_task(name="Cleanup Task Results")
def clear_stale_results_task(
    since: int | None = None,
    stdout: Any = None,
    user_confirm: bool = False,
    exclude_errors: bool = True,
    *args: Any,
    **options: Any,
) -> None:
    delta_seconds = since or DJANGO_QSTASH_RESULT_TTL
    cutoff_date = timezone.now() - timedelta(seconds=delta_seconds)
    TaskResult = None
    try:
        TaskResult = apps.get_model("django_qstash_results", "TaskResult")
    except LookupError as e:
        msg = "Django QStash Results not installed.\nAdd `django_qstash.results` to INSTALLED_APPS and run migrations."
        if stdout is not None:
            stdout.write(msg)
        logger.exception(msg)
        raise e
    qs_to_delete = TaskResult.objects.filter(date_done__lt=cutoff_date)
    if exclude_errors:
        qs_to_delete = qs_to_delete.exclude(
            status__in=[
                TaskStatus.EXECUTION_ERROR,
                TaskStatus.INTERNAL_ERROR,
                TaskStatus.OTHER_ERROR,
            ]
        )

    if user_confirm:
        user_input = input("Are you sure? (Y/n): ")
        if f"{user_input}".lower() != "y":
            msg = "Skipping deletion"
            if stdout is not None:
                stdout.write(msg)
            logger.info(msg)
            return

    if not qs_to_delete.exists():
        msg = "No stale Django QStash task results found"
        if stdout is not None:
            stdout.write(msg)
        else:
            logger.info(msg)
        return
    delete_msg = f"Deleting {qs_to_delete.count()} task results older than {cutoff_date} ({DJANGO_QSTASH_RESULT_TTL} seconds)"
    if stdout is not None:
        stdout.write(delete_msg)
    else:
        logger.info(delete_msg)
    try:
        deleted_count, _ = qs_to_delete.delete()
        msg = f"Successfully deleted {deleted_count} stale results."
        if stdout is not None:
            stdout.write(msg)
        else:
            logger.info(msg)
    except Exception as e:
        msg = f"Error deleting stale results: {e}"
        if stdout is not None:
            stdout.write(msg)
        logger.exception(msg)
        raise e


@stashed_task(name="Clear Task Error Results")
def clear_task_errors_task(
    since: int | None = None,
    stdout: Any = None,
    user_confirm: bool = False,
    *args: Any,
    **options: Any,
) -> None:
    clear_stale_results_task(
        since=since, stdout=stdout, user_confirm=user_confirm, exclude_errors=False
    )
