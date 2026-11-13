from __future__ import annotations

import json
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models.signals import post_save

from django_qstash.schedules.models import TaskSchedule
from django_qstash.schedules.reconcile import ScheduleSpec
from django_qstash.schedules.reconcile import reconcile_schedules
from django_qstash.schedules.reconcile import schedule_id_for
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
            body=data["body"],
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
    @pytest.mark.parametrize("remove_option", [False, True])
    def test_failed_delivery_option_update_is_repaired(
        self, qstash, field, value, remove_option
    ):
        original = specs(**{field: value}) if remove_option else specs()
        desired = specs() if remove_option else specs(**{field: value})
        assert reconcile_schedules(original, namespace="prod").ok
        old_body = qstash.store["prod.nightly-report"].body

        qstash.fail_create = True
        failed = reconcile_schedules(desired, namespace="prod")
        assert not failed.ok
        assert failed.outcomes[0].local_saved
        assert qstash.store["prod.nightly-report"].body == old_body

        qstash.fail_create = False
        repaired = reconcile_schedules(desired, namespace="prod")
        assert repaired.outcomes[0].action == "resynced"
        assert repaired.outcomes[0].remote_drift == ["payload"]
        if remove_option:
            assert field not in qstash.requests[-1]
        else:
            assert qstash.requests[-1][field] == value
        new_body = qstash.store["prod.nightly-report"].body
        assert new_body != old_body
        assert "private-" not in new_body
        assert reconcile_schedules(desired, namespace="prod").counts()["unchanged"] == 1
        assert len(qstash.requests) == 2

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
    def test_dry_run_validates_like_apply(self, qstash, invalid, existing):
        if existing:
            reconcile_schedules(specs(), namespace="prod")
        calls_before = list(qstash.calls)
        rows_before = list(TaskSchedule.objects.values())

        dry = reconcile_schedules(specs(**invalid), namespace="prod", dry_run=True)
        applied = reconcile_schedules(specs(**invalid), namespace="prod")

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
