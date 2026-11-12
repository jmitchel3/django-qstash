from __future__ import annotations

import logging
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.db import transaction
from django.test import override_settings

from django_qstash.app import stashed_task

EAGER_CALLS: list[tuple[int, int]] = []


@stashed_task
def add(x, y):
    return x + y


@stashed_task
def record_eager(x, y):
    EAGER_CALLS.append((x, y))
    return x + y


@pytest.fixture(autouse=True)
def mock_qstash_client():
    with patch("django_qstash.app.base.qstash_client") as mock_client:
        mock_message = Mock()
        mock_response = Mock()
        mock_response.message_id = "test-id-123"
        mock_message.publish_json = Mock(return_value=mock_response)
        mock_message.enqueue_json = Mock(return_value=mock_response)
        mock_client.message = mock_message
        yield mock_client


@pytest.fixture(autouse=True)
def clear_eager_calls():
    EAGER_CALLS.clear()
    yield
    EAGER_CALLS.clear()


def _published_bodies(mock_client: Mock) -> list[dict]:
    return [
        call.kwargs["body"] for call in mock_client.message.publish_json.call_args_list
    ]


# transaction=True runs these tests without a wrapping atomic block, so
# transaction.atomic() really commits (or rolls back) and on_commit callbacks
# fire exactly as they would in production.
pytestmark = pytest.mark.django_db(transaction=True)


def test_delay_on_commit_publishes_after_outer_atomic_exits(mock_qstash_client):
    with transaction.atomic():
        with transaction.atomic():
            assert add.delay_on_commit(1, 2) is None
        mock_qstash_client.message.publish_json.assert_not_called()
    mock_qstash_client.message.publish_json.assert_called_once()
    body = _published_bodies(mock_qstash_client)[0]
    assert body["args"] == (1, 2)
    assert body["kwargs"] == {}


def test_apply_async_on_commit_publishes_after_commit_with_options(
    mock_qstash_client,
):
    with transaction.atomic():
        result = add.apply_async_on_commit(
            args=(1,), kwargs={"y": 2}, countdown=10, label="on-commit"
        )
        assert result is None
        mock_qstash_client.message.publish_json.assert_not_called()
    mock_qstash_client.message.publish_json.assert_called_once()
    call = mock_qstash_client.message.publish_json.call_args
    assert call.kwargs["body"]["args"] == (1,)
    assert call.kwargs["body"]["kwargs"] == {"y": 2}
    assert call.kwargs["delay"] == "10s"
    assert call.kwargs["label"] == "on-commit"


def test_apply_async_on_commit_routes_queue_option(mock_qstash_client):
    with transaction.atomic():
        add.apply_async_on_commit(args=(1, 2), queue="fifo")
    mock_qstash_client.message.publish_json.assert_not_called()
    mock_qstash_client.message.enqueue_json.assert_called_once()
    assert mock_qstash_client.message.enqueue_json.call_args.kwargs["queue"] == "fifo"


def test_full_rollback_publishes_nothing(mock_qstash_client):
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            add.delay_on_commit(1, 2)
            add.apply_async_on_commit(args=(3, 4))
            raise RuntimeError("boom")
    mock_qstash_client.message.publish_json.assert_not_called()


def test_savepoint_rollback_discards_only_inner_call(mock_qstash_client):
    with transaction.atomic():
        add.delay_on_commit(1, 1)
        try:
            with transaction.atomic():
                add.delay_on_commit(2, 2)
                raise RuntimeError("inner")
        except RuntimeError:
            pass
        add.delay_on_commit(3, 3)
    bodies = _published_bodies(mock_qstash_client)
    assert [body["args"] for body in bodies] == [(1, 1), (3, 3)]


def test_outside_transaction_publishes_immediately(mock_qstash_client):
    add.delay_on_commit(1, 2)
    mock_qstash_client.message.publish_json.assert_called_once()
    add.apply_async_on_commit(args=(3, 4))
    assert mock_qstash_client.message.publish_json.call_count == 2


@pytest.mark.django_db(transaction=True, databases=["default", "other"])
def test_non_default_alias_waits_for_that_alias(mock_qstash_client):
    with transaction.atomic(using="other"):
        add.apply_async_on_commit(args=(1, 2), using="other")
        mock_qstash_client.message.publish_json.assert_not_called()
    mock_qstash_client.message.publish_json.assert_called_once()


