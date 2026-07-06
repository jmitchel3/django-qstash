from __future__ import annotations

from unittest.mock import Mock
from unittest.mock import patch

from django.core.management import call_command


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


def test_qstash_requeue_requires_exactly_one_identifier(capsys):
    call_command("qstash_requeue", "--result-id", "result-1", "--task-id", "task-1")

    captured = capsys.readouterr()
    assert "Specify exactly one" in captured.out


@patch("django_qstash.management.commands.qstash_requeue.requeue_task_result_by_id")
def test_qstash_requeue_reports_errors(mock_requeue, capsys):
    mock_requeue.side_effect = ValueError("nope")

    call_command("qstash_requeue", "--task-id", "task-1")

    captured = capsys.readouterr()
    assert "An error occurred: nope" in captured.out
