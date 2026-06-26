from __future__ import annotations

from typing import Any
from typing import cast

from django.core.management.base import BaseCommand
from django.core.management.base import CommandParser
from qstash.dlq import DlqFilter

from django_qstash.client import qstash_client


def _compact_filter(options: dict[str, Any]) -> dict[str, Any] | None:
    filters = {
        "message_id": options.get("message_id"),
        "url": options.get("url"),
        "url_group": options.get("url_group"),
        "queue": options.get("queue"),
        "schedule_id": options.get("schedule_id"),
        "response_status": options.get("response_status"),
        "label": options.get("label"),
    }
    compacted = {
        key: value
        for key, value in filters.items()
        if value is not None and value != ""
    }
    return compacted or None


def _display(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


def _truncate(value: Any, max_length: int = 240) -> str:
    text = _display(value)
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


class Command(BaseCommand):
    """Inspect and delete QStash dead letter queue messages."""

    help = "List, inspect, and delete QStash DLQ messages"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--list", action="store_true", help="List DLQ messages")
        parser.add_argument("--get", help="Fetch one DLQ message by DLQ ID")
        parser.add_argument("--delete", help="Delete one DLQ message by DLQ ID")
        parser.add_argument(
            "--delete-many",
            nargs="+",
            help="Delete multiple DLQ messages by DLQ ID",
        )
        parser.add_argument("--count", type=int, help="Maximum number of DLQ messages")
        parser.add_argument("--cursor", help="Pagination cursor for --list")
        parser.add_argument("--message-id", help="Filter by QStash message ID")
        parser.add_argument("--url", help="Filter by destination URL")
        parser.add_argument("--url-group", help="Filter by URL group")
        parser.add_argument("--queue", help="Filter by queue name")
        parser.add_argument("--schedule-id", help="Filter by schedule ID")
        parser.add_argument("--response-status", type=int, help="Filter by HTTP status")
        parser.add_argument("--label", help="Filter by QStash label")

    def _write_message(self, message: Any, include_body: bool = False) -> None:
        self.stdout.write(
            f"\nDLQ ID: {_display(getattr(message, 'dlq_id', None))}"
            f"\n  Message ID: {_display(getattr(message, 'message_id', None))}"
            f"\n  Status: {_display(getattr(message, 'response_status', None))}"
            f"\n  URL: {_display(getattr(message, 'url', None))}"
            f"\n  Queue: {_display(getattr(message, 'queue', None))}"
            f"\n  Schedule ID: {_display(getattr(message, 'schedule_id', None))}"
            f"\n  Label: {_display(getattr(message, 'label', None))}"
            f"\n  Response: {_truncate(getattr(message, 'response_body', None))}"
        )
        if include_body:
            self.stdout.write(
                f"  Body: {_truncate(getattr(message, 'body', None), max_length=1000)}"
            )

    def _list_messages(self, options: dict[str, Any]) -> None:
        response = qstash_client.dlq.list(
            cursor=options.get("cursor"),
            count=options.get("count"),
            filter=cast("DlqFilter | None", _compact_filter(options)),
        )
        self.stdout.write(
            self.style.SUCCESS(f"Found {len(response.messages)} DLQ messages")
        )
        for message in response.messages:
            self._write_message(message)
        if response.cursor:
            self.stdout.write(f"\nNext cursor: {response.cursor}")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            if options.get("list"):
                self._list_messages(options)
                return

            if options.get("get"):
                message = qstash_client.dlq.get(options["get"])
                self._write_message(message, include_body=True)
                return

            if options.get("delete"):
                qstash_client.dlq.delete(options["delete"])
                self.stdout.write(
                    self.style.SUCCESS(f"Deleted DLQ message {options['delete']}")
                )
                return

            if options.get("delete_many"):
                deleted = qstash_client.dlq.delete_many(options["delete_many"])
                self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} DLQ messages"))
                return

            self.stdout.write(
                self.style.ERROR(
                    "Please specify --list, --get, --delete, or --delete-many"
                )
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"An error occurred: {str(e)}"))
