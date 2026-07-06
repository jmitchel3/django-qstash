from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from django_qstash.db.models import TaskStatus
from django_qstash.results.services import build_dlq_requeue_payload
from django_qstash.results.services import build_requeue_payload
from django_qstash.results.services import calculate_task_metrics
from django_qstash.results.services import duration_to_ms
from django_qstash.results.services import function_result_to_dict
from django_qstash.results.services import requeue_dlq_message
from django_qstash.results.services import requeue_task_result
from django_qstash.results.services import requeue_task_result_by_id
from django_qstash.results.services import store_task_result
from django_qstash.results.services import successful_result_exists


class TestSuccessfulResultExists:
    def test_false_when_no_task_id(self):
        assert successful_result_exists(None) is False
        assert successful_result_exists("") is False

    @pytest.mark.django_db
    def test_true_after_success_stored(self):
        store_task_result(
            task_id="abc", task_name="t", status=TaskStatus.SUCCESS, result=1
        )
        assert successful_result_exists("abc") is True

    @pytest.mark.django_db
    def test_false_when_only_failure_stored(self):
        store_task_result(
            task_id="def", task_name="t", status=TaskStatus.EXECUTION_ERROR
        )
        assert successful_result_exists("def") is False

    def test_false_when_results_app_missing(self):
        with patch(
            "django_qstash.results.services.apps.get_model", side_effect=LookupError
        ):
            assert successful_result_exists("abc") is False


class TestFunctionResultToDict:
    def test_none_returns_none(self):
        assert function_result_to_dict(None) is None

    def test_dict_passthrough(self):
        assert function_result_to_dict({"a": 1}) == {"a": 1}

    def test_json_string_dict(self):
        assert function_result_to_dict('{"a": 1}') == {"a": 1}

    def test_json_string_non_dict_wrapped(self):
        assert function_result_to_dict("[1, 2]") == {"result": [1, 2]}

    def test_non_json_string_wrapped(self):
        assert function_result_to_dict("hello") == {"result": "hello"}

    def test_other_type_wrapped(self):
        assert function_result_to_dict(42) == {"result": 42}


class TestDurationToMs:
    def test_none_returns_none(self):
        assert duration_to_ms(None) is None

    def test_seconds_convert_to_ms(self):
        assert duration_to_ms(0.1234) == 123

    def test_negative_duration_clamps_to_zero(self):
        assert duration_to_ms(-1) == 0


@pytest.mark.django_db
class TestStoreTaskResult:
    def test_stores_valid_result(self):
        from django_qstash.results.models import TaskResult

        obj = store_task_result(
            task_id="t1",
            task_name="name",
            status=TaskStatus.SUCCESS,
            result={"x": 1},
        )
        assert obj is not None
        assert obj.result == {"x": 1}
        assert TaskResult.objects.filter(pk=obj.pk).exists()

    def test_invalid_status_becomes_unknown(self):
        obj = store_task_result(
            task_id="t2",
            task_name="name",
            status="NOT-A-REAL-STATUS",
        )
        assert obj is not None
        assert obj.status == TaskStatus.UNKNOWN

    def test_stores_lineage_and_duration(self):
        obj = store_task_result(
            task_id="t3",
            task_name="name",
            status=TaskStatus.SUCCESS,
            correlation_id="root-1",
            parent_task_id="parent-1",
            attempt=2,
            duration_ms=42,
        )
        assert obj is not None
        assert obj.correlation_id == "root-1"
        assert obj.parent_task_id == "parent-1"
        assert obj.attempt == 2
        assert obj.duration_ms == 42


