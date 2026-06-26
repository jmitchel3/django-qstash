from __future__ import annotations

from unittest.mock import Mock
from unittest.mock import patch

from django.core.management import call_command

from django_qstash.management.commands.qstash_dlq import _display
from django_qstash.management.commands.qstash_dlq import _truncate


def _dlq_message(**overrides):
    message = Mock()
    message.dlq_id = "dlq-123"
    message.message_id = "msg-123"
    message.response_status = 422
    message.url = "https://example.com/qstash/webhook/"
    message.queue = "emails"
    message.schedule_id = "schedule-123"
    message.label = "scheduled,email"
    message.response_body = "Task execution failed"
    message.body = '{"task_name": "Daily Email Digest"}'
    for key, value in overrides.items():
        setattr(message, key, value)
    return message


@patch("django_qstash.management.commands.qstash_dlq.qstash_client")
def test_list_dlq_messages(mock_client, capsys):
    response = Mock()
    response.cursor = "next-cursor"
    response.messages = [_dlq_message()]
    mock_client.dlq.list.return_value = response

    call_command(
        "qstash_dlq",
        "--list",
        "--count",
        "10",
        "--queue",
        "emails",
        "--label",
        "scheduled,email",
        "--response-status",
        "422",
    )

    mock_client.dlq.list.assert_called_once_with(
        cursor=None,
        count=10,
        filter={
            "queue": "emails",
            "response_status": 422,
            "label": "scheduled,email",
        },
    )
    captured = capsys.readouterr()
    assert "Found 1 DLQ messages" in captured.out
    assert "DLQ ID: dlq-123" in captured.out
    assert "Status: 422" in captured.out
    assert "Next cursor: next-cursor" in captured.out


@patch("django_qstash.management.commands.qstash_dlq.qstash_client")
def test_list_dlq_messages_without_filters(mock_client, capsys):
    response = Mock()
    response.cursor = None
    response.messages = []
    mock_client.dlq.list.return_value = response

    call_command("qstash_dlq", "--list")

    mock_client.dlq.list.assert_called_once_with(
        cursor=None,
        count=None,
        filter=None,
    )
    captured = capsys.readouterr()
    assert "Found 0 DLQ messages" in captured.out


@patch("django_qstash.management.commands.qstash_dlq.qstash_client")
def test_get_dlq_message(mock_client, capsys):
    mock_client.dlq.get.return_value = _dlq_message()

    call_command("qstash_dlq", "--get", "dlq-123")

    mock_client.dlq.get.assert_called_once_with("dlq-123")
    captured = capsys.readouterr()
    assert "DLQ ID: dlq-123" in captured.out
    assert 'Body: {"task_name": "Daily Email Digest"}' in captured.out


@patch("django_qstash.management.commands.qstash_dlq.qstash_client")
def test_delete_dlq_message(mock_client, capsys):
    call_command("qstash_dlq", "--delete", "dlq-123")

    mock_client.dlq.delete.assert_called_once_with("dlq-123")
    captured = capsys.readouterr()
    assert "Deleted DLQ message dlq-123" in captured.out


@patch("django_qstash.management.commands.qstash_dlq.qstash_client")
def test_delete_many_dlq_messages(mock_client, capsys):
    mock_client.dlq.delete_many.return_value = 2

    call_command("qstash_dlq", "--delete-many", "dlq-123", "dlq-456")

    mock_client.dlq.delete_many.assert_called_once_with(["dlq-123", "dlq-456"])
    captured = capsys.readouterr()
    assert "Deleted 2 DLQ messages" in captured.out


def test_qstash_dlq_no_options(capsys):
    call_command("qstash_dlq")

    captured = capsys.readouterr()
    assert "Please specify --list, --get, --delete, or --delete-many" in captured.out


def test_display_empty_values_render_dash():
    """_display renders a dash for None and empty-string values."""
    assert _display(None) == "-"
    assert _display("") == "-"


def test_truncate_long_value():
    """_truncate shortens values longer than the max length with an ellipsis."""
    text = "x" * 300
    truncated = _truncate(text, max_length=10)
    assert truncated == "xxxxxxx..."
    assert len(truncated) == 10


@patch("django_qstash.management.commands.qstash_dlq.qstash_client")
def test_qstash_dlq_api_error(mock_client, capsys):
    mock_client.dlq.list.side_effect = Exception("API Error")

    call_command("qstash_dlq", "--list")

    captured = capsys.readouterr()
    assert "An error occurred: API Error" in captured.out
