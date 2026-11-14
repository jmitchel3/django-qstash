from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models.signals import post_save

from django_qstash.schedules.formatters import format_task_schedule_for_qstash
from django_qstash.schedules.models import TaskSchedule
from django_qstash.schedules.reconcile import ScheduleSpec
from django_qstash.schedules.reconcile import reconcile_schedules
from django_qstash.schedules.reconcile import schedule_id_for
from django_qstash.schedules.services import remote_sync_suppressed
from django_qstash.schedules.signals import sync_schedule_to_qstash_receiver

DEST = "https://example.com/qstash/webhook/"


class FakeScheduleApi:
    """In-memory stand-in for ``qstash_client.schedule`` keyed by schedule id."""

    def __init__(self) -> None:
        self.store: dict[str, SimpleNamespace] = {}
        self.calls: list[tuple[str, str]] = []
        self.requests: list[dict] = []
        self.fail_create = False
        self.fail_list = False

    def list(self):
        if self.fail_list:
            raise RuntimeError("list down")
        return list(self.store.values())

    def create(self, **data):
        if self.fail_create:
            raise RuntimeError("provider down")
        schedule_id = data["schedule_id"]
        self.calls.append(("create", schedule_id))
        self.requests.append(data)
        existing = self.store.get(schedule_id)
        self.store[schedule_id] = SimpleNamespace(
            schedule_id=schedule_id,
            destination=data["destination"],
            cron=data["cron"],
            body=(
                "REDACTED:" + hashlib.sha256(data["body"].encode()).hexdigest()
                if data.get("redact", {}).get("body")
                else data["body"]
            ),
            retries=data["retries"],
            timeout=data["timeout"],
            paused=existing.paused if existing else False,
        )
        return schedule_id

    def pause(self, schedule_id):
        self.calls.append(("pause", schedule_id))
        self.store[schedule_id].paused = True

    def resume(self, schedule_id):
        self.calls.append(("resume", schedule_id))
        self.store[schedule_id].paused = False

    def delete(self, schedule_id):  # pragma: no cover - must never be called
        raise AssertionError("reconciliation must not delete")


@pytest.fixture
def qstash():
    api = FakeScheduleApi()
    client = SimpleNamespace(schedule=api)
    with patch("django_qstash.schedules.reconcile.qstash_client", client):
        yield api


@pytest.fixture
def live_signals():
    """Make sure reconciliation's own saves do not double-sync via post_save."""
    post_save.connect(sync_schedule_to_qstash_receiver, sender=TaskSchedule)
    with patch("django_qstash.schedules.services.qstash_client") as signal_client:
        yield signal_client
    post_save.disconnect(sync_schedule_to_qstash_receiver, sender=TaskSchedule)


def specs(**overrides):
    base = {
        "key": "nightly-report",
        "task": "reports.tasks.nightly",
        "cron": "0 3 * * *",
        "name": "Nightly report",
        "kwargs": {"full": True},
        "retries": 2,
        "timeout": "5m",
    }
    base.update(overrides)
    return [ScheduleSpec(**base)]


def seed_existing(qstash, schedule_id="scd_legacy", **overrides):
    with remote_sync_suppressed():
        row = TaskSchedule.objects.create(
            schedule_id=schedule_id, **specs(**overrides)[0].local_fields()
        )
    qstash.create(**format_task_schedule_for_qstash(row))
    qstash.calls.clear()
    qstash.requests.clear()
    return row