@pytest.mark.django_db
class TestTaskMetrics:
    def test_calculate_task_metrics(self):
        from django_qstash.results.models import TaskResult

        now = timezone.now()
        TaskResult.objects.create(
            task_id="success",
            task_name="task",
            status=TaskStatus.SUCCESS,
            date_done=now,
            duration_ms=100,
        )
        TaskResult.objects.create(
            task_id="failure",
            task_name="task",
            status=TaskStatus.EXECUTION_ERROR,
            date_done=now,
            duration_ms=400,
        )
        TaskResult.objects.create(
            task_id="old",
            task_name="task",
            status=TaskStatus.SUCCESS,
            date_done=now - timedelta(hours=2),
            duration_ms=10,
        )

        metrics = calculate_task_metrics(window_seconds=60, now=now)

        assert metrics["total"] == 2
        assert metrics["counts_by_status"] == {
            TaskStatus.EXECUTION_ERROR: 1,
            TaskStatus.SUCCESS: 1,
        }
        assert metrics["success_rate"] == 0.5
        assert metrics["duration_ms"] == {"p50": 100, "p95": 400}

    def test_calculate_task_metrics_without_results_app(self):
        now = timezone.now()
        with patch(
            "django_qstash.results.services.apps.get_model",
            side_effect=LookupError,
        ):
            metrics = calculate_task_metrics(window_seconds=60, now=now)
        assert metrics["total"] == 0
        assert metrics["duration_ms"] == {"p50": None, "p95": None}

    def test_calculate_task_metrics_without_rows(self):
        now = timezone.now()

        metrics = calculate_task_metrics(window_seconds=60, now=now)

        assert metrics["total"] == 0
        assert metrics["duration_ms"] == {"p50": None, "p95": None}


@pytest.mark.django_db
class TestRequeueTaskResult:
    @patch("django_qstash.results.services.qstash_client")
    def test_requeue_task_result_publishes_payload(self, mock_client):
        from django_qstash.results.models import TaskResult

        response = mock_client.message.publish_json.return_value
        response.message_id = "new-msg"
        task_result = TaskResult.objects.create(
            task_id="failed-msg",
            task_name="emails.send",
            status=TaskStatus.EXECUTION_ERROR,
            function_path="emails.tasks.send",
            args=[1],
            kwargs={"force": True},
            correlation_id="root-1",
            attempt=1,
        )

        result = requeue_task_result(task_result)

        assert result.message_id == "new-msg"
        assert result.correlation_id == "root-1"
        body = mock_client.message.publish_json.call_args.kwargs["body"]
        assert body == {
            "function": "send",
            "module": "emails.tasks",
            "args": [1],
            "kwargs": {"force": True},
            "task_name": "emails.send",
            "correlation_id": "root-1",
            "parent_task_id": "failed-msg",
            "attempt": 2,
        }

    @patch("django_qstash.results.services.qstash_client")
    def test_requeue_task_result_can_target_queue(self, mock_client):
        from django_qstash.results.models import TaskResult

        response = mock_client.message.enqueue_json.return_value
        response.message_id = "queued-msg"
        task_result = TaskResult.objects.create(
            task_id="failed-msg",
            task_name="emails.send",
            status=TaskStatus.EXECUTION_ERROR,
            function_path="emails.tasks.send",
        )

        result = requeue_task_result(task_result, queue="emails")

        assert result.message_id == "queued-msg"
        mock_client.message.enqueue_json.assert_called_once()
        assert mock_client.message.enqueue_json.call_args.kwargs["queue"] == "emails"

    @patch("django_qstash.results.services.qstash_client")
    def test_requeue_task_result_requires_message_id(self, mock_client):
        from django_qstash.results.models import TaskResult

        mock_client.message.publish_json.return_value.message_id = ""
        task_result = TaskResult.objects.create(
            task_id="failed-msg",
            task_name="emails.send",
            status=TaskStatus.EXECUTION_ERROR,
            function_path="emails.tasks.send",
        )

        with pytest.raises(ValueError, match="message id"):
            requeue_task_result(task_result)

    def test_build_requeue_payload_requires_function_path(self):
        from django_qstash.results.models import TaskResult

        task_result = TaskResult.objects.create(
            task_id="failed-msg",
            task_name="emails.send",
            status=TaskStatus.EXECUTION_ERROR,
        )
        with pytest.raises(ValueError, match="function_path"):
            build_requeue_payload(task_result)

    def test_success_result_is_not_requeueable_without_force(self):
        from django_qstash.results.models import TaskResult

        task_result = TaskResult.objects.create(
            task_id="success-msg",
            task_name="emails.send",
            status=TaskStatus.SUCCESS,
            function_path="emails.tasks.send",
        )
        with pytest.raises(ValueError, match="not requeueable"):
            requeue_task_result(task_result)

    @patch("django_qstash.results.services.qstash_client")
    def test_requeue_task_result_by_task_id(self, mock_client):
        from django_qstash.results.models import TaskResult

        mock_client.message.publish_json.return_value.message_id = "new-msg"
        TaskResult.objects.create(
            task_id="failed-msg",
            task_name="emails.send",
            status=TaskStatus.EXECUTION_ERROR,
            function_path="emails.tasks.send",
        )

        result = requeue_task_result_by_id("failed-msg")

        assert result.message_id == "new-msg"

    def test_requeue_task_result_by_id_missing(self):
        with pytest.raises(ValueError, match="No TaskResult"):
            requeue_task_result_by_id("missing")


