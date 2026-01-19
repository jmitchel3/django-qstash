from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django import forms
from django.db import models

from django_qstash.discovery.fields import TaskChoiceField

if TYPE_CHECKING:
    _CharFieldBase = models.CharField[str, str]
else:
    _CharFieldBase = models.CharField


class TaskField(_CharFieldBase):
    """
    A model field for storing QStash task references
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Set a reasonable max_length for task names if not provided
        if "max_length" not in kwargs:
            kwargs["max_length"] = 255
        super().__init__(*args, **kwargs)

    def formfield(
        self,
        form_class: type[forms.Field] | None = None,
        choices_form_class: type[forms.ChoiceField] | None = None,
        **kwargs: Any,
    ) -> forms.Field | None:
        # Use our custom form field
        defaults: dict[str, Any] = {
            "form_class": TaskChoiceField,
        }
        defaults.update(kwargs)
        return super().formfield(**defaults)