@pytest.mark.django_db
class TestReconcile:
    def test_create_then_repeat_preserves_identity(self, qstash, live_signals):
        first = reconcile_schedules(specs(), namespace="prod")
        assert first.ok
        assert first.counts()["created"] == 1
        assert qstash.calls == [("create", "prod.nightly-report")]
        row = TaskSchedule.objects.get()
        assert row.schedule_id == "prod.nightly-report"
        assert row.task == "reports.tasks.nightly"
        assert row.timeout == "5m"

        second = reconcile_schedules(specs(), namespace="prod")
        assert second.counts()["unchanged"] == 1
        assert second.outcomes[0].changes == {}
        assert len(qstash.calls) == 1
        assert TaskSchedule.objects.count() == 1
        assert len(qstash.store) == 1
        live_signals.schedule.create.assert_not_called()

    def test_changed_cron_retry_timeout_converge(self, qstash):
        reconcile_schedules(specs(), namespace="prod")
        result = reconcile_schedules(
            specs(cron="0 4 * * *", retries=4, timeout="10m"), namespace="prod"
        )
        outcome = result.outcomes[0]
        assert outcome.action == "changed"
        assert set(outcome.changes) == {"cron", "retries", "timeout"}
        assert outcome.changes["timeout"] == ["5m", "10m"]
        row = TaskSchedule.objects.get()
        assert (row.cron, row.retries, row.timeout) == ("0 4 * * *", 4, "10m")
        remote = qstash.store["prod.nightly-report"]
        assert (remote.cron, remote.retries, remote.timeout) == ("0 4 * * *", 4, "10m")
        assert json.loads(remote.body)["options"]["timeout"] == "10m"

    def test_default_change_updates_existing_rows(self, qstash):
        base = specs()[0]
        reconcile_schedules(
            [ScheduleSpec(key=base.key, task=base.task, cron=base.cron)],
            namespace="prod",
        )
        assert TaskSchedule.objects.get().retries == 3
        result = reconcile_schedules(
            [ScheduleSpec(key=base.key, task=base.task, cron=base.cron, retries=1)],
            namespace="prod",
        )
        assert result.outcomes[0].changes == {"retries": [3, 1]}

    def test_domain_move_resyncs_same_schedule(self, qstash, settings):
        reconcile_schedules(specs(), namespace="prod")
        settings.DJANGO_QSTASH_DOMAIN = "new.example.com"

        dry = reconcile_schedules(specs(), namespace="prod", dry_run=True)
        assert dry.outcomes[0].action == "resynced"
        assert "destination" in dry.outcomes[0].remote_drift[0]
        assert qstash.store["prod.nightly-report"].destination == DEST

        result = reconcile_schedules(specs(), namespace="prod")
        assert result.outcomes[0].action == "resynced"
        remote = qstash.store["prod.nightly-report"]
        assert remote.destination == "https://new.example.com/qstash/webhook/"
        assert len(qstash.store) == 1
        assert TaskSchedule.objects.count() == 1

        assert reconcile_schedules(specs(), namespace="prod").counts()["unchanged"] == 1

    def test_provider_failure_is_visible_and_rerun_repairs(self, qstash):
        qstash.fail_create = True
        failed = reconcile_schedules(specs(), namespace="prod")
        assert not failed.ok
        outcome = failed.outcomes[0]
        assert outcome.action == "failed"
        assert outcome.local_saved is True
        assert "provider down" in outcome.error
        assert "Rerun" in outcome.error
        assert TaskSchedule.objects.count() == 1
        assert qstash.store == {}

        qstash.fail_create = False
        repaired = reconcile_schedules(specs(), namespace="prod")
        assert repaired.outcomes[0].action == "resynced"
        assert repaired.outcomes[0].remote_drift == ["missing in QStash"]
        assert "prod.nightly-report" in qstash.store

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("headers", {"Authorization": "Bearer private-test-token"}),
            ("callback", "https://callback.example.com/done"),
            ("callback_headers", {"X-Token": "private-callback-token"}),
            ("failure_callback", "https://callback.example.com/failed"),
            ("failure_callback_headers", {"X-Token": "private-failure-token"}),
            ("flow_control", {"key": "reports", "parallelism": 2}),
            ("redact", {"body": True}),
        ],
    )
    @pytest.mark.parametrize("mode", ["add", "change", "remove"])
    @pytest.mark.parametrize("adopt", [False, True])
    def test_failed_delivery_option_update_is_repaired(
        self, qstash, field, value, mode, adopt
    ):
        original = specs(**{field: value}) if mode != "add" else specs()
        if mode == "change":
            value = (
                value + "/changed"
                if isinstance(value, str)
                else (
                    {"key": "changed", "parallelism": 1}
                    if field == "flow_control"
                    else (
                        {"header": ["X-Secret"]}
                        if field == "redact"
                        else {"X-Changed": "changed"}
                    )
                )
            )
        desired = specs() if mode == "remove" else specs(**{field: value})
        schedule_id = "prod.nightly-report"
        if adopt:
            seed_existing(qstash)
            schedule_id = "scd_legacy"
            original = [replace(original[0], existing_schedule_id=schedule_id)]
            desired = [replace(desired[0], existing_schedule_id=schedule_id)]
        assert reconcile_schedules(original, namespace="prod").ok
        old_body = qstash.store[schedule_id].body

        qstash.fail_create = True
        failed = reconcile_schedules(desired, namespace="prod")
        assert not failed.ok
        assert failed.outcomes[0].local_saved
        assert qstash.store[schedule_id].body == old_body

        qstash.fail_create = False
        repaired = reconcile_schedules(desired, namespace="prod")
        assert repaired.outcomes[0].action == "resynced"
        assert repaired.outcomes[0].remote_drift == ["payload"]
        if mode == "remove":
            assert field not in qstash.requests[-1]
        else:
            assert qstash.requests[-1][field] == value
        new_body = qstash.store[schedule_id].body
        assert new_body != old_body
        assert "private-" not in new_body
        assert reconcile_schedules(desired, namespace="prod").counts()["unchanged"] == 1
        assert len(qstash.requests) == 2
        assert set(qstash.store) == {schedule_id}

    @pytest.mark.parametrize("local_exists", [False, True])
    def test_adopt_existing_id_and_repeat(self, qstash, live_signals, local_exists):
        row = seed_existing(qstash)
        if not local_exists:
            TaskSchedule.objects.all()._raw_delete("default")
        declared = specs(existing_schedule_id="scd_legacy")
        first = reconcile_schedules(declared, namespace="prod")
        assert first.ok
        adopted = TaskSchedule.objects.get()
        if local_exists:
            assert adopted.pk == row.pk
        assert adopted.schedule_id == "scd_legacy"
        assert adopted.reconciliation_namespace == "prod"
        assert adopted.reconciliation_key == "nightly-report"
        assert set(qstash.store) == {"scd_legacy"}
        assert qstash.calls == [("create", "scd_legacy")]
        assert (
            reconcile_schedules(declared, namespace="prod").counts()["unchanged"] == 1
        )
        assert len(qstash.calls) == 1
        live_signals.schedule.create.assert_not_called()

    def test_adoption_dry_run_has_no_writes(self, qstash):
        seed_existing(qstash)
        before = list(TaskSchedule.objects.values())
        body = qstash.store["scd_legacy"].body
        declared = specs(existing_schedule_id="scd_legacy")
        dry = reconcile_schedules(declared, namespace="prod", dry_run=True)
        assert dry.ok
        assert dry.outcomes[0].action == "resynced"
        assert list(TaskSchedule.objects.values()) == before
        assert qstash.store["scd_legacy"].body == body
        assert qstash.calls == []

    @pytest.mark.parametrize("dry_run", [False, True])
    @pytest.mark.parametrize(
        "conflict",
        [
            "destination",
            "remote-task",
            "local-task",
            "missing",
            "remote-owner",
            "local-owner",
            "deterministic-local",
            "deterministic-remote",
            "malformed",
        ],
    )
    def test_adoption_rejects_unsafe_mapping_before_any_writes(
        self, qstash, dry_run, conflict
    ):
        row = seed_existing(qstash)
        remote = qstash.store["scd_legacy"]
        if conflict == "destination":
            remote.destination = "https://stage.example.com/qstash/webhook/"
        elif conflict == "remote-task":
            remote.body = json.dumps({"module": "other.tasks", "function": "nightly"})
        elif conflict == "local-task":
            TaskSchedule.objects.filter(pk=row.pk).update(task="other.tasks.nightly")
        elif conflict == "missing":
            qstash.store.clear()
        elif conflict == "remote-owner":
            body = json.loads(remote.body)
            body["_qstash_schedule_owner"] = {
                "namespace": "stage",
                "key": "nightly-report",
            }
            remote.body = json.dumps(body)
        elif conflict == "local-owner":
            TaskSchedule.objects.filter(pk=row.pk).update(
                reconciliation_namespace="stage", reconciliation_key="nightly-report"
            )
        elif conflict == "deterministic-local":
            TaskSchedule.objects.create(
                schedule_id="prod.nightly-report", **specs()[0].local_fields()
            )
        elif conflict == "deterministic-remote":
            qstash.store["prod.nightly-report"] = SimpleNamespace(
                schedule_id="prod.nightly-report"
            )
        else:
            remote.body = "[]"
        before = list(TaskSchedule.objects.values())
        with pytest.raises(ValueError):
            reconcile_schedules(
                specs(key="valid-new-job") + specs(existing_schedule_id="scd_legacy"),
                namespace="prod",
                dry_run=dry_run,
            )
        assert list(TaskSchedule.objects.values()) == before
        assert qstash.calls == []

    @pytest.mark.parametrize("dry_run", [False, True])
    @pytest.mark.parametrize("ids", [("scd_one", "scd_two"), ("scd_one", "scd_one")])
    def test_duplicate_keys_rejected_even_with_distinct_ids(self, qstash, dry_run, ids):
        with pytest.raises(ValueError, match="Duplicate schedule key"):
            reconcile_schedules(
                specs(existing_schedule_id=ids[0]) + specs(existing_schedule_id=ids[1]),
                namespace="prod",
                dry_run=dry_run,
            )
        assert qstash.calls == []

    @pytest.mark.parametrize("dry_run", [False, True])
    def test_duplicate_existing_ids_rejected(self, qstash, dry_run):
        with pytest.raises(ValueError, match="Duplicate schedule id"):
            reconcile_schedules(
                specs(key="one", existing_schedule_id="scd_one")
                + specs(key="two", existing_schedule_id="scd_one"),
                namespace="prod",
                dry_run=dry_run,
            )
        assert qstash.calls == []

    @pytest.mark.parametrize(
        "invalid", ["", "prod.job", "stage.job", "scd_", "scd_x\n", 12]
    )
    def test_invalid_existing_id(self, qstash, invalid):
        with pytest.raises(ValueError, match="existing_schedule_id"):
            reconcile_schedules(specs(existing_schedule_id=invalid), namespace="prod")
        assert qstash.calls == []

    @pytest.mark.parametrize("local_exists", [False, True])
    @pytest.mark.parametrize("replacement", [None, "scd_other"])
    def test_adoption_mapping_cannot_be_removed_or_changed(
        self, qstash, local_exists, replacement
    ):
        seed_existing(qstash)
        assert reconcile_schedules(
            specs(existing_schedule_id="scd_legacy"), namespace="prod"
        ).ok
        if not local_exists:
            TaskSchedule.objects.all()._raw_delete("default")
        qstash.calls.clear()
        with pytest.raises(ValueError, match="already bound"):
            reconcile_schedules(
                specs(existing_schedule_id=replacement), namespace="prod"
            )
        assert qstash.calls == []
        assert set(qstash.store) == {"scd_legacy"}

    def test_failed_initial_adoption_retains_binding_and_recovers(self, qstash):
        row = seed_existing(qstash)
        declared = specs(existing_schedule_id="scd_legacy", headers={"X-New": "yes"})
        qstash.fail_create = True
        failed = reconcile_schedules(declared, namespace="prod")
        assert failed.failed[0].local_saved
        row.refresh_from_db()
        assert row.reconciliation_namespace == "prod"
        with pytest.raises(ValueError, match="already bound"):
            reconcile_schedules(specs(), namespace="prod")
        qstash.fail_create = False
        assert reconcile_schedules(declared, namespace="prod").counts()["resynced"] == 1
        assert (
            reconcile_schedules(declared, namespace="prod").counts()["unchanged"] == 1
        )
        assert set(qstash.store) == {"scd_legacy"}

    def test_two_environments_adopt_only_their_explicit_ids(self, qstash, settings):
        seed_existing(qstash, "scd_stage")
        seed_existing(qstash, "scd_prod")
        qstash.store["scd_stage"].destination = (
            "https://stage.example.com/qstash/webhook/"
        )
        settings.DJANGO_QSTASH_DOMAIN = "stage.example.com"
        stage = specs(existing_schedule_id="scd_stage")
        assert reconcile_schedules(stage, namespace="stage").ok
        stage_body = qstash.store["scd_stage"].body
        settings.DJANGO_QSTASH_DOMAIN = "example.com"
        prod = specs(existing_schedule_id="scd_prod")
        assert reconcile_schedules(prod, namespace="prod").ok
        assert reconcile_schedules(prod, namespace="prod").counts()["unchanged"] == 1
        assert qstash.store["scd_stage"].body == stage_body
        assert set(qstash.store) == {"scd_stage", "scd_prod"}

    def test_adopted_task_can_change_after_ownership_is_established(self, qstash):
        seed_existing(qstash)
        declared = specs(existing_schedule_id="scd_legacy")
        assert reconcile_schedules(declared, namespace="prod").ok
        changed = [replace(declared[0], task="reports.tasks.weekly")]
        assert reconcile_schedules(changed, namespace="prod").ok
        assert reconcile_schedules(changed, namespace="prod").counts()["unchanged"] == 1

    def test_adopted_missing_remote_is_never_recreated(self, qstash):
        seed_existing(qstash)
        declared = specs(existing_schedule_id="scd_legacy")
        assert reconcile_schedules(declared, namespace="prod").ok
        qstash.store.clear()
        qstash.calls.clear()
        with pytest.raises(ValueError, match="missing schedule"):
            reconcile_schedules(declared, namespace="prod")
        assert qstash.calls == []

    def test_redacted_legacy_adoption_requires_original_local_payload(self, qstash):
        seed_existing(qstash, redact={"body": True})
        declared = specs(existing_schedule_id="scd_legacy", redact={"body": True})
        assert reconcile_schedules(declared, namespace="prod").ok
        assert (
            reconcile_schedules(declared, namespace="prod").counts()["unchanged"] == 1
        )
        TaskSchedule.objects.all()._raw_delete("default")
        qstash.calls.clear()
        with pytest.raises(ValueError, match="Ambiguous redacted"):
            reconcile_schedules(specs(redact={"body": True}), namespace="prod")
        with pytest.raises(ValueError, match="task does not match"):
            reconcile_schedules(declared, namespace="stage")
        assert qstash.calls == []

    def test_redacted_legacy_task_mismatch_is_not_adopted(self, qstash):
        row = seed_existing(qstash, redact={"body": True})
        TaskSchedule.objects.filter(pk=row.pk).update(
            task="other.task", task_name="other.task"
        )
        with pytest.raises(ValueError, match="task does not match"):
            reconcile_schedules(
                specs(existing_schedule_id="scd_legacy", task="other.task"),
                namespace="prod",
            )
        assert qstash.calls == []

    def test_legacy_payload_gets_one_resync(self, qstash):
        reconcile_schedules(specs(), namespace="prod")
        remote = qstash.store["prod.nightly-report"]
        body = json.loads(remote.body)
        body.pop("_qstash_schedule_spec")
        remote.body = json.dumps(body)

        result = reconcile_schedules(specs(), namespace="prod")
        assert result.outcomes[0].action == "resynced"
        assert result.outcomes[0].remote_drift == ["payload"]
        assert reconcile_schedules(specs(), namespace="prod").counts()["unchanged"] == 1
        assert len(qstash.requests) == 2

    def test_fingerprint_is_independent_of_mapping_order(self, qstash):
        reconcile_schedules(
            specs(headers={"X-First": "one", "X-Second": "two"}), namespace="prod"
        )
        result = reconcile_schedules(
            specs(headers={"X-Second": "two", "X-First": "one"}), namespace="prod"
        )
        assert result.counts()["unchanged"] == 1
        assert len(qstash.requests) == 1

    def test_fingerprint_normalizes_json_object_keys(self, qstash):
        desired = specs(args=[{1: "one", "x": "two"}])
        assert reconcile_schedules(desired, namespace="prod").counts()["created"] == 1
        payload = json.loads(qstash.store["prod.nightly-report"].body)
        assert payload["args"] == [{"1": "one", "x": "two"}]
        assert reconcile_schedules(desired, namespace="prod").counts()["unchanged"] == 1
        assert len(qstash.requests) == 1

    def test_changed_task_payload_converges(self, qstash):
        reconcile_schedules(specs(), namespace="prod")
        changed = specs(task="reports.tasks.weekly")
        assert reconcile_schedules(changed, namespace="prod").counts()["changed"] == 1
        payload = json.loads(qstash.store["prod.nightly-report"].body)
        assert (payload["module"], payload["function"]) == ("reports.tasks", "weekly")
        assert reconcile_schedules(changed, namespace="prod").counts()["unchanged"] == 1

    def test_reconciled_payload_is_webhook_compatible(self, qstash):
        from django_qstash.handlers import TaskPayload

        reconcile_schedules(specs(), namespace="prod")
        body = json.loads(qstash.store["prod.nightly-report"].body)
        payload = TaskPayload.from_dict(body)
        assert payload.function_path == "reports.tasks.nightly"
        assert payload.args == []
        assert payload.kwargs == {"full": True}

    def test_remote_payload_drift_is_repaired(self, qstash):
        reconcile_schedules(specs(), namespace="prod")
        qstash.store["prod.nightly-report"].body = json.dumps({"tampered": True})
        result = reconcile_schedules(specs(), namespace="prod")
        assert result.outcomes[0].remote_drift == ["payload"]
        assert json.loads(qstash.store["prod.nightly-report"].body)["kwargs"] == {
            "full": True
        }

    def test_local_validation_failure_writes_nothing(self, qstash):
        result = reconcile_schedules(specs(cron="not a cron"), namespace="prod")
        assert result.outcomes[0].action == "failed"
        assert result.outcomes[0].local_saved is False
        assert "local validation failed" in result.outcomes[0].error
        assert TaskSchedule.objects.count() == 0
        assert qstash.calls == []

    def test_list_failure_fails_every_entry_without_writes(self, qstash):
        qstash.fail_list = True
        result = reconcile_schedules(specs(), namespace="prod")
        assert [o.action for o in result.outcomes] == ["failed"]
        assert "could not list" in result.outcomes[0].error
        assert TaskSchedule.objects.count() == 0

    def test_environments_do_not_touch_each_other(self, qstash):
        reconcile_schedules(specs(), namespace="stage")
        stage_before = vars(qstash.store["stage.nightly-report"]).copy()

        reconcile_schedules(specs(cron="0 5 * * *"), namespace="prod")
        assert set(qstash.store) == {"stage.nightly-report", "prod.nightly-report"}
        assert vars(qstash.store["stage.nightly-report"]) == stage_before
        assert TaskSchedule.objects.get(schedule_id="stage.nightly-report").cron == (
            "0 3 * * *"
        )

    def test_unrelated_schedules_are_not_adopted_or_changed(self, qstash):
        qstash.store["other-app"] = SimpleNamespace(
            schedule_id="other-app",
            destination="https://other.app/",
            cron="* * * * *",
            body="<xml/>",
            retries=0,
            paused=False,
        )
        TaskSchedule.objects.create(
            name="Hand made", task="reports.tasks.adhoc", schedule_id="hand-made"
        )
        reconcile_schedules(specs(), namespace="prod")
        assert qstash.store["other-app"].body == "<xml/>"
        assert TaskSchedule.objects.filter(schedule_id="hand-made").exists()
        assert [c[1] for c in qstash.calls] == ["prod.nightly-report"]

    def test_pause_and_resume(self, qstash):
        reconcile_schedules(specs(is_active=False), namespace="prod")
        assert qstash.store["prod.nightly-report"].paused is True
        assert ("pause", "prod.nightly-report") in qstash.calls

        result = reconcile_schedules(specs(), namespace="prod")
        assert result.outcomes[0].changes == {"is_active": [False, True]}
        assert qstash.store["prod.nightly-report"].paused is False

        qstash.store["prod.nightly-report"].paused = True
        drift = reconcile_schedules(specs(), namespace="prod")
        assert drift.outcomes[0].remote_drift == ["paused"]
        assert qstash.store["prod.nightly-report"].paused is False

    def test_dry_run_writes_nothing(self, qstash):
        result = reconcile_schedules(specs(), namespace="prod", dry_run=True)
        assert result.dry_run
        assert result.outcomes[0].action == "created"
        assert TaskSchedule.objects.count() == 0
        assert qstash.calls == []

    @pytest.mark.parametrize(
        "invalid",
        [
            {"cron": "not a cron"},
            {"timeout": "invalid"},
            {"retries": 6},
            {"callback": "not-a-url"},
        ],
    )
    @pytest.mark.parametrize("existing", [False, True])
    @pytest.mark.parametrize("adopt", [False, True])
    def test_dry_run_validates_like_apply(self, qstash, invalid, existing, adopt):
        mapping = {}
        if adopt:
            seed_existing(qstash)
            mapping = {"existing_schedule_id": "scd_legacy"}
        if existing:
            reconcile_schedules(specs(**mapping), namespace="prod")
        calls_before = list(qstash.calls)
        rows_before = list(TaskSchedule.objects.values())

        dry = reconcile_schedules(
            specs(**invalid, **mapping), namespace="prod", dry_run=True
        )
        applied = reconcile_schedules(specs(**invalid, **mapping), namespace="prod")

        assert not dry.ok
        assert dry.outcomes[0].action == "failed"
        assert not dry.outcomes[0].local_saved
        assert dry.outcomes[0].error == applied.outcomes[0].error
        assert list(TaskSchedule.objects.values()) == rows_before
        assert qstash.calls == calls_before

    def test_forced_resync(self, qstash):
        reconcile_schedules(specs(), namespace="prod")
        result = reconcile_schedules(specs(), namespace="prod", resync=True)
        assert result.outcomes[0].action == "resynced"
        assert result.outcomes[0].remote_drift == ["forced resync"]
        assert qstash.calls.count(("create", "prod.nightly-report")) == 2

    def test_dict_specs_and_callable_task(self, qstash):
        from tests.discovery.tasks import debug_task

        result = reconcile_schedules(
            [{"key": "a", "task": debug_task, "cron": "*/5 * * * *"}],
            namespace="prod",
        )
        assert result.ok
        assert TaskSchedule.objects.get().task == "tests.discovery.tasks.debug_task"

    def test_result_to_dict_is_json(self, qstash):
        data = reconcile_schedules(specs(), namespace="prod").to_dict()
        encoded = json.loads(json.dumps(data))
        assert encoded["counts"]["created"] == 1
        assert encoded["outcomes"][0]["schedule_id"] == "prod.nightly-report"

    def test_configuration_errors(self, qstash, settings):
        with pytest.raises(ImproperlyConfigured, match="namespace"):
            reconcile_schedules(specs())
        settings.DJANGO_QSTASH_SCHEDULE_NAMESPACE = "prod"
        assert reconcile_schedules(specs()).namespace == "prod"
        with pytest.raises(ValueError, match="Duplicate"):
            reconcile_schedules(specs() + specs(), namespace="prod")
        with pytest.raises(ValueError, match="Invalid schedule key"):
            reconcile_schedules(specs(key="has space"), namespace="prod")
        with pytest.raises(ValueError, match="Unknown schedule spec fields"):
            ScheduleSpec.coerce(
                {"key": "a", "task": "x.y", "cron": "* * * * *", "z": 1}
            )
        with pytest.raises(TypeError):
            ScheduleSpec.coerce(42)  # type: ignore[arg-type]

    def test_schedule_id_for(self):
        assert schedule_id_for("prod", "job_1") == "prod.job_1"
        with pytest.raises(ValueError, match="namespace"):
            schedule_id_for("a.b", "job")


