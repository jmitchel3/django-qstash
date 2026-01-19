from __future__ import annotations

import logging
import os
import warnings
from functools import lru_cache
from importlib import import_module
from typing import Any
from typing import TypedDict

from django.apps import apps
from django.conf import settings
from django.core.signals import request_started
from django.utils.module_loading import module_has_submodule

logger = logging.getLogger(__name__)

DJANGO_QSTASH_DISCOVER_INCLUDE_SETTINGS_DIR: bool = getattr(
    settings, "DJANGO_QSTASH_DISCOVER_INCLUDE_SETTINGS_DIR", True
)


class TaskInfo(TypedDict):
    """Type definition for task discovery result."""

    name: str | None
    field_label: str
    location: str


@lru_cache(maxsize=None)
def _discover_tasks_impl() -> list[TaskInfo]:
    """
    Internal implementation that returns the full task info list.
    """
    from django_qstash.app import QStashTask

    discovered_tasks: list[TaskInfo] = []
    packages: list[str] = []

    # Add Django apps that contain tasks.py
    for app_config in apps.get_app_configs():
        if module_has_submodule(app_config.module, "tasks"):
            packages.append(app_config.name)

    # Add the directory containing settings.py if it has a tasks.py module
    if DJANGO_QSTASH_DISCOVER_INCLUDE_SETTINGS_DIR:
        settings_module = os.environ.get("DJANGO_SETTINGS_MODULE", "")
        if settings_module:
            settings_package = settings_module.rsplit(".", 1)[0]
            try:
                settings_module_obj = import_module(settings_package)
                if module_has_submodule(settings_module_obj, "tasks"):
                    packages.append(settings_package)
            except ImportError:
                warnings.warn(
                    f"Could not import settings package {settings_package} for task discovery",
                    RuntimeWarning,
                    stacklevel=2,
                )

    # Rest of the discovery logic
    for package in packages:
        try:
            tasks_module = import_module(f"{package}.tasks")
            # Find all attributes that are QstashTask instances
            for attr_name in dir(tasks_module):
                attr = getattr(tasks_module, attr_name)

                if isinstance(attr, QStashTask):
                    value = f"{package}.tasks.{attr_name}"
                    if attr.name == attr_name:
                        label = value
                    else:
                        label = f"{attr.name} ({package}.tasks)"
                    discovered_tasks.append(
                        TaskInfo(
                            name=attr.name,
                            field_label=label,
                            location=f"{package}.tasks.{attr_name}",
                        )
                    )
        except Exception as e:
            warnings.warn(
                f"Failed to import tasks from {package}: {str(e)}",
                RuntimeWarning,
                stacklevel=2,
            )
    return discovered_tasks


def discover_tasks(locations_only: bool = False) -> list[str] | list[TaskInfo]:
    """
    Automatically discover tasks in Django apps and return them as a list.

    Args:
        locations_only: If True, returns a list of location strings.
                       If False, returns a list of TaskInfo dicts.

    Returns:
        If locations_only is True: List of location strings
        If locations_only is False: List of TaskInfo dicts
        Example: [
            ('example_app.tasks.my_task', 'example_app.tasks.my_task'),
            ('other_app.tasks.custom_task', 'special_name')
        ]
    """
    tasks = _discover_tasks_impl()
    if locations_only:
        return [x["location"] for x in tasks]
    return tasks


# Add cache_clear as an attribute for backwards compatibility
discover_tasks.cache_clear = _discover_tasks_impl.cache_clear  # type: ignore[attr-defined]


def clear_discover_tasks_cache(sender: type[Any] | None, **kwargs: Any) -> None:
    logger.info("Clearing Django QStash discovered tasks cache")
    _discover_tasks_impl.cache_clear()


request_started.connect(
    clear_discover_tasks_cache,
    dispatch_uid="clear_django_qstash_discovered_tasks_cache",
)
