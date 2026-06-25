from __future__ import annotations

import logging

from django_qstash import stashed_task as shared_task

logger = logging.getLogger(__name__)

"""
from cfehome.tasks import *
math_add_task.apply_async(args=(12, 454))
math_add_task.apply_async(args=(12, 12), delay=10)
"""


@shared_task(name="Math adder")
def math_add_task(a, b, *args, **kwargs):
    logger.info("Adding %s and %s", a, b)
    return a + b
