from __future__ import annotations

from unittest.mock import patch

import pytest

from django_qstash.db.models import TaskStatus
from django_qstash.results.services import function_result_to_dict
from django_qstash.results.services import store_task_result


class TestFunctionResultToDict:
    def test_none_returns_none(self):
        assert function_result_to_dict(None) is None

    def test_dict_passthrough(self):
        assert function_result_to_dict({"a": 1}) == {"a": 1}

    def test_json_string_dict(self):
        assert function_result_to_dict('{"a": 1}') == {"a": 1}

    def test_json_string_non_dict_wrapped(self):
        assert function_result_to_dict("[1, 2]") == {"result": [1, 2]}

    def test_non_json_string_wrapped(self):
        assert function_result_to_dict("hello") == {"result": "hello"}

    def test_other_type_wrapped(self):
        assert function_result_to_dict(42) == {"result": 42}


@pytest.mark.django_db
class TestStoreTaskResult:
    def test_stores_valid_result(self):
        from django_qstash.results.models import TaskResult

        obj = store_task_result(
            task_id="t1",
            task_name="name",
            status=TaskStatus.SUCCESS,
            result={"x": 1},
        )
        assert obj is not None
        assert obj.result == {"x": 1}
        assert TaskResult.objects.filter(pk=obj.pk).exists()

    def test_invalid_status_becomes_unknown(self):
        obj = store_task_result(
            task_id="t2",
            task_name="name",
            status="NOT-A-REAL-STATUS",
        )
        assert obj is not None
        assert obj.status == TaskStatus.UNKNOWN


def test_store_task_result_model_not_installed():
    """When the results model isn't installed, store quietly returns None."""
    with patch(
        "django_qstash.results.services.apps.get_model", side_effect=LookupError
    ):
        result = store_task_result(
            task_id="t",
            task_name="name",
            status=TaskStatus.SUCCESS,
        )
    assert result is None
