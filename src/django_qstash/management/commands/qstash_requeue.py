from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.core.management.base import CommandParser

from django_qstash.results.services import requeue_dlq_message
from django_qstash.results.services import requeue_task_result_by_id


class Command(BaseCommand):
    help = "Requeue a failed TaskResult row or QStash DLQ message"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--result-id",
            help="TaskResult UUID primary key to requeue",
        )
        parser.add_argument(
            "--task-id",
            help="QStash message id from a TaskResult row to requeue",
        )
        parser.add_argument(
            "--dlq-id",
            help="QStash DLQ id to requeue",
        )
        parser.add_argument(
            "--queue",
            help="Optional QStash queue to enqueue the replacement message into",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Allow requeueing a non-failed TaskResult",
        )
        parser.add_argument(
            "--delete-dlq",
            action="store_true",
            help="Delete the DLQ message after a successful requeue",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        identifiers = [
            value
            for value in (
                options.get("result_id"),
                options.get("task_id"),
                options.get("dlq_id"),
            )
            if value
        ]
        if len(identifiers) != 1:
            self.stdout.write(
                self.style.ERROR(
                    "Specify exactly one of --result-id, --task-id, or --dlq-id"
                )
            )
            return

        try:
            if options.get("dlq_id"):
                result = requeue_dlq_message(
                    options["dlq_id"],
                    delete_after_requeue=options["delete_dlq"],
                    queue=options.get("queue"),
                )
            else:
                result = requeue_task_result_by_id(
                    options.get("result_id") or options["task_id"],
                    queue=options.get("queue"),
                    force=options["force"],
                )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"An error occurred: {str(e)}"))
            return

        self.stdout.write(
            self.style.SUCCESS(
                "Requeued task as "
                f"{result.message_id} "
                f"(correlation {result.correlation_id})"
            )
        )
