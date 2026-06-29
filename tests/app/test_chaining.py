from __future__ import annotations

from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.test import override_settings

from django_qstash.app import stashed_task
from django_qstash.app.base import Signature
from django_qstash.app.base import _normalize_links
from django_qstash.app.base import enqueue_links

RECORD: list[tuple[str, tuple]] = []


@stashed_task
def first_task(x, y):
    RECORD.append(("first", (x, y)))
    return x + y


@stashed_task
def second_task(label):
    RECORD.append(("second", (label,)))
    return f"done:{label}"


@stashed_task
def third_task():
    RECORD.append(("third", ()))
    return "third"


@pytest.fixture(autouse=True)
def clear_record():
    RECORD.clear()
    yield
    RECORD.clear()


@pytest.fixture(autouse=True)
def mock_qstash_client():
    with patch("django_qstash.app.base.qstash_client") as mock_client:
        mock_message = Mock()
        mock_response = Mock()
        mock_response.message_id = "chain-msg-1"
        mock_message.publish_json = Mock(return_value=mock_response)
        mock_message.enqueue_json = Mock(return_value=mock_response)
        mock_client.message = mock_message
        yield mock_client


class TestSignature:
    def test_s_captures_call(self):
        """.s() captures the function path, args, and kwargs."""
        sig = second_task.s("hello")
        assert isinstance(sig, Signature)
        assert sig.function == "second_task"
        assert sig.function_path.endswith(".second_task")
        assert sig.args == ("hello",)
        assert sig.immutable is False

    def test_si_is_immutable(self):
        """.si() sets the immutable flag (behavior otherwise identical)."""
        assert second_task.si("x").immutable is True

    def test_to_dict_roundtrip_shape(self):
        """to_dict() serializes the JSON-friendly link form."""
        data = second_task.s("hi", flag=True).to_dict()
        assert data["function"] == "second_task"
        assert data["args"] == ["hi"]
        assert data["kwargs"] == {"flag": True}
        assert data["options"] == {}


class TestNormalizeLinks:
    def test_none(self):
        assert _normalize_links(None) == []

    def test_single(self):
        sig = second_task.s("a")
        assert _normalize_links(sig) == [sig]

    def test_list(self):
        sigs = [second_task.s("a"), third_task.s()]
        assert _normalize_links(sigs) == sigs


class TestApplyAsyncSerializesLinks:
    def test_single_link_serialized(self, mock_qstash_client):
        """apply_async(link=sig) writes on_success into the QStash payload."""
        first_task.apply_async(args=(1, 2), link=second_task.s("next"))

        body = mock_qstash_client.message.publish_json.call_args.kwargs["body"]
        assert "on_success" in body
        assert len(body["on_success"]) == 1
        assert body["on_success"][0]["function"] == "second_task"
        assert body["on_success"][0]["args"] == ["next"]

    def test_multiple_links_serialized(self, mock_qstash_client):
        """apply_async(link=[a, b]) serializes every link."""
        first_task.apply_async(
            args=(1, 2),
            link=[second_task.s("a"), third_task.s()],
        )
        body = mock_qstash_client.message.publish_json.call_args.kwargs["body"]
        functions = [item["function"] for item in body["on_success"]]
        assert functions == ["second_task", "third_task"]

    def test_no_link_has_no_on_success(self, mock_qstash_client):
        """Without link=, no on_success key is added to the payload."""
        first_task.apply_async(args=(1, 2))
        body = mock_qstash_client.message.publish_json.call_args.kwargs["body"]
        assert "on_success" not in body


class TestEnqueueLinks:
    def test_empty_returns_early(self):
        """An empty link list does nothing (and never touches discovery)."""
        with patch("django_qstash.app.base.discover_tasks") as mock_discover:
            enqueue_links([])
        mock_discover.assert_not_called()

    def test_registered_link_enqueued(self):
        """A registered link is resolved and its apply_async is called."""
        sig = second_task.s("z")
        mock_task = Mock()
        with (
            patch(
                "django_qstash.app.base.discover_tasks",
                return_value=[sig.function_path],
            ),
            patch(
                "django_qstash.app.base.import_string",
                return_value=mock_task,
            ),
        ):
            enqueue_links([sig.to_dict()])
        mock_task.apply_async.assert_called_once_with(args=("z",), kwargs={})

    def test_unregistered_link_skipped(self):
        """A link that is not in the allowlist is skipped, not enqueued."""
        sig = second_task.s("z")
        with (
            patch("django_qstash.app.base.discover_tasks", return_value=[]),
            patch("django_qstash.app.base.import_string") as mock_import,
        ):
            enqueue_links([sig.to_dict()])
        mock_import.assert_not_called()

    def test_import_error_skipped(self):
        """A registered link that fails to import is logged and skipped."""
        sig = second_task.s("z")
        with (
            patch(
                "django_qstash.app.base.discover_tasks",
                return_value=[sig.function_path],
            ),
            patch(
                "django_qstash.app.base.import_string",
                side_effect=ImportError("nope"),
            ),
        ):
            # Should not raise.
            enqueue_links([sig.to_dict()])

    def test_discovery_failure_skips_all(self):
        """If discovery itself fails, links are skipped without raising."""
        sig = second_task.s("z")
        with (
            patch(
                "django_qstash.app.base.discover_tasks",
                side_effect=RuntimeError("boom"),
            ),
            patch("django_qstash.app.base.import_string") as mock_import,
        ):
            enqueue_links([sig.to_dict()])
        mock_import.assert_not_called()


class TestEagerChaining:
    @override_settings(DJANGO_QSTASH_ALWAYS_EAGER=True)
    def test_link_runs_inline_after_success(self):
        """In eager mode, a linked task runs inline after the parent succeeds."""
        sig = second_task.s("chained")
        with (
            patch(
                "django_qstash.app.base.discover_tasks",
                return_value=[sig.function_path],
            ),
            patch(
                "django_qstash.app.base.import_string",
                return_value=second_task,
            ),
        ):
            result = first_task.apply_async(args=(1, 2), link=sig)

        assert result.get() == 3
        assert ("first", (1, 2)) in RECORD
        assert ("second", ("chained",)) in RECORD

    @override_settings(DJANGO_QSTASH_ALWAYS_EAGER=True)
    def test_apply_runs_multiple_links(self):
        """apply() runs every link inline on success."""
        sig2 = second_task.s("a")
        sig3 = third_task.s()
        registered = [sig2.function_path, sig3.function_path]

        def resolve(path):
            return second_task if path.endswith("second_task") else third_task

        with (
            patch(
                "django_qstash.app.base.discover_tasks",
                return_value=registered,
            ),
            patch("django_qstash.app.base.import_string", side_effect=resolve),
        ):
            first_task.apply(args=(1, 2), link=[sig2, sig3])

        labels = [name for name, _ in RECORD]
        assert labels == ["first", "second", "third"]

    @override_settings(DJANGO_QSTASH_ALWAYS_EAGER=True)
    def test_failed_parent_skips_links(self):
        """A failing parent does not run its links."""

        @stashed_task
        def boom():
            raise ValueError("nope")

        sig = second_task.s("never")
        with (
            patch(
                "django_qstash.app.base.discover_tasks",
                return_value=[sig.function_path],
            ),
            patch(
                "django_qstash.app.base.import_string",
                return_value=second_task,
            ),
        ):
            result = boom.apply_async(link=sig)

        assert result.failed() is True
        assert RECORD == []
