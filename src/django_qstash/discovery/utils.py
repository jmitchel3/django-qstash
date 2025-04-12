from __future__ import annotations

import logging
import os
import warnings
from functools import cache
from importlib import import_module

from django.apps import apps
from django.conf import settings
from django.core.signals import request_started
from django.utils.module_loading import module_has_submodule

logger = logging.getLogger(__name__)

DJANGO_QSTASH_DISCOVER_INCLUDE_SETTINGS_DIR = getattr(
    settings, "DJANGO_QSTASH_DISCOVER_INCLUDE_SETTINGS_DIR", True
)


@cache
def discover_tasks(locations_only: bool = False) -> list[str] | list[dict]:
    """
    Automatically discover tasks in Django apps and return them as a list of tuples.
    Each tuple contains (dot_notation_path, task_name).
    If no custom task name is specified, both values will be the dot notation path.

    Returns:
        List of tuples: [(dot_notation_path, task_name), ...]
        Example: [
            ('example_app.tasks.my_task', 'example_app.tasks.my_task'),
            ('other_app.tasks.custom_task', 'special_name')
        ]
    """
    from django_qstash.app import QStashTask

    discovered_tasks = []
    # Django apps that contain tasks.py
    packages = [
        app_config.name
        for app_config in apps.get_app_configs()
        if module_has_submodule(app_config.module, "tasks")
    ]

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
                        {
                            "name": attr.name,
                            "field_label": label,
                            "location": f"{package}.tasks.{attr_name}",
                        }
                    )
        except Exception as e:
            warnings.warn(
                f"Failed to import tasks from {package}: {str(e)}",
                RuntimeWarning,
                stacklevel=2,
            )
    if locations_only:
        return [x["location"] for x in discovered_tasks]
    return discovered_tasks


def clear_discover_tasks_cache(sender, **kwargs):
    logger.info("Clearing Django QStash discovered tasks cache")
    discover_tasks.cache_clear()


request_started.connect(
    clear_discover_tasks_cache,
    dispatch_uid="clear_django_qstash_discovered_tasks_cache",
)
