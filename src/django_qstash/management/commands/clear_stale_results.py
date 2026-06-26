from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandParser

from django_qstash.results.tasks import clear_stale_results_task

DJANGO_QSTASH_RESULT_TTL = getattr(settings, "DJANGO_QSTASH_RESULT_TTL", 604800)


class Command(BaseCommand):
    help = f"""Clears stale task results older than\n
    {DJANGO_QSTASH_RESULT_TTL} seconds (settings.DJANGO_QSTASH_RESULT_TTL)"""

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Do not ask for confirmation",
        )
        parser.add_argument(
            "--since",
            type=int,
            help="The number of seconds ago to clear results for",
        )
        parser.add_argument(
            "--delay", action="store_true", help="Offload request using django_qstash"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        delay = options["delay"]
        no_input = options["no_input"]
        since = options.get("since") or DJANGO_QSTASH_RESULT_TTL
        user_confirm = not no_input
        if not delay:
            clear_stale_results_task(
                since=since, user_confirm=user_confirm, stdout=self.stdout
            )
        else:
            clear_stale_results_task.delay(
                since=since, user_confirm=user_confirm, stdout=self.stdout
            )
