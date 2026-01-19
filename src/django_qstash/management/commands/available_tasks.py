from __future__ import annotations

from typing import Any
from typing import cast

from django.core.management.base import BaseCommand
from django.core.management.base import CommandParser

from django_qstash.discovery.utils import TaskInfo
from django_qstash.discovery.utils import _discover_tasks_impl
from django_qstash.discovery.utils import discover_tasks


class Command(BaseCommand):
    help = "View all available tasks"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--locations",
            action="store_true",
            help="Only show task paths",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        locations_only: bool = options["locations"] or False
        self.stdout.write("Available tasks:")
        _discover_tasks_impl.cache_clear()
        if locations_only:
            tasks_locations = cast(list[str], discover_tasks(locations_only=True))
            for task_location in tasks_locations:
                self.stdout.write(f"\t- {self.style.SQL_FIELD(task_location)}")
        else:
            tasks_info = cast(list[TaskInfo], discover_tasks(locations_only=False))
            for task_info in tasks_info:
                name = task_info["name"] or ""
                field_label = task_info["field_label"]
                location = task_info["location"]
                self.stdout.write(
                    f"  Name: {self.style.SQL_FIELD(name)}\n"
                    f"  Location: {self.style.SQL_FIELD(location)}\n"
                    f"  Field Label: {self.style.SQL_FIELD(field_label)}"
                )
                self.stdout.write("")
