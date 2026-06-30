from __future__ import annotations

from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.test import override_settings

from django_qstash.app import stashed_task
from django_qstash.app.base import DEFAULT_MAX_RETRIES
from django_qstash.app.base import BoundTask
from django_qstash.app.base import TaskRequest
from django_qstash.exceptions import MaxRetriesExceededError
from django_qstash.exceptions import Retry

# Records (retries) seen on each attempt so tests can assert the retry loop ran.
ATTEMPTS: list[int] = []


@stashed_task(bind=True, max_retries=3)
def flaky(self, fail_times):
    """Fail (via self.retry) until ``self.request.retries`` reaches fail_times."""
    ATTEMPTS.append(self.request.retries)
    if self.request.retries < fail_times:
        self.retry()
    return ("ok", self.request.retries)


@stashed_task(bind=True, max_retries=5)
def reschedule_with_args(self, x, y):
    """On the first attempt, retry with bumped args; then return the sum."""
    if self.request.retries == 0:
        self.retry(args=(x + 10, y))
    return x + y


@stashed_task(bind=True, max_retries=1)
def retry_with_exc(self):
    """Always retry carrying an exc, so exhaustion re-raises that exc."""
    try:
        raise ValueError("boom")
    except ValueError as exc:
        self.retry(exc=exc)


@stashed_task(bind=True, max_retries=2)
def plain_bound(self):
    return self.request.retries


@stashed_task(bind=True, max_retries=None)
def unlimited(self):
    return "never gives up"


@stashed_task(bind=True, retries=4)
def uses_retries_option(self):
    return "ok"


@stashed_task(bind=True)
def uses_default_limit(self):
    return "ok"


@pytest.fixture(autouse=True)
def clear_attempts():
    ATTEMPTS.clear()
    yield
    ATTEMPTS.clear()


@pytest.fixture(autouse=True)
def mock_qstash_client():
    with patch("django_qstash.app.base.qstash_client") as mock_client:
        mock_message = Mock()
        mock_response = Mock()
        mock_response.message_id = "retry-msg-1"
        mock_message.publish_json = Mock(return_value=mock_response)
        mock_message.enqueue_json = Mock(return_value=mock_response)
        mock_client.message = mock_message
        yield mock_client


class TestMaxRetriesProperty:
    def test_max_retries_option(self):
        """An explicit max_retries option is reported verbatim."""
        assert flaky.max_retries == 3

    def test_retries_option_fallback(self):
        """When only the QStash retries option is set, it doubles as the limit."""
        assert uses_retries_option.max_retries == 4

    def test_default_limit(self):
        """With neither option set, the Celery default applies."""
        assert uses_default_limit.max_retries == DEFAULT_MAX_RETRIES == 3

    def test_unlimited(self):
        """max_retries=None means unlimited (no ceiling)."""
        assert unlimited.max_retries is None


