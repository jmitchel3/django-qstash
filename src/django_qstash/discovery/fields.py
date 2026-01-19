from __future__ import annotations

from typing import Any
from typing import cast

from django import forms

from django_qstash.discovery.utils import TaskInfo
from django_qstash.discovery.utils import discover_tasks
from django_qstash.discovery.validators import task_exists_validator


class TaskChoiceField(forms.ChoiceField):
    """
    A form field that provides choices from discovered QStash tasks
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Remove max_length if it's present since ChoiceField doesn't use it
        kwargs.pop("max_length", None)

        # Get tasks before calling parent to set choices
        tasks = cast(list[TaskInfo], discover_tasks(locations_only=False))

        # Convert tasks to choices using (task_name, task_name) format
        task_choices: list[tuple[str, str]] = [
            (task["location"], task["field_label"]) for task in tasks
        ]

        kwargs["choices"] = task_choices
        kwargs["validators"] = [task_exists_validator] + kwargs.get("validators", [])
        super().__init__(*args, **kwargs)

    def get_task(self) -> str | None:
        """
        Returns the actual task dot notation path for the selected value
        """
        # self.data is available on forms.Field but not typed in django-stubs
        data = getattr(self, "data", None)
        if data:
            tasks = cast(list[TaskInfo], discover_tasks(locations_only=False))

            for task in tasks:
                if task["field_label"] == data:
                    return task["location"]
        return None