@pytest.mark.django_db(transaction=True, databases=["default", "other"])
def test_non_default_alias_ignores_default_transaction(mock_qstash_client):
    # The "other" connection is in autocommit, so the callback runs at once
    # even though a transaction is open on "default".
    with transaction.atomic(using="default"):
        add.apply_async_on_commit(args=(1, 2), using="other")
        mock_qstash_client.message.publish_json.assert_called_once()


@pytest.mark.django_db(transaction=True, databases=["default", "other"])
def test_non_default_alias_rollback_publishes_nothing(mock_qstash_client):
    with pytest.raises(RuntimeError):
        with transaction.atomic(using="other"):
            add.apply_async_on_commit(args=(1, 2), using="other")
            raise RuntimeError("boom")
    mock_qstash_client.message.publish_json.assert_not_called()


@override_settings(DJANGO_QSTASH_ALWAYS_EAGER=True)
def test_eager_mode_respects_commit_boundary(mock_qstash_client):
    with transaction.atomic():
        record_eager.delay_on_commit(1, 2)
        record_eager.apply_async_on_commit(args=(3, 4))
        assert EAGER_CALLS == []
    assert EAGER_CALLS == [(1, 2), (3, 4)]
    mock_qstash_client.message.publish_json.assert_not_called()


@override_settings(DJANGO_QSTASH_ALWAYS_EAGER=True)
def test_eager_mode_rollback_runs_nothing():
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            record_eager.delay_on_commit(1, 2)
            raise RuntimeError("boom")
    assert EAGER_CALLS == []


def test_provider_failure_after_commit_raises(mock_qstash_client, caplog):
    mock_qstash_client.message.publish_json.side_effect = ConnectionError("down")
    with caplog.at_level(logging.ERROR, logger="django_qstash"):
        with pytest.raises(ConnectionError):
            with transaction.atomic():
                add.apply_async_on_commit(args=(1, 2))
    records = [r for r in caplog.records if r.getMessage() == "task_enqueue_failed"]
    assert len(records) == 1
    assert records[0].name == "django_qstash.app.base"
    assert records[0].task_name == "add"
    assert records[0].robust is False


def test_provider_failure_robust_logs_and_does_not_raise(mock_qstash_client, caplog):
    mock_qstash_client.message.publish_json.side_effect = ConnectionError("down")
    with caplog.at_level(logging.ERROR):
        with transaction.atomic():
            add.apply_async_on_commit(
                args=(1, 2), robust=True, _qstash_correlation_id="corr-1"
            )
    records = [r for r in caplog.records if r.getMessage() == "task_enqueue_failed"]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.ERROR
    assert record.task == f"{__name__}.add"
    assert record.task_name == "add"
    assert record.correlation_id == "corr-1"
    assert record.error_type == "ConnectionError"
    assert record.robust is True
    assert record.exc_info is not None
    mock_qstash_client.message.publish_json.assert_called_once()


def test_provider_failure_robust_does_not_block_other_callbacks(
    mock_qstash_client,
):
    response = Mock(message_id="ok")
    mock_qstash_client.message.publish_json.side_effect = [
        ConnectionError("down"),
        response,
    ]
    with transaction.atomic():
        add.apply_async_on_commit(args=(1, 2), robust=True)
        add.apply_async_on_commit(args=(3, 4))
    assert mock_qstash_client.message.publish_json.call_count == 2


def test_arguments_captured_at_call_time(mock_qstash_client):
    args = [1, 2]
    kwargs = {"y": 2}
    options = {"label": "before"}
    with transaction.atomic():
        add.apply_async_on_commit(args=args, kwargs=kwargs, **options)
        add.delay_on_commit(*args, **kwargs)
        args.append(99)
        kwargs["y"] = 99
        kwargs["z"] = 1
        options["label"] = "after"
    first, second = mock_qstash_client.message.publish_json.call_args_list
    assert first.kwargs["body"]["args"] == (1, 2)
    assert first.kwargs["body"]["kwargs"] == {"y": 2}
    assert first.kwargs["label"] == "before"
    assert second.kwargs["body"]["args"] == (1, 2)
    assert second.kwargs["body"]["kwargs"] == {"y": 2}


@pytest.mark.django_db
def test_with_django_capture_on_commit_callbacks(
    mock_qstash_client, django_capture_on_commit_callbacks
):
    # Documented testing pattern for TestCase-style (non-transactional) tests.
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        add.delay_on_commit(1, 2)
    assert len(callbacks) == 1
    mock_qstash_client.message.publish_json.assert_called_once()