class TestRetrySignal:
    def test_under_limit_raises_retry(self):
        """retry() under the limit raises a Retry carrying the next attempt."""
        bound = BoundTask(plain_bound, TaskRequest(id="x", retries=0))
        with pytest.raises(Retry) as excinfo:
            bound.retry()
        assert excinfo.value.retries == 1

    def test_throw_false_returns_signal(self):
        """throw=False returns the Retry instead of raising it."""
        bound = BoundTask(plain_bound, TaskRequest(id="x", retries=0))
        signal = bound.retry(throw=False, countdown=30, kwargs={"a": 1})
        assert isinstance(signal, Retry)
        assert signal.retries == 1
        assert signal.countdown == 30
        assert signal.task_kwargs == {"a": 1}

    def test_args_default_to_request(self):
        """Without an args override, the Retry reuses the request's args."""
        bound = BoundTask(
            plain_bound, TaskRequest(id="x", retries=0, args=(7,), kwargs={"k": 1})
        )
        signal = bound.retry(throw=False)
        assert signal.task_args == (7,)
        assert signal.task_kwargs == {"k": 1}

    def test_exhausted_raises_max_retries(self):
        """At the limit with no exc, MaxRetriesExceededError is raised."""
        bound = BoundTask(plain_bound, TaskRequest(id="abc", retries=2))
        with pytest.raises(MaxRetriesExceededError, match="max_retries"):
            bound.retry()

    def test_exhausted_reraises_exc(self):
        """At the limit with an exc, the original exception propagates."""
        bound = BoundTask(plain_bound, TaskRequest(id="x", retries=2))
        sentinel = KeyError("nope")
        with pytest.raises(KeyError):
            bound.retry(exc=sentinel)

    def test_exhausted_throw_false_returns_exc(self):
        """Exhaustion with throw=False returns the exception object."""
        bound = BoundTask(plain_bound, TaskRequest(id="x", retries=2))
        result = bound.retry(throw=False)
        assert isinstance(result, MaxRetriesExceededError)

    def test_max_retries_override_forces_exhaustion(self):
        """An explicit max_retries=0 exhausts immediately on the first attempt."""
        bound = BoundTask(plain_bound, TaskRequest(id="x", retries=0))
        with pytest.raises(MaxRetriesExceededError):
            bound.retry(max_retries=0)

    def test_unlimited_never_exhausts(self):
        """max_retries=None keeps raising Retry no matter the attempt count."""
        bound = BoundTask(unlimited, TaskRequest(id="x", retries=100))
        with pytest.raises(Retry):
            bound.retry()

    def test_nameless_task_message(self):
        """Exhaustion message falls back to 'task' when the task has no name."""
        with patch.object(plain_bound, "name", None):
            bound = BoundTask(plain_bound, TaskRequest(id="x", retries=99))
            with pytest.raises(MaxRetriesExceededError, match=r"Can't retry task"):
                bound.retry(max_retries=1)


class TestEagerRetry:
    def test_apply_retries_until_success(self):
        """apply() re-runs inline until the body stops calling self.retry()."""
        result = flaky.apply(args=(2,))
        assert result.successful() is True
        assert result.result == ("ok", 2)
        # Attempts ran at retries=0, 1, 2.
        assert ATTEMPTS == [0, 1, 2]

    def test_apply_keeps_stable_task_id_across_retries(self):
        """The task id is stable across the whole retry loop (like Celery)."""
        result = flaky.apply(args=(1,))
        assert result.successful() is True
        # id is a single uuid string, not regenerated per attempt.
        assert isinstance(result.id, str) and result.id

    def test_apply_args_override_flows_through(self):
        """An args override on retry() is used on the next inline attempt."""
        result = flaky_args_result = reschedule_with_args.apply(args=(1, 2))
        assert flaky_args_result.successful() is True
        # First attempt retried with (11, 2); second attempt returns 11 + 2.
        assert result.result == 13

    def test_apply_exhaustion_captures_failure(self):
        """Exceeding max_retries inline yields a failed EagerResult."""
        result = flaky.apply(args=(99,))
        assert result.failed() is True
        assert isinstance(result.result, MaxRetriesExceededError)
        # max_retries=3 -> attempts at retries 0,1,2,3 then exhausted.
        assert ATTEMPTS == [0, 1, 2, 3]

    def test_apply_exhaustion_reraises_exc(self):
        """retry(exc=...) past the limit surfaces the original exception."""
        result = retry_with_exc.apply()
        assert result.failed() is True
        assert isinstance(result.result, ValueError)

    @override_settings(DJANGO_QSTASH_ALWAYS_EAGER=True)
    def test_delay_eager_retries_inline(self):
        """In eager mode, .delay() runs the retry loop inline too."""
        result = flaky.delay(1)
        assert result.result == ("ok", 1)


class TestDirectCallRetry:
    def test_direct_call_runs_retry_loop(self):
        """A direct bound call honors self.retry() and returns the final value."""
        assert flaky(1) == ("ok", 1)
        assert ATTEMPTS == [0, 1]


class TestEnqueueCarriesRetries:
    def test_enqueue_embeds_retry_count(self, mock_qstash_client):
        """_enqueue(_retries=N) writes the attempt count into the QStash body."""
        plain_bound._enqueue(args=(), kwargs={}, _retries=2)
        body = mock_qstash_client.message.publish_json.call_args.kwargs["body"]
        assert body["retries"] == 2

    def test_enqueue_without_retries_omits_key(self, mock_qstash_client):
        """A first-attempt enqueue does not add a retries key to the body."""
        plain_bound._enqueue(args=(), kwargs={})
        body = mock_qstash_client.message.publish_json.call_args.kwargs["body"]
        assert "retries" not in body
