from __future__ import annotations

import json
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser

from django_qstash.settings import qstash_settings
from django_qstash.utils import import_string


def load_specs(path: str) -> list[Any]:
    """Import ``path`` and return its specs (a list, or a callable returning one)."""
    try:
        target = import_string(path)
    except Exception as exc:
        raise CommandError(f"Could not import schedule specs {path!r}: {exc}") from exc
    specs = target() if callable(target) else target
    if isinstance(specs, (str, bytes)) or not hasattr(specs, "__iter__"):
        raise CommandError(f"{path!r} did not provide a list of schedule specs")
    return list(specs)


class Command(BaseCommand):
    help = (
        "Create or update this application's declared QStash schedules so the "
        "local TaskSchedule rows and QStash match the specs. Never deletes or "
        "adopts schedules outside the specs."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--specs",
            help=(
                "Dotted path to a list (or zero-arg callable) of ScheduleSpec "
                "objects or dicts. Defaults to DJANGO_QSTASH_SCHEDULE_SPECS."
            ),
        )
        parser.add_argument(
            "--namespace",
            help=(
                "Per-environment schedule id prefix. Defaults to "
                "DJANGO_QSTASH_SCHEDULE_NAMESPACE."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing locally or to QStash",
        )
        parser.add_argument(
            "--resync",
            action="store_true",
            help="Push every spec to QStash even when no drift is detected",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print the result as JSON",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from django_qstash.schedules.reconcile import reconcile_schedules

        path = options.get("specs") or qstash_settings.DJANGO_QSTASH_SCHEDULE_SPECS
        if not path:
            raise CommandError(
                "No schedule specs given. Pass --specs or set "
                "DJANGO_QSTASH_SCHEDULE_SPECS."
            )
        specs = load_specs(str(path))

        try:
            result = reconcile_schedules(
                specs,
                namespace=options.get("namespace"),
                dry_run=bool(options.get("dry_run")),
                resync=bool(options.get("resync")),
            )
        except (ImproperlyConfigured, ValueError, TypeError) as exc:
            raise CommandError(str(exc)) from exc

        if options.get("json"):
            self.stdout.write(json.dumps(result.to_dict(), indent=2, default=str))
        else:
            prefix = "[dry run] " if result.dry_run else ""
            self.stdout.write(
                f"{prefix}Namespace {result.namespace!r}, destination "
                f"{result.destination}"
            )
            for outcome in result.outcomes:
                line = f"  {outcome.action:<9} {outcome.schedule_id}"
                if outcome.changes:
                    line += f"  fields: {', '.join(outcome.changes)}"
                if outcome.remote_drift and outcome.action != "created":
                    line += f"  qstash: {'; '.join(outcome.remote_drift)}"
                if outcome.error:
                    line += f"  error: {outcome.error}"
                self.stdout.write(line)
            counts = result.counts()
            self.stdout.write(
                prefix + ", ".join(f"{count} {name}" for name, count in counts.items())
            )

        if not result.ok:
            raise CommandError(
                f"{len(result.failed)} of {len(result.outcomes)} schedules failed "
                "to reconcile; rerun to repair"
            )
