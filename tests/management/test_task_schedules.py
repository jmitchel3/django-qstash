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
from django.db.models.signals import pre_delete

from django_qstash.schedules.models import TaskSchedule
from django_qstash.schedules.signals import delete_schedule_from_qstash_receiver
from django_qstash.schedules.signals import sync_schedule_to_qstash_receiver

DEST = "https://example.com/qstash/webhook/"
OTHER_DEST = "https://stage.example.com/qstash/webhook/"
CMD_CLIENT = "django_qstash.management.commands.task_schedules.qstash_client"


def remote(
    schedule_id: str = "sched-1",
    destination: str = DEST,
    body: object = None,
    **extra: object,
) -> SimpleNamespace:
    if body is None:
        body = {
            "task_name": "Nightly Report",
            "module": "reports.tasks",
            "function": "nightly",
            "args": [1, 2],
            "kwargs": {"key": "value"},
            "options": {"timeout": "5m", "retry_delay": "1000", "label": "nightly"},
        }
    attrs: dict[str, object] = {
        "schedule_id": schedule_id,
        "destination": destination,
        "cron": "0 3 * * *",
        "body": body if isinstance(body, str) else json.dumps(body),
        "retries": 2,
        "timeout": 300000,  # QStash reports milliseconds
        "delay": None,
        "paused": False,
        "headers": None,
        "callback_headers": None,
        "failure_callback_headers": None,
        "callback": None,
        "failure_callback": None,
        "queue": None,
        "flow_control": None,
        "retry_delay_expression": None,
        "label": None,
    }
    attrs.update(extra)
    return SimpleNamespace(**attrs)