SPECS = specs()


def bad_specs():
    return "not a list"


@pytest.mark.django_db
class TestReconcileCommand:
    def run(self, *args):
        out = StringIO()
        call_command("qstash_reconcile_schedules", *args, stdout=out)
        return out.getvalue()

    def test_text_output(self, qstash):
        out = self.run("--specs", f"{__name__}.SPECS", "--namespace", "prod")
        assert "created   prod.nightly-report" in out
        assert "1 created, 0 changed, 0 resynced, 0 unchanged, 0 failed" in out

    def test_json_dry_run_from_settings(self, qstash, settings):
        settings.DJANGO_QSTASH_SCHEDULE_SPECS = f"{__name__}.specs"
        settings.DJANGO_QSTASH_SCHEDULE_NAMESPACE = "stage"
        data = json.loads(self.run("--json", "--dry-run"))
        assert data["dry_run"] is True
        assert data["outcomes"][0]["schedule_id"] == "stage.nightly-report"
        assert TaskSchedule.objects.count() == 0

    def test_failure_exits_nonzero(self, qstash):
        qstash.fail_create = True
        with pytest.raises(CommandError, match="1 of 1 schedules failed"):
            self.run("--specs", f"{__name__}.SPECS", "--namespace", "prod")

    def test_resync_flag(self, qstash):
        self.run("--specs", f"{__name__}.SPECS", "--namespace", "prod")
        out = self.run(
            "--specs", f"{__name__}.SPECS", "--namespace", "prod", "--resync"
        )
        assert "resynced  prod.nightly-report" in out

    def test_missing_specs(self):
        with pytest.raises(CommandError, match="No schedule specs"):
            self.run()

    def test_bad_specs_path(self):
        with pytest.raises(CommandError, match="Could not import"):
            self.run("--specs", "nope.module.SPECS")
        with pytest.raises(CommandError, match="did not provide a list"):
            self.run("--specs", f"{__name__}.bad_specs")

    def test_missing_namespace(self, qstash):
        with pytest.raises(CommandError, match="namespace"):
            self.run("--specs", f"{__name__}.SPECS")
