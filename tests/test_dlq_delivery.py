from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import create_autospec
from unittest.mock import patch

import pytest
from qstash.dlq import parse_dlq_message_response
from qstash.message import MessageApi

from django_qstash.results.services import requeue_dlq_message


def dlq_message(**overrides):
    response = {
        "messageId": "failed-message",
        "url": "https://original.example.com/qstash/webhook/",
        "method": "POST",
        "maxRetries": 3,
        "notBefore": 1700000000000,
        "createdAt": 1700000000000,
        "responseStatus": 500,
        "body": json.dumps(
            {"module": "emails.tasks", "function": "send", "args": [], "kwargs": {}}
        ),
    }
    response.update(overrides)
    return parse_dlq_message_response(response, "dlq-id")


@pytest.fixture
def client():
    # Real SDK signatures catch passing publish-only options to enqueue_json.
    message_api = create_autospec(MessageApi, instance=True)
    message_api.publish_json.return_value = SimpleNamespace(message_id="new-message")
    message_api.enqueue_json.return_value = SimpleNamespace(message_id="new-message")
    client = SimpleNamespace(message=message_api, dlq=Mock())
    with patch("django_qstash.results.services.qstash_client", client):
        yield client


def test_direct_requeue_preserves_delivery_controls_without_old_scheduling(client):
    original_body = {
        "module": "emails.tasks",
        "function": "send",
        "args": [],
        "kwargs": {},
        "options": {
            "timeout": "45s",
            "redact": {"body": True, "header": ["Authorization"]},
            "delay": "5m",
            "not_before": 1700000000,
            "deduplication_id": "original-dedup-id",
            "content_based_deduplication": True,
            "max_retries": 1,
            "headers": {"Authorization": "stale-token"},
        },
    }
    message = dlq_message(
        body=json.dumps(original_body),
        header={"Authorization": ["Bearer current-token"], "X-Values": ["a", "b"]},
        callback="https://callbacks.example.com/success",
        callbackHeader={"Authorization": ["callback-token"]},
        failureCallback="https://callbacks.example.com/failure",
        failureCallbackHeader={"Authorization": ["failure-token"]},
        retryDelayExpression="1000 * (1 + retried)",
        flowControlKey="emails",
        parallelism=2,
        rate=10,
        period=60,
        label="billing",
    )
    client.dlq.get.return_value = message

    result = requeue_dlq_message("dlq-id", delete_after_requeue=True)

    assert result.message_id == "new-message"
    client.message.enqueue_json.assert_not_called()
    sent = dict(client.message.publish_json.call_args.kwargs)
    body = sent.pop("body")
    assert body["module"] == "emails.tasks"
    assert sent == {
        "url": message.url,
        "method": "POST",
        "headers": {"Authorization": "Bearer current-token", "X-Values": "a,b"},
        "callback": "https://callbacks.example.com/success",
        "callback_headers": {"Authorization": "callback-token"},
        "failure_callback": "https://callbacks.example.com/failure",
        "failure_callback_headers": {"Authorization": "failure-token"},
        "retries": 3,
        "retry_delay": "1000 * (1 + retried)",
        "flow_control": {"key": "emails", "parallelism": 2, "rate": 10, "period": 60},
        "label": "billing",
        "timeout": "45s",
        "redact": {"body": True, "header": ["Authorization"]},
    }
    client.dlq.delete.assert_called_once_with("dlq-id")
    assert json.loads(message.body) == original_body


def test_requeue_keeps_original_queue_and_zero_retries(client):
    client.dlq.get.return_value = dlq_message(
        queueName="serial-emails",
        maxRetries=0,
        header={"Authorization": ["required-token"]},
    )

    requeue_dlq_message("dlq-id")

    client.message.publish_json.assert_not_called()
    sent = client.message.enqueue_json.call_args.kwargs
    assert sent["queue"] == "serial-emails"
    assert sent["retries"] == 0
    assert sent["headers"] == {"Authorization": "required-token"}
    client.dlq.delete.assert_not_called()


@pytest.mark.parametrize("original_queue", [None, "original-queue"])
def test_queue_override_preserves_headers_and_uses_queue_controls(
    client, original_queue
):
    client.dlq.get.return_value = dlq_message(
        queueName=original_queue,
        header={"Authorization": ["required-token"]},
        flowControlKey="original-flow",
        rate=2,
    )

    requeue_dlq_message("dlq-id", queue="recovery-queue")

    client.message.publish_json.assert_not_called()
    sent = client.message.enqueue_json.call_args.kwargs
    assert sent["queue"] == "recovery-queue"
    assert sent["headers"] == {"Authorization": "required-token"}
    assert "flow_control" not in sent


def test_explicit_empty_queue_switches_to_direct_delivery(client):
    client.dlq.get.return_value = dlq_message(queueName="original-queue")

    requeue_dlq_message("dlq-id", queue="")

    client.message.publish_json.assert_called_once()
    client.message.enqueue_json.assert_not_called()


def test_optional_controls_absent_from_dlq_are_not_invented(client):
    client.dlq.get.return_value = dlq_message()

    requeue_dlq_message("dlq-id")

    sent = client.message.publish_json.call_args.kwargs
    assert set(sent) == {"url", "body", "method", "retries"}


def test_failed_republish_keeps_dlq_message(client):
    client.dlq.get.return_value = dlq_message(queueName="original-queue")
    client.message.enqueue_json.side_effect = ConnectionError("provider unavailable")

    with pytest.raises(ConnectionError, match="provider unavailable"):
        requeue_dlq_message("dlq-id", delete_after_requeue=True)

    client.dlq.delete.assert_not_called()
