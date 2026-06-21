from __future__ import annotations

import types

import pytest

from django_qstash.discovery import utils
from django_qstash.discovery.utils import discover_tasks


def test_discovers_basic_task():
    """Test that basic task discovery works"""
    discover_tasks.cache_clear()
    tasks = discover_tasks()
    expected_tasks = [
        {
            "name": "Custom Name Task",
            "field_label": "Custom Name Task (tests.discovery.tasks)",
            "location": "tests.discovery.tasks.custom_name_task",
        },
        {
            "name": "debug_task",
            "field_label": "tests.discovery.tasks.debug_task",
            "location": "tests.discovery.tasks.debug_task",
        },
        {
            "name": "Cleanup Task Results",
            "field_label": "Cleanup Task Results (django_qstash.results.tasks)",
            "location": "django_qstash.results.tasks.clear_stale_results_task",
        },
        {
            "name": "Clear Task Error Results",
            "field_label": "Clear Task Error Results (django_qstash.results.tasks)",
            "location": "django_qstash.results.tasks.clear_task_errors_task",
        },
        {
            "name": "replace_celery_decorator_task",
            "field_label": "tests.discovery.tasks.replace_celery_decorator_task",
            "location": "tests.discovery.tasks.replace_celery_decorator_task",
        },
    ]
    assert len(tasks) == len(expected_tasks)
    tasks_set = {tuple(sorted(t.items())) for t in tasks}
    expected_tasks_set = {tuple(sorted(t.items())) for t in expected_tasks}
    assert tasks_set == expected_tasks_set


def test_discovers_tasks_in_settings_dir(monkeypatch):
    """Tasks living next to settings.py are discovered."""
    from django_qstash.app import QStashTask

    @QStashTask
    def settings_task():
        return "ok"

    fake_module = types.ModuleType("tests.tasks")
    fake_module.settings_task = settings_task

    orig_import = utils.import_module
    orig_has = utils.module_has_submodule

    def fake_import(name):
        if name == "tests.tasks":
            return fake_module
        return orig_import(name)

    def fake_has(module, submodule):
        if submodule == "tasks" and getattr(module, "__name__", "") == "tests":
            return True
        return orig_has(module, submodule)

    monkeypatch.setattr(utils, "import_module", fake_import)
    monkeypatch.setattr(utils, "module_has_submodule", fake_has)
    monkeypatch.setattr(utils, "DJANGO_QSTASH_DISCOVER_INCLUDE_SETTINGS_DIR", True)

    utils._discover_tasks_impl.cache_clear()
    try:
        locations = discover_tasks(locations_only=True)
        assert "tests.tasks.settings_task" in locations
    finally:
        utils._discover_tasks_impl.cache_clear()


def test_settings_dir_discovery_disabled(monkeypatch):
    """When the settings-dir opt-in is off, the settings package is skipped."""
    monkeypatch.setattr(utils, "DJANGO_QSTASH_DISCOVER_INCLUDE_SETTINGS_DIR", False)

    calls = []
    orig_import = utils.import_module

    def tracking_import(name):
        calls.append(name)
        return orig_import(name)

    monkeypatch.setattr(utils, "import_module", tracking_import)
    utils._discover_tasks_impl.cache_clear()
    try:
        discover_tasks()
        assert "tests" not in calls
    finally:
        utils._discover_tasks_impl.cache_clear()


def test_settings_dir_discovery_no_settings_module(monkeypatch):
    """With no DJANGO_SETTINGS_MODULE set, settings-dir discovery is skipped."""
    monkeypatch.setattr(utils, "DJANGO_QSTASH_DISCOVER_INCLUDE_SETTINGS_DIR", True)
    monkeypatch.setattr(utils.os.environ, "get", lambda *a, **k: "")

    utils._discover_tasks_impl.cache_clear()
    try:
        discover_tasks()  # should not raise
    finally:
        utils._discover_tasks_impl.cache_clear()


def test_settings_package_import_failure_warns(monkeypatch):
    """A settings package that can't be imported warns but doesn't crash."""
    orig_import = utils.import_module

    def fake_import(name):
        if name == "tests":
            raise ImportError("no settings package")
        return orig_import(name)

    monkeypatch.setattr(utils, "import_module", fake_import)
    monkeypatch.setattr(utils, "DJANGO_QSTASH_DISCOVER_INCLUDE_SETTINGS_DIR", True)
    utils._discover_tasks_impl.cache_clear()
    try:
        with pytest.warns(RuntimeWarning, match="Could not import settings package"):
            discover_tasks()
    finally:
        utils._discover_tasks_impl.cache_clear()


def test_discover_warns_on_import_failure(monkeypatch):
    """A package whose tasks module fails to import yields a warning, not a crash."""
    orig_import = utils.import_module

    def fake_import(name):
        if name.endswith(".tasks"):
            raise ImportError("boom")
        return orig_import(name)

    monkeypatch.setattr(utils, "import_module", fake_import)

    utils._discover_tasks_impl.cache_clear()
    try:
        with pytest.warns(RuntimeWarning, match="Failed to import tasks"):
            discover_tasks()
    finally:
        utils._discover_tasks_impl.cache_clear()
