from __future__ import annotations

import pytest

from django_qstash.client import init_qstash


def test_init_qstash_no_url(monkeypatch):
    """No QSTASH_URL -> plain client, no base_url override."""
    monkeypatch.setattr("django_qstash.client.QSTASH_URL", None)
    client = init_qstash()
    assert client is not None


def test_init_qstash_custom_url_warns(monkeypatch):
    """A non-Upstash QSTASH_URL warns and sets base_url for dev use."""
    monkeypatch.setattr("django_qstash.client.QSTASH_URL", "http://localhost:8080")
    with pytest.warns(RuntimeWarning, match="development"):
        client = init_qstash()
    assert client is not None


@pytest.mark.parametrize(
    "url",
    [
        "https://foo.upstash.io",
        "https://bar.upstash.cloud",
        "https://baz.upstash.com",
    ],
)
def test_init_qstash_upstash_url_no_warning(monkeypatch, recwarn, url):
    """Known Upstash domains don't trigger the development warning."""
    monkeypatch.setattr("django_qstash.client.QSTASH_URL", url)
    client = init_qstash()
    assert client is not None
    assert not any("development" in str(w.message) for w in recwarn.list)
