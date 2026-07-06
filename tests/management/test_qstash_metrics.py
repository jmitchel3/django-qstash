from __future__ import annotations

import json
from unittest.mock import patch

from django.core.management import call_command


@patch("django_qstash.management.commands.qstash_metrics.calculate_task_metrics")
def test_qstash_metrics_text_output(mock_metrics, capsys):
    mock_metrics.return_value = {
        "window_seconds": 60,
        "since": "2026-01-01T00:00:00+00:00",
        "until": "2026-01-01T00:01:00+00:00",
        "total": 2,
        "counts_by_status": {"SUCCESS": 1, "EXECUTION_ERROR": 1},
        "success_rate": 0.5,
        "duration_ms": {"p50": 100, "p95": 400},
    }

    call_command("qstash_metrics", "--window", "60")

    mock_metrics.assert_called_once_with(window_seconds=60)
    captured = capsys.readouterr()
    assert "Window: 60s" in captured.out
    assert "Success rate: 50.00%" in captured.out
    assert "SUCCESS: 1" in captured.out


@patch("django_qstash.management.commands.qstash_metrics.calculate_task_metrics")
def test_qstash_metrics_json_output(mock_metrics, capsys):
    mock_metrics.return_value = {
        "window_seconds": 60,
        "since": "2026-01-01T00:00:00+00:00",
        "until": "2026-01-01T00:01:00+00:00",
        "total": 0,
        "counts_by_status": {},
        "success_rate": 0.0,
        "duration_ms": {"p50": None, "p95": None},
    }

    call_command("qstash_metrics", "--window", "60", "--json")

    captured = capsys.readouterr()
    assert json.loads(captured.out)["total"] == 0
