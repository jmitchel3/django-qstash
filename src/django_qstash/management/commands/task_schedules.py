from __future__ import annotations

import logging
from typing import Any

from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser

from django_qstash.callbacks import get_callback_url
from django_qstash.client import qstash_client

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """List QStash schedules for this app's callback URL, or import them.

    Only schedules whose destination is exactly this environment's callback URL
    (``DJANGO_QSTASH_DOMAIN`` + ``DJANGO_QSTASH_WEBHOOK_PATH``) are shown or
    imported. ``--sync`` is a one-way, remote-to-local import: it writes local
    ``TaskSchedule`` rows and never creates, updates, pauses, or deletes
    anything in QStash.
    """

    help = (
        "List QStash schedules targeting this app's callback URL (--list, "
        "read-only) or import them into local TaskSchedule rows (--sync, "
        "remote-to-local, no QStash writes)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--list",
            action="store_true",
            help="List remote schedules for this callback URL (read-only)",
        )
        parser.add_argument(
            "--sync",
            action="store_true",
            help=(
                "Import remote schedules for this callback URL into the local "
                "database. Does not write to QStash."
            ),
        )
        parser.add_argument(
            "--no-input",
            "--noinput",
            action="store_true",
            dest="no_input",
            help="Do not prompt for confirmation (never reads stdin)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not (options.get("sync") or options.get("list")):
            raise CommandError("Please specify either --list or --sync option")

        if options.get("sync"):
            try:
                apps.get_model("django_qstash_schedules", "TaskSchedule")
            except LookupError:
                raise CommandError(
                    "Django QStash Schedules not installed. Add "
                    "`django_qstash.schedules` to INSTALLED_APPS and run migrations."
                )

        try:
            destination = get_callback_url()
        except ImproperlyConfigured as exc:
            raise CommandError(str(exc)) from exc
        try:
            remote = list(qstash_client.schedule.list())
        except Exception as exc:
            raise CommandError(f"Failed to list QStash schedules: {exc}") from exc

        schedules = [
            s for s in remote if getattr(s, "destination", None) == destination
        ]
        skipped = len(remote) - len(schedules)

        self.stdout.write(
            self.style.SUCCESS(
                f"Found {len(schedules)} remote schedules for destination: {destination}"
            )
        )
        if skipped:
            self.stdout.write(
                f"Ignored {skipped} schedules with other destinations "
                "(other environments or applications)."
            )

        for schedule in schedules:
            self._describe(schedule)

        if not options.get("sync"):
            return

        if not schedules:
            self.stdout.write("Nothing to import.")
            return

        if not options.get("no_input"):
            try:
                answer = input(
                    "Import these schedules into the local database? (y/n): "
                )
            except EOFError:
                raise CommandError(
                    "No input available for confirmation; pass --no-input to "
                    "import unattended."
                )
            if answer.strip().lower() != "y":
                self.stdout.write(self.style.WARNING("Sync cancelled"))
                return

        self._import(schedules)

    def _describe(self, schedule: Any) -> None:
        from django_qstash.schedules.services import ScheduleImportError
        from django_qstash.schedules.services import parse_remote_schedule_body

        try:
            body = parse_remote_schedule_body(schedule)
            task = (
                f"{body.get('task_name') or 'Unnamed Task'} "
                f"({body['module']}.{body['function']})"
            )
        except ScheduleImportError as exc:
            task = f"<not a django-qstash task payload: {exc}>"

        self.stdout.write(
            f"\nSchedule ID: {schedule.schedule_id}"
            f"\n  Task: {task}"
            f"\n  Cron: {schedule.cron}"
            f"\n  Destination: {schedule.destination}"
            f"\n  Retries: {schedule.retries}"
            f"\n  Status: {'Paused' if schedule.paused else 'Active'}"
        )

    def _import(self, schedules: list[Any]) -> None:
        from django_qstash.schedules.services import import_remote_schedule

        created = updated = 0
        failures: list[tuple[str, str]] = []
        for schedule in schedules:
            try:
                instance, was_created = import_remote_schedule(schedule)
            except Exception as exc:
                logger.exception("Failed to import schedule %s", schedule.schedule_id)
                failures.append((str(schedule.schedule_id), str(exc)))
                continue
            if was_created:
                created += 1
            else:
                updated += 1
            logger.info(
                "%s schedule: %s (%s)",
                "Created" if was_created else "Updated",
                instance.name,
                schedule.schedule_id,
            )

        self.stdout.write(
            f"\nImported {created + updated} of {len(schedules)} schedules "
            f"({created} created, {updated} updated, {len(failures)} failed)."
        )
        if failures:
            for schedule_id, reason in failures:
                self.stderr.write(f"  {schedule_id}: {reason}")
            raise CommandError(
                f"{len(failures)} of {len(schedules)} schedules failed to import"
            )
