from __future__ import annotations

from unittest import mock

from django.test import override_settings

from django_qstash.discovery import utils
from django_qstash.discovery.utils import clear_discover_tasks_cache
from django_qstash.discovery.utils import discover_tasks


@override_settings(DEBUG=True)
def test_signal_handler_clears_cache_when_debug_true():
    """With DEBUG=True (and the setting unset), the per-request handler clears."""
    with mock.patch.object(utils._discover_tasks_impl, "cache_clear") as cache_clear:
        clear_discover_tasks_cache(sender=None)
        cache_clear.assert_called_once()


@override_settings(DEBUG=False)
def test_signal_handler_skips_cache_when_debug_false():
    """With DEBUG=False (and the setting unset), the handler is a no-op."""
    with mock.patch.object(utils._discover_tasks_impl, "cache_clear") as cache_clear:
        clear_discover_tasks_cache(sender=None)
        cache_clear.assert_not_called()


@override_settings(DEBUG=False, DJANGO_QSTASH_DISCOVER_CLEAR_CACHE_ON_REQUEST=True)
def test_setting_overrides_debug_to_force_clear():
    """The explicit setting wins over DEBUG: True forces a clear in production."""
    with mock.patch.object(utils._discover_tasks_impl, "cache_clear") as cache_clear:
        clear_discover_tasks_cache(sender=None)
        cache_clear.assert_called_once()


@override_settings(DEBUG=True, DJANGO_QSTASH_DISCOVER_CLEAR_CACHE_ON_REQUEST=False)
def test_setting_overrides_debug_to_skip_clear():
    """The explicit setting wins over DEBUG: False skips even in development."""
    with mock.patch.object(utils._discover_tasks_impl, "cache_clear") as cache_clear:
        clear_discover_tasks_cache(sender=None)
        cache_clear.assert_not_called()


def test_explicit_cache_clear_still_works():
    """The public discover_tasks.cache_clear() remains available for manual use."""
    # Prime the cache.
    discover_tasks()
    assert utils._discover_tasks_impl.cache_info().currsize >= 1

    discover_tasks.cache_clear()
    assert utils._discover_tasks_impl.cache_info().currsize == 0
