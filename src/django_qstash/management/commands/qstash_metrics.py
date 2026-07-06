from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand
from django.core.management.base import CommandParser

from django_qstash.results.services import calculate_task_metrics


class Command(BaseCommand):
    help = "Show django-qstash task metrics from the TaskResult table"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--window",
            type=int,
            default=3600,
            help="Lookback window in seconds (default: 3600)",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="Output metrics as JSON",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        metrics = calculate_task_metrics(window_seconds=options["window"])
        if options["as_json"]:
            self.stdout.write(json.dumps(metrics, sort_keys=True))
            return

        duration = metrics["duration_ms"]
        self.stdout.write(f"Window: {metrics['window_seconds']}s")
        self.stdout.write(f"Total tasks: {metrics['total']}")
        self.stdout.write(f"Success rate: {metrics['success_rate']:.2%}")
        self.stdout.write(f"p50 duration: {duration['p50'] or '-'} ms")
        self.stdout.write(f"p95 duration: {duration['p95'] or '-'} ms")
        self.stdout.write("Counts by status:")
        for status, count in sorted(metrics["counts_by_status"].items()):
            self.stdout.write(f"  {status}: {count}")
