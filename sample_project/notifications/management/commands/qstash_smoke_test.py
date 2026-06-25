"""Round-trip smoke test for a fully-local django-qstash setup.

Enqueues a real task through QStash and waits for the result to be written
back via the webhook. This exercises the entire path:

    delay() -> QStash (dev server) -> webhook -> task runs -> TaskResult saved

Run it once the web server and the QStash dev server are both up:

    python manage.py qstash_smoke_test

Exit code is 0 on success, 1 on timeout/failure, so it is CI-friendly.
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from notifications.tasks import send_welcome_notification

from django_qstash.results.models import TaskResult


class Command(BaseCommand):
    help = "Enqueue a task and wait for the webhook to store its result."

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            default="smoke-test@example.com",
            help="Email passed to the sample task (default: smoke-test@example.com).",
        )
        parser.add_argument(
            "--timeout",
            type=float,
            default=30.0,
            help="Seconds to wait for the result (default: 30).",
        )

    def handle(self, *args, **options):
        email = options["email"]
        timeout = options["timeout"]

        self.stdout.write(f"Enqueueing send_welcome_notification({email!r}) ...")
        result = send_welcome_notification.delay(email)
        task_id = result.task_id
        self.stdout.write(f"  -> queued task_id={task_id}")

        self.stdout.write(
            f"Waiting up to {timeout:.0f}s for the webhook to store the result ..."
        )
        deadline = time.monotonic() + timeout
        poll = 1.0
        while time.monotonic() < deadline:
            obj = TaskResult.objects.filter(task_id=task_id).first()
            if obj is not None:
                if obj.status == "SUCCESS":
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"PASS: result stored with status={obj.status}\n"
                            f"  result={obj.result!r}"
                        )
                    )
                    return
                raise CommandError(
                    f"FAIL: task finished with status={obj.status}: {obj.result!r}"
                )
            time.sleep(poll)

        raise CommandError(
            "FAIL: timed out waiting for the result.\n"
            "Checklist:\n"
            "  - Is the QStash dev server running? (docker compose -f compose.dev.yaml up qstash)\n"
            "  - Is the web server reachable at DJANGO_QSTASH_DOMAIN from the QStash container?\n"
            "  - Are QSTASH_URL and the signing keys set for local mode?\n"
            "  - Is DJANGO_QSTASH_FORCE_HTTPS=False for http callbacks?"
        )
