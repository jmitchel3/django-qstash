from __future__ import annotations

__version__ = "0.2.4"

from django_qstash.app import shared_task
from django_qstash.app import stashed_task

__all__ = ["stashed_task", "shared_task"]
