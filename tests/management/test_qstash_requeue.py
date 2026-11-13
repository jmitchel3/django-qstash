from __future__ import annotations

from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from django_qstash.management.commands.qstash_requeue import Command


@patch("django_qstash.management.commands.qstash_requeue.requeue_task_result_by_id")
def test_qstash_requeue_result_id(mock_requeue, capsys):
    result = Mock()
    result.message_id = "msg-new"
    result.correlation_id = "root-1"
    mock_requeue.return_value = result

    call_command("qstash_requeue", "--result-id", "result-1", "--queue", "emails")

    mock_requeue.assert_called_once_with("result-1", queue="emails", force=False)
    captured = capsys.readouterr()
    assert "Requeued task as msg-new (correlation root-1)" in captured.out


@patch("django_qstash.management.commands.qstash_requeue.requeue_task_result_by_id")
def test_qstash_requeue_task_id_force(mock_requeue, capsys):
    result = Mock()
    result.message_id = "msg-new"
    result.correlation_id = "root-1"
    mock_requeue.return_value = result

    call_command("qstash_requeue", "--task-id", "task-1", "--force")

    mock_requeue.assert_called_once_with("task-1", queue=None, force=True)
    captured = capsys.readouterr()
    assert "Requeued task as msg-new" in captured.out


@patch("django_qstash.management.commands.qstash_requeue.requeue_dlq_message")
def test_qstash_requeue_dlq_id(mock_requeue, capsys):
    result = Mock()
    result.message_id = "msg-new"
    result.correlation_id = "root-1"
    mock_requeue.return_value = result

    call_command("qstash_requeue", "--dlq-id", "dlq-1", "--delete-dlq")

    mock_requeue.assert_called_once_with(
        "dlq-1",
        delete_after_requeue=True,
        queue=None,
    )
    captured = capsys.readouterr()
    assert "Requeued task as msg-new" in captured.out


@pytest.mark.parametrize(
    "args", [[], ["--result-id", "result-1", "--task-id", "task-1"]]
)
def test_qstash_requeue_requires_exactly_one_identifier(args, capsys):
    with pytest.raises(CommandError, match="Specify exactly one"):
        call_command("qstash_requeue", *args)
    assert capsys.readouterr().out == ""


@patch("django_qstash.management.commands.qstash_requeue.requeue_task_result_by_id")
def test_qstash_requeue_reports_errors(mock_requeue, capsys):
    mock_requeue.side_effect = ValueError("nope")

    with pytest.raises(CommandError, match="Failed to requeue task: nope"):
        call_command("qstash_requeue", "--task-id", "task-1")
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("args", [[], ["--task-id", "task-1", "--dlq-id", "dlq-1"]])
def test_qstash_requeue_invalid_identifiers_exit_nonzero(args, capsys):
    with pytest.raises(SystemExit) as exc:
        Command().run_from_argv(["manage.py", "qstash_requeue", *args])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "CommandError: Specify exactly one" in captured.err


@pytest.mark.parametrize(
    ("flag", "service"),
    [
        ("--task-id", "requeue_task_result_by_id"),
        ("--dlq-id", "requeue_dlq_message"),
    ],
)
def test_qstash_requeue_provider_failure_exits_nonzero(flag, service, capsys):
    with patch(
        f"django_qstash.management.commands.qstash_requeue.{service}",
        side_effect=ConnectionError("provider unavailable"),
    ):
        with pytest.raises(SystemExit) as exc:
            Command().run_from_argv(["manage.py", "qstash_requeue", flag, "failed-1"])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "CommandError: Failed to requeue task: provider unavailable" in captured.err
