"""Exercise reconciliation using only a newly created, temporary QStash schedule."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from django_qstash.callbacks import get_callback_url
from django_qstash.client import qstash_client
from django_qstash.schedules.formatters import format_task_schedule_for_qstash
from django_qstash.schedules.models import TaskSchedule
from django_qstash.schedules.reconcile import ScheduleSpec
from django_qstash.schedules.reconcile import reconcile_schedules
from django_qstash.schedules.services import remote_schedule_to_fields
from django_qstash.schedules.services import remote_sync_suppressed


class Command(BaseCommand):
    help = "Verify adoption/recovery with a temporary provider-generated schedule ID."

    def handle(self, *args, **options):
        namespace = f"smoke-{uuid4().hex}"
        spec = ScheduleSpec(
            key="adoption",
            task="notifications.tasks.send_welcome_notification",
            cron="0 0 1 1 *",
            args=["schedule-smoke@example.com"],
            is_active=False,
        )
        # No ID supplied: the provider generates one just as it did for legacy jobs.
        seed = TaskSchedule(**spec.local_fields())
        seed.task_name = seed.task
        schedule_id = qstash_client.schedule.create(
            **format_task_schedule_for_qstash(seed)
        )
        try:
            qstash_client.schedule.pause(schedule_id)
            spec = replace(spec, existing_schedule_id=schedule_id)
            original = qstash_client.schedule.get(schedule_id)
            self.require(
                reconcile_schedules([spec], namespace=namespace, dry_run=True).ok,
                "dry run",
            )
            self.require(
                not TaskSchedule.objects.filter(schedule_id=schedule_id).exists(),
                "dry run wrote locally",
            )
            self.require(
                qstash_client.schedule.get(schedule_id).body == original.body,
                "dry run wrote remotely",
            )
            self.require(
                reconcile_schedules([spec], namespace=namespace).ok, "adoption"
            )
            self.require(
                reconcile_schedules([spec], namespace=namespace).counts()["unchanged"]
                == 1,
                "adoption idempotence",
            )

            configured = replace(
                spec,
                headers={"X-Smoke": "yes"},
                callback=get_callback_url(),
                callback_headers={"X-Smoke": "callback"},
                failure_callback=get_callback_url(),
                failure_callback_headers={"X-Smoke": "failure"},
                flow_control={"key": namespace, "parallelism": 1},
                redact={"body": True},
            )
            # Exercise both setting and removing delivery options after a failed push.
            for desired in (configured, spec):
                before = qstash_client.schedule.get(schedule_id).body
                with patch.object(
                    qstash_client.schedule,
                    "create",
                    side_effect=ConnectionError("smoke injected failure"),
                ):
                    failed = reconcile_schedules([desired], namespace=namespace)
                self.require(
                    not failed.ok and failed.failed[0].local_saved, "failure reporting"
                )
                self.require(
                    qstash_client.schedule.get(schedule_id).body == before,
                    "failed push changed remote",
                )
                self.require(
                    reconcile_schedules([desired], namespace=namespace).counts()[
                        "resynced"
                    ]
                    == 1,
                    "repair",
                )
                repeated = reconcile_schedules([desired], namespace=namespace)
                remote = qstash_client.schedule.get(schedule_id)
                self.require(
                    repeated.counts()["unchanged"] == 1,
                    f"repair idempotence: {repeated.to_dict()!r}; "
                    f"temporary remote body={remote.body!r}",
                )
                self.require(
                    remote.schedule_id == schedule_id,
                    "schedule identity changed",
                )
                self.require(remote.paused, "schedule resumed unexpectedly")
                # Body redaction hides task metadata. Use the known original
                # task body only to let the mapper inspect the echoed options;
                # the reconciler already verified the real body's SHA256 above.
                actual = remote_schedule_to_fields(replace(remote, body=original.body))
                for field in (
                    "headers",
                    "callback",
                    "callback_headers",
                    "failure_callback",
                    "failure_callback_headers",
                    "flow_control",
                ):
                    self.require(
                        actual[field] == getattr(desired, field),
                        f"remote {field} mismatch: {actual[field]!r}",
                    )
            self.require(
                not any(
                    s.schedule_id.startswith(namespace + ".")
                    for s in qstash_client.schedule.list()
                ),
                "duplicate deterministic schedule",
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"PASS: adopted/repaired {schedule_id}; ID preserved, repeated runs unchanged"
                )
            )
        finally:
            # This is the only ID we delete, returned by our own create above.
            qstash_client.schedule.delete(schedule_id)
            with remote_sync_suppressed():
                TaskSchedule.objects.filter(schedule_id=schedule_id).delete()
            self.stdout.write(f"Cleaned up temporary schedule {schedule_id}")

    @staticmethod
    def require(condition, message):
        if not condition:
            raise CommandError(f"FAIL: {message}")
