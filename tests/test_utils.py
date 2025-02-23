from __future__ import annotations

import pytest

from django_qstash.utils import import_string
from django_qstash.utils import validate_task_payload


def test_import_string():
    """Test importing functions by string path"""
    # Import a real Python function
    func = import_string("json.dumps")
    assert callable(func)

    # Test invalid import
    with pytest.raises(ImportError):
        import_string("nonexistent.module.function")


def test_validate_task_payload():
    """Test task payload validation"""
    # Valid payload
    valid_payload = {
        "function": "task_func",
        "module": "my_app.tasks",
        "args": [1, 2, 3],
        "kwargs": {"key": "value"},
    }
    is_valid, message = validate_task_payload(valid_payload)
    assert is_valid
    assert message == ""

    # Missing required field
    invalid_payload = {
        "function": "task_func",
        "args": [1, 2, 3],
        "kwargs": {"key": "value"},
    }
    is_valid, message = validate_task_payload(invalid_payload)
    assert not is_valid
    assert "module" in message

    # Invalid args type
    invalid_payload = {
        "function": "task_func",
        "module": "my_app.tasks",
        "args": "not a list",
        "kwargs": {"key": "value"},
    }
    is_valid, message = validate_task_payload(invalid_payload)
    assert not is_valid
    assert "Args must be" in message