class TestRequeueDlqMessage:
    def test_build_dlq_requeue_payload(self):
        message = type(
            "Message",
            (),
            {
                "message_id": "dlq-msg",
                "body": (
                    '{"function": "send", "module": "emails.tasks", '
                    '"args": [], "kwargs": {}, "attempt": 2}'
                ),
            },
        )()

        payload = build_dlq_requeue_payload(message)

        assert payload["correlation_id"] == "dlq-msg"
        assert payload["parent_task_id"] == "dlq-msg"
        assert payload["attempt"] == 3

    def test_build_dlq_requeue_payload_accepts_bytes_body(self):
        message = type(
            "Message",
            (),
            {
                "message_id": "dlq-msg",
                "body": b'{"function": "send", "module": "emails.tasks"}',
            },
        )()

        payload = build_dlq_requeue_payload(message)

        assert payload["function"] == "send"
        assert payload["correlation_id"] == "dlq-msg"

    def test_build_dlq_requeue_payload_rejects_non_object_body(self):
        message = type("Message", (), {"message_id": "dlq-msg", "body": "[]"})()
        with pytest.raises(ValueError, match="JSON object"):
            build_dlq_requeue_payload(message)

    def test_build_dlq_requeue_payload_rejects_unsupported_body_type(self):
        message = type("Message", (), {"message_id": "dlq-msg", "body": object()})()
        with pytest.raises(ValueError, match="JSON object"):
            build_dlq_requeue_payload(message)

    @patch("django_qstash.results.services.qstash_client")
    def test_requeue_dlq_message_deletes_after_requeue(self, mock_client):
        message = mock_client.dlq.get.return_value
        message.message_id = "dlq-msg"
        message.url = "https://example.com/qstash/webhook/"
        message.body = {
            "function": "send",
            "module": "emails.tasks",
            "args": [],
            "kwargs": {},
        }
        mock_client.message.publish_json.return_value.message_id = "new-msg"

        result = requeue_dlq_message("dlq-1", delete_after_requeue=True)

        assert result.message_id == "new-msg"
        mock_client.dlq.delete.assert_called_once_with("dlq-1")

    @patch("django_qstash.results.services.qstash_client")
    def test_requeue_dlq_message_keeps_dlq_by_default(self, mock_client):
        message = mock_client.dlq.get.return_value
        message.message_id = "dlq-msg"
        message.url = "https://example.com/qstash/webhook/"
        message.body = {
            "function": "send",
            "module": "emails.tasks",
            "args": [],
            "kwargs": {},
        }
        mock_client.message.publish_json.return_value.message_id = "new-msg"

        result = requeue_dlq_message("dlq-1")

        assert result.message_id == "new-msg"
        mock_client.dlq.delete.assert_not_called()


def test_store_task_result_model_not_installed():
    """When the results model isn't installed, store quietly returns None."""
    with patch(
        "django_qstash.results.services.apps.get_model", side_effect=LookupError
    ):
        result = store_task_result(
            task_id="t",
            task_name="name",
            status=TaskStatus.SUCCESS,
        )
    assert result is None
