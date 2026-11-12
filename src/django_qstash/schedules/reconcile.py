"""Desired-state reconciliation for application-declared QStash schedules.

Applications describe the recurring jobs they own as :class:`ScheduleSpec`
values and call :func:`reconcile_schedules` from a deploy step (or the
``qstash_reconcile_schedules`` management command). Each run converges the
local ``TaskSchedule`` rows and the QStash schedules toward those specs:

* Identity is deterministic. The QStash schedule id is
  ``"<namespace>.<key>"``, and django-qstash sets that id itself when creating
  the schedule, so repeated runs (and runs that crashed half way) update the
  same schedule instead of creating duplicates.
* The namespace separates environments. Use a different namespace for stage
  and production; a run only ever reads or writes ids in its own namespace.
* Nothing else is touched. Schedules that are not in ``specs`` are never
  updated, adopted, or deleted.

Local and remote writes are separate operations. A database transaction does
not make the QStash call atomic: if the local save succeeds and the QStash
call fails (or the reverse), the entry is reported as failed and the next run
detects the drift and repairs it.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from dataclasses import fields as dataclass_fields
from typing import Any
from typing import Literal

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction

from django_qstash.callbacks import get_callback_url
from django_qstash.client import qstash_client
from django_qstash.schedules.formatters import format_task_schedule_for_qstash
from django_qstash.schedules.formatters import prepare_qstash_payload
from django_qstash.schedules.models import TaskSchedule
from django_qstash.schedules.models import _normalize_task_reference
from django_qstash.schedules.services import remote_sync_suppressed
from django_qstash.settings import qstash_settings

logger = logging.getLogger(__name__)

Action = Literal["created", "changed", "resynced", "unchanged", "failed"]

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$")

# TaskSchedule fields a spec controls, in the order they are compared.
SPEC_FIELDS: tuple[str, ...] = (
    "name",
    "task",
    "cron",
    "args",
    "kwargs",
    "retries",
    "timeout",
    "retry_delay",
    "delay",
    "queue",
    "headers",
    "callback",
    "callback_headers",
    "failure_callback",
    "failure_callback_headers",
    "flow_control",
    "label",
    "redact",
    "is_active",
)


@dataclass(frozen=True)
class ScheduleSpec:
    """One application-owned schedule.

    ``key`` is the stable identity within a namespace (letters, digits, ``_``
    and ``-``). ``task`` is a dotted path or a ``@stashed_task`` function.
    Every other field mirrors the ``TaskSchedule`` field of the same name and
    has the same default, so changing a default here (or in your spec) updates
    existing schedules on the next run.
    """

    key: str
    task: Any
    cron: str
    name: str = ""
    args: list[Any] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)
    retries: int = 3
    timeout: str = "60s"
    retry_delay: str = ""
    delay: str = ""
    queue: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    callback: str = ""
    callback_headers: dict[str, str] = field(default_factory=dict)
    failure_callback: str = ""
    failure_callback_headers: dict[str, str] = field(default_factory=dict)
    flow_control: dict[str, Any] = field(default_factory=dict)
    label: str = ""
    redact: dict[str, Any] = field(default_factory=dict)
    is_active: bool = True

    @classmethod
    def coerce(cls, value: ScheduleSpec | Mapping[str, Any]) -> ScheduleSpec:
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            allowed = {f.name for f in dataclass_fields(cls)}
            unknown = sorted(set(value) - allowed)
            if unknown:
                raise ValueError(f"Unknown schedule spec fields: {unknown}")
            return cls(**dict(value))
        raise TypeError(f"Expected ScheduleSpec or mapping, got {type(value)!r}")

    def local_fields(self) -> dict[str, Any]:
        task = _normalize_task_reference(self.task)
        return {
            "name": self.name or self.key,
            "task": task,
            "cron": self.cron,
            "args": list(self.args),
            "kwargs": dict(self.kwargs),
            "retries": self.retries,
            "timeout": self.timeout,
            "retry_delay": self.retry_delay,
            "delay": self.delay,
            "queue": self.queue,
            "headers": dict(self.headers),
            "callback": self.callback,
            "callback_headers": dict(self.callback_headers),
            "failure_callback": self.failure_callback,
            "failure_callback_headers": dict(self.failure_callback_headers),
            "flow_control": dict(self.flow_control),
            "label": self.label,
            "redact": dict(self.redact),
            "is_active": self.is_active,
        }


@dataclass
class ScheduleOutcome:
    """What reconciliation did (or, in a dry run, would do) for one spec.

    ``action`` is ``created`` (no local row existed), ``changed`` (local
    fields differed), ``resynced`` (local matched but QStash had drifted:
    missing, another destination, different payload/cron/retries, or paused
    state), ``unchanged``, or ``failed``. ``changes`` maps each differing
    local field to ``[old, new]``; ``remote_drift`` lists why QStash needed
    a push. ``error`` is set when ``action == "failed"``; ``local_saved``
    tells you whether the database write landed before the failure.
    """

    key: str
    schedule_id: str
    action: Action
    changes: dict[str, list[Any]] = field(default_factory=dict)
    remote_drift: list[str] = field(default_factory=list)
    error: str = ""
    local_saved: bool = False


@dataclass
class ReconcileResult:
    namespace: str
    destination: str
    dry_run: bool
    outcomes: list[ScheduleOutcome] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed

    @property
    def failed(self) -> list[ScheduleOutcome]:
        return [o for o in self.outcomes if o.action == "failed"]

    def counts(self) -> dict[str, int]:
        totals = dict.fromkeys(
            ("created", "changed", "resynced", "unchanged", "failed"), 0
        )
        for outcome in self.outcomes:
            totals[outcome.action] += 1
        return totals

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "destination": self.destination,
            "dry_run": self.dry_run,
            "ok": self.ok,
            "counts": self.counts(),
            "outcomes": [asdict(o) for o in self.outcomes],
        }


def schedule_id_for(namespace: str, key: str) -> str:
    """Deterministic QStash schedule id for ``key`` in ``namespace``."""
    for label, value in (("namespace", namespace), ("key", key)):
        if not _IDENTIFIER.match(str(value)):
            raise ValueError(
                f"Invalid schedule {label} {value!r}: use 1-100 letters, digits, "
                "'_' or '-', starting with a letter or digit"
            )
    return f"{namespace}.{key}"


def _resolve_namespace(namespace: str | None) -> str:
    value = namespace or qstash_settings.DJANGO_QSTASH_SCHEDULE_NAMESPACE
    if not value:
        raise ImproperlyConfigured(
            "Schedule reconciliation needs a namespace that is unique per "
            "environment (for example 'prod' or 'stage'). Pass namespace= or "
            "set DJANGO_QSTASH_SCHEDULE_NAMESPACE."
        )
    return str(value)


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _local_changes(
    instance: TaskSchedule | None, desired: dict[str, Any]
) -> dict[str, list[Any]]:
    if instance is None:
        return {name: [None, desired[name]] for name in SPEC_FIELDS}
    changes: dict[str, list[Any]] = {}
    for name in SPEC_FIELDS:
        old, new = getattr(instance, name), desired[name]
        if _jsonable(old) != _jsonable(new):
            changes[name] = [old, new]
    return changes


def _remote_drift(remote: Any, instance: TaskSchedule, destination: str) -> list[str]:
    if remote is None:
        return ["missing in QStash"]
    drift: list[str] = []
    if getattr(remote, "destination", None) != destination:
        drift.append(
            f"destination {getattr(remote, 'destination', None)!r} != {destination!r}"
        )
    if getattr(remote, "cron", None) != instance.cron:
        drift.append("cron")
    if getattr(remote, "retries", None) != instance.retries:
        drift.append("retries")
    try:
        body = json.loads(getattr(remote, "body", None) or "")
    except (TypeError, ValueError):
        body = None
    if body != _jsonable(prepare_qstash_payload(instance)):
        drift.append("payload")
    if bool(getattr(remote, "paused", False)) != (not instance.is_active):
        drift.append("paused" if instance.is_active else "active")
    return drift


def _push(instance: TaskSchedule, remote: Any) -> None:
    """Create or overwrite the QStash schedule, then apply pause state."""
    qstash_client.schedule.create(**format_task_schedule_for_qstash(instance))
    schedule_id = str(instance.schedule_id)
    if instance.is_active:
        if remote is not None and getattr(remote, "paused", False):
            qstash_client.schedule.resume(schedule_id)
    else:
        qstash_client.schedule.pause(schedule_id)


def reconcile_schedules(
    specs: Iterable[ScheduleSpec | Mapping[str, Any]],
    *,
    namespace: str | None = None,
    dry_run: bool = False,
    resync: bool = False,
) -> ReconcileResult:
    """Converge local ``TaskSchedule`` rows and QStash schedules to ``specs``.

    ``namespace`` defaults to ``DJANGO_QSTASH_SCHEDULE_NAMESPACE`` and must
    differ between environments that share a QStash account. ``dry_run``
    computes the result without writing anything. ``resync=True`` pushes every
    spec to QStash even when no drift is detected (use it after changing
    headers, callbacks, or flow control directly in QStash, which drift
    detection does not compare).

    The result is returned, never raised: inspect ``result.ok`` /
    ``result.failed``. Configuration errors (missing namespace, invalid or
    duplicate keys, no callback domain) raise before anything is written.
    """
    ns = _resolve_namespace(namespace)
    destination = get_callback_url()

    planned: list[tuple[ScheduleSpec, str]] = []
    seen: set[str] = set()
    for raw in specs:
        spec = ScheduleSpec.coerce(raw)
        schedule_id = schedule_id_for(ns, spec.key)
        if schedule_id in seen:
            raise ValueError(f"Duplicate schedule key {spec.key!r}")
        seen.add(schedule_id)
        planned.append((spec, schedule_id))

    result = ReconcileResult(namespace=ns, destination=destination, dry_run=dry_run)

    try:
        remote_by_id = {
            s.schedule_id: s
            for s in qstash_client.schedule.list()
            if str(getattr(s, "schedule_id", "")).startswith(f"{ns}.")
        }
    except Exception as exc:
        logger.exception("Failed to list QStash schedules for reconciliation")
        for spec, schedule_id in planned:
            result.outcomes.append(
                ScheduleOutcome(
                    key=spec.key,
                    schedule_id=schedule_id,
                    action="failed",
                    error=f"could not list QStash schedules: {exc}",
                )
            )
        return result

    for spec, schedule_id in planned:
        result.outcomes.append(
            _reconcile_one(
                spec,
                schedule_id,
                remote_by_id.get(schedule_id),
                destination=destination,
                dry_run=dry_run,
                resync=resync,
            )
        )
    return result


def _reconcile_one(
    spec: ScheduleSpec,
    schedule_id: str,
    remote: Any,
    *,
    destination: str,
    dry_run: bool,
    resync: bool,
) -> ScheduleOutcome:
    outcome = ScheduleOutcome(key=spec.key, schedule_id=schedule_id, action="unchanged")
    try:
        desired = spec.local_fields()
        if not desired["task"]:
            raise ValueError("spec has no task")
        instance = TaskSchedule.objects.filter(schedule_id=schedule_id).first()
        outcome.changes = _local_changes(instance, desired)

        if instance is None:
            outcome.action = "created"
            instance = TaskSchedule(schedule_id=schedule_id, **desired)
        elif outcome.changes:
            outcome.action = "changed"
            for name, value in desired.items():
                setattr(instance, name, value)

        outcome.remote_drift = _remote_drift(remote, instance, destination)
        if outcome.action == "unchanged" and (outcome.remote_drift or resync):
            outcome.action = "resynced"
            if not outcome.remote_drift:
                outcome.remote_drift = ["forced resync"]
    except Exception as exc:
        logger.exception("Failed to plan schedule %s", schedule_id)
        outcome.action = "failed"
        outcome.error = str(exc)
        return outcome

    if dry_run or outcome.action == "unchanged":
        return outcome

    planned_action = outcome.action
    try:
        if planned_action in ("created", "changed"):
            with remote_sync_suppressed(), transaction.atomic():
                instance.full_clean(validate_unique=False)
                instance.save()
            outcome.local_saved = True
    except Exception as exc:
        logger.exception("Failed to save schedule %s locally", schedule_id)
        outcome.action = "failed"
        outcome.error = f"local save failed ({planned_action}): {exc}"
        return outcome

    try:
        _push(instance, remote)
    except Exception as exc:
        logger.exception("Failed to push schedule %s to QStash", schedule_id)
        outcome.action = "failed"
        saved = "local row saved; " if outcome.local_saved else ""
        outcome.error = (
            f"QStash update failed ({planned_action}): {exc}. {saved}"
            "Rerun reconciliation to repair."
        )
    return outcome
