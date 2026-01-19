from __future__ import annotations

import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


def import_string(import_path: str) -> Any:
    """
    Import a module path and return the attribute/class designated by the last name.

    Example:
        import_string('myapp.tasks.mytask') -> mytask function
    """
    try:
        module_path, class_name = import_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        raise ImportError(f"Could not import '{import_path}': {e}") from e


def validate_task_payload(payload: dict[str, Any]) -> tuple[bool, str]:
    """Validate the task payload has all required fields"""
    required_fields = {"function", "module", "args", "kwargs"}
    missing_fields = required_fields - set(payload.keys())

    if missing_fields:
        return False, f"Missing required fields: {', '.join(missing_fields)}"

    if not isinstance(payload["args"], (list, tuple)):
        return False, "Args must be a list or tuple"

    if not isinstance(payload["kwargs"], dict):
        return False, "Kwargs must be a dictionary"

    return True, ""