def run(*args: str) -> tuple[str, str]:
    out, err = StringIO(), StringIO()
    call_command("task_schedules", *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


@pytest.fixture
def no_stdin():
    def explode(*args, **kwargs):
        raise AssertionError("stdin must not be read")

    with patch("builtins.input", side_effect=explode) as mock_input:
        yield mock_input


@pytest.fixture
def live_signals():
    """Reconnect the QStash receivers so remote writes would be observable."""
    post_save.connect(sync_schedule_to_qstash_receiver, sender=TaskSchedule)
    pre_delete.connect(delete_schedule_from_qstash_receiver, sender=TaskSchedule)
    with patch("django_qstash.schedules.services.qstash_client") as service_client:
        yield service_client
    post_save.disconnect(sync_schedule_to_qstash_receiver, sender=TaskSchedule)
    pre_delete.disconnect(delete_schedule_from_qstash_receiver, sender=TaskSchedule)


def assert_no_remote_writes(*clients) -> None:
    for client in clients:
        for method in ("create", "pause", "resume", "delete"):
            getattr(client.schedule, method).assert_not_called()


@pytest.mark.django_db
class TestTaskSchedulesCommand:
    def test_requires_an_option(self):
        with pytest.raises(CommandError, match="--list or --sync"):
            run()

    @patch(CMD_CLIENT)
    def test_list_filters_to_destination_and_is_read_only(self, client, no_stdin):
        client.schedule.list.return_value = [
            remote("mine"),
            remote("stage-sched", destination=OTHER_DEST),
            remote("foreign", destination="https://other.app/hook", body="not json"),
        ]
        out, _ = run("--list")

        assert f"Found 1 remote schedules for destination: {DEST}" in out
        assert "Ignored 2 schedules with other destinations" in out
        assert "Schedule ID: mine" in out
        assert "Nightly Report (reports.tasks.nightly)" in out
        assert "stage-sched" not in out
        assert "foreign" not in out
        assert TaskSchedule.objects.count() == 0
        assert_no_remote_writes(client)

    @patch(CMD_CLIENT)
    def test_list_tolerates_unrecognized_payload(self, client):
        client.schedule.list.return_value = [remote("odd", body={"hello": "world"})]
        out, _ = run("--list")
        assert "not a django-qstash task payload" in out

    @patch(CMD_CLIENT)
    def test_no_input_never_reads_stdin(self, client, no_stdin, live_signals):
        client.schedule.list.return_value = [remote("mine")]
        out, _ = run("--sync", "--no-input")

        no_stdin.assert_not_called()
        assert "Imported 1 of 1 schedules (1 created, 0 updated, 0 failed)" in out
        obj = TaskSchedule.objects.get(schedule_id="mine")
        assert obj.name == "Nightly Report"
        assert obj.task == "reports.tasks.nightly"
        assert obj.cron == "0 3 * * *"
        assert obj.args == [1, 2]
        assert obj.kwargs == {"key": "value"}
        assert obj.retries == 2
        assert obj.timeout == "5m"
        assert obj.retry_delay == "1000"
        assert obj.label == "nightly"
        assert_no_remote_writes(client, live_signals)

    @patch(CMD_CLIENT)
    def test_remote_attributes_used_when_body_has_no_options(self, client):
        body = {"module": "reports.tasks", "function": "nightly"}
        client.schedule.list.return_value = [
            remote("mine", body=body, timeout=90000, delay=30, label="x")
        ]
        run("--sync", "--no-input")
        obj = TaskSchedule.objects.get(schedule_id="mine")
        assert obj.name == "reports.tasks.nightly"
        assert obj.timeout == "90s"
        assert obj.delay == "30s"
        assert obj.label == "x"

    @patch(CMD_CLIENT)
    def test_sync_ignores_foreign_destinations_and_payloads(self, client, live_signals):
        client.schedule.list.return_value = [
            remote("mine"),
            remote("stage-sched", destination=OTHER_DEST),
            remote("foreign", destination="https://other.app/hook", body="<xml/>"),
            remote("foreign2", destination="https://other.app/hook", body={"a": 1}),
        ]
        run("--sync", "--no-input")

        assert list(TaskSchedule.objects.values_list("schedule_id", flat=True)) == [
            "mine"
        ]
        assert_no_remote_writes(client, live_signals)

    @patch(CMD_CLIENT)
    def test_update_existing_row_without_remote_write(self, client, live_signals):
        post_save.disconnect(sync_schedule_to_qstash_receiver, sender=TaskSchedule)
        TaskSchedule.objects.create(
            schedule_id="mine",
            name="Old",
            task="reports.tasks.old",
            cron="* * * * *",
            redact={"body": True},
        )
        post_save.connect(sync_schedule_to_qstash_receiver, sender=TaskSchedule)

        client.schedule.list.return_value = [
            remote(
                "mine",
                paused=True,
                headers={"X-Token": ["abc"], "Content-Type": ["application/json"]},
                callback="https://example.com/cb",
                flow_control=SimpleNamespace(
                    key="reports", parallelism=2, rate=None, period=None
                ),
                queue="reports",
            )
        ]
        out, _ = run("--sync", "--no-input")

        assert "(0 created, 1 updated, 0 failed)" in out
        obj = TaskSchedule.objects.get(schedule_id="mine")
        assert obj.name == "Nightly Report"
        assert obj.task == "reports.tasks.nightly"
        assert obj.is_active is False
        assert obj.headers == {"X-Token": "abc"}
        assert obj.callback == "https://example.com/cb"
        assert obj.flow_control == {"key": "reports", "parallelism": 2}
        assert obj.queue == "reports"
        # QStash does not echo redaction settings; the local value is preserved.
        assert obj.redact == {"body": True}
        assert_no_remote_writes(client, live_signals)

    @patch(CMD_CLIENT)
    def test_saves_after_import_sync_again(self, client, live_signals):
        """Suppression is scoped to the import; normal saves still sync."""
        client.schedule.list.return_value = [remote("mine")]
        run("--sync", "--no-input")
        assert_no_remote_writes(live_signals)

        live_signals.schedule.create.return_value = "mine"
        obj = TaskSchedule.objects.get(schedule_id="mine")
        obj.cron = "0 4 * * *"
        obj.save()
        live_signals.schedule.create.assert_called_once()
        sent = live_signals.schedule.create.call_args.kwargs
        assert sent["schedule_id"] == "mine"
        assert sent["timeout"] == "5m"
        assert sent["retry_delay"] == "1000"

    @patch(CMD_CLIENT)
    def test_partial_failure_returns_error_with_summary(self, client):
        client.schedule.list.return_value = [
            remote("good"),
            remote("bad-json", body="not json"),
            remote("bad-shape", body={"task_name": "x"}),
        ]
        out, err = StringIO(), StringIO()
        with pytest.raises(CommandError, match="2 of 3 schedules failed to import"):
            call_command(
                "task_schedules", "--sync", "--no-input", stdout=out, stderr=err
            )

        assert "(1 created, 0 updated, 2 failed)" in out.getvalue()
        assert "bad-json: body is not JSON" in err.getvalue()
        assert "bad-shape: body is missing 'module'" in err.getvalue()
        assert TaskSchedule.objects.filter(schedule_id="good").exists()

    @patch(CMD_CLIENT)
    def test_database_failure_is_reported(self, client):
        client.schedule.list.return_value = [remote("mine")]
        with patch(
            "django_qstash.schedules.services.TaskSchedule.objects.update_or_create",
            side_effect=RuntimeError("db down"),
        ):
            with pytest.raises(CommandError, match="1 of 1 schedules failed"):
                run("--sync", "--no-input")

    @patch(CMD_CLIENT)
    def test_provider_failure_returns_error(self, client):
        client.schedule.list.side_effect = Exception("API Error")
        with pytest.raises(CommandError, match="Failed to list QStash schedules"):
            run("--list")

    @patch(CMD_CLIENT)
    def test_prompt_cancel(self, client):
        client.schedule.list.return_value = [remote("mine")]
        with patch("builtins.input", return_value="n"):
            out, _ = run("--sync")
        assert "Sync cancelled" in out
        assert TaskSchedule.objects.count() == 0

    @patch(CMD_CLIENT)
    def test_prompt_confirm(self, client):
        client.schedule.list.return_value = [remote("mine")]
        with patch("builtins.input", return_value="y"):
            run("--sync")
        assert TaskSchedule.objects.filter(schedule_id="mine").exists()

    @patch(CMD_CLIENT)
    def test_closed_stdin_without_no_input_fails(self, client):
        client.schedule.list.return_value = [remote("mine")]
        with patch("builtins.input", side_effect=EOFError):
            with pytest.raises(CommandError, match="--no-input"):
                run("--sync")
        assert TaskSchedule.objects.count() == 0

    @patch(CMD_CLIENT)
    def test_nothing_to_import(self, client, no_stdin):
        client.schedule.list.return_value = [remote("x", destination=OTHER_DEST)]
        out, _ = run("--sync")
        assert "Nothing to import." in out

    @patch("django_qstash.management.commands.task_schedules.apps")
    def test_schedules_app_missing(self, mock_apps):
        mock_apps.get_model.side_effect = LookupError("nope")
        with pytest.raises(CommandError, match="not installed"):
            run("--sync")

    @patch(CMD_CLIENT)
    def test_missing_domain_is_command_error(self, client):
        with patch(
            "django_qstash.management.commands.task_schedules.get_callback_url",
            side_effect=ImproperlyConfigured("DJANGO_QSTASH_DOMAIN is not set"),
        ):
            with pytest.raises(CommandError, match="DJANGO_QSTASH_DOMAIN"):
                run("--list")
        client.schedule.list.assert_not_called()


@pytest.mark.django_db
class TestAllDestinations:
    @patch(CMD_CLIENT)
    def test_list_all_destinations_shows_everything_read_only(self, client):
        client.schedule.list.return_value = [
            remote("mine"),
            remote("old-domain", destination="https://old.example.com/qstash/webhook/"),
            remote("foreign", destination="https://other.app/hook", body="not json"),
        ]
        out, _ = run("--list", "--all-destinations")

        assert "Found 1 remote schedules for destination" in out
        assert "Also showing 2 schedules with other destinations" in out
        for schedule_id in ("mine", "old-domain", "foreign"):
            assert f"Schedule ID: {schedule_id}" in out
        assert "Destination: https://old.example.com/qstash/webhook/" in out
        assert "not a django-qstash task payload" in out
        assert TaskSchedule.objects.count() == 0
        assert_no_remote_writes(client)

    @patch(CMD_CLIENT)
    def test_default_list_hints_at_flag(self, client):
        client.schedule.list.return_value = [remote("x", destination=OTHER_DEST)]
        out, _ = run("--list")
        assert "--all-destinations" in out
        assert "Schedule ID: x" not in out

    @patch(CMD_CLIENT)
    def test_rejected_with_sync(self, client):
        with pytest.raises(CommandError, match="only works with --list"):
            run("--sync", "--all-destinations", "--no-input")
        client.schedule.list.assert_not_called()
