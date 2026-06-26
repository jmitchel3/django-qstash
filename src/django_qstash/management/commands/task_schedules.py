from __future__ import annotations

import json
import logging
from typing import Any
from typing import cast

from django.apps import apps
from django.core.management.base import BaseCommand
from django.core.management.base import CommandParser
from django.db import models

from django_qstash.callbacks import get_callback_url
from django_qstash.client import qstash_client

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Management command to list and sync QStash schedules."""

    help = "List and sync schedules from QStash"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--list",
            action="store_true",
            help="List schedules from QStash",
        )
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Sync schedules from QStash to local database",
        )
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Do not ask for confirmation",
        )

    def get_task_schedule_model(self) -> type[models.Model] | None:
        """Get the TaskSchedule model if available."""
        try:
            return apps.get_model("django_qstash_schedules", "TaskSchedule")
        except LookupError:
            self.stdout.write(
                self.style.ERROR(
                    "Django QStash Schedules not installed.\n"
                    "Add `django_qstash.schedules` to INSTALLED_APPS and run migrations."
                )
            )
            return None

    def sync_schedules(self, schedules: list[Any]) -> None:
        """Sync remote schedules to local database."""
        TaskSchedule = self.get_task_schedule_model()
        if TaskSchedule is None:
            return

        for schedule in schedules:
            try:
                body = json.loads(schedule.body)
                task_name = body.get("task_name", "Unnamed Task")
                function = f"{body['module']}.{body['function']}"

                obj, created = cast(Any, TaskSchedule).objects.update_or_create(
                    schedule_id=schedule.schedule_id,
                    defaults={
                        "name": task_name,
                        "task": function,
                        "cron": schedule.cron,
                        "args": body.get("args", []),
                        "kwargs": body.get("kwargs", {}),
                    },
                )
                status = "Created" if created else "Updated"
                logger.info(
                    "%s schedule: %s (%s)", status, task_name, schedule.schedule_id
                )
            except Exception:
                logger.exception("Failed to sync schedule %s", schedule.schedule_id)

    def handle(self, *args: Any, **options: Any) -> None:
        auto_confirm = options.get("no_input")
        if not (options.get("sync") or options.get("list")):
            self.stdout.write(
                self.style.ERROR("Please specify either --list or --sync option")
            )
            return

        try:
            destination = get_callback_url()
            schedules = qstash_client.schedule.list()

            self.stdout.write(
                self.style.SUCCESS(
                    f"Found {len(schedules)} remote schedules based on destination: {destination}"
                )
            )

            for schedule in schedules:
                body = json.loads(cast(str, schedule.body))
                task_name = body.get("task_name", "Unnamed Task")
                function = f"{body['module']}.{body['function']}"

                self.stdout.write(
                    f"\nSchedule ID: {schedule.schedule_id}"
                    f"\n  Task: {task_name} ({function})"
                    f"\n  Cron: {schedule.cron}"
                    f"\n  Destination: {schedule.destination}"
                    f"\n  Retries: {schedule.retries}"
                    f"\n  Status: {'Paused' if schedule.paused else 'Active'}"
                )

            if options.get("sync"):
                user_input = input("Do you want to sync remote schedules? (y/n): ")
                if user_input.lower() == "y" or auto_confirm:
                    self.sync_schedules(schedules)
                else:
                    self.stdout.write(self.style.ERROR("Sync cancelled"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"An error occurred: {str(e)}"))
