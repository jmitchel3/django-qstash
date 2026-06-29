# Proposed New Features

This document captures proposed improvements for django-qstash, prioritized by impact on adoption and Celery parity. The guiding constraint for every item: stay pure Django and stay a viable Celery alternative (no broker, no always-on worker).

## Context

django-qstash is already a mature project: signed webhooks with key rotation, an allowlist so only `@stashed_task` functions execute, payload-size limits, structured logging with correlation IDs, Django signals, a results backend, QStash Schedules with full delivery controls, a DLQ command, 90% enforced coverage, strict mypy, and a 3.10 to 3.14 / Django 4.2 to 6.0 matrix.

The items below close the remaining gap with Celery and with what adopting projects hit in production. They are not bug fixes; the existing functionality is solid.

## Shipped

The entire **high-priority tier** below has been implemented (eager/test mode,
a working `AsyncResult` backed by the results backend, the webhook idempotency
guard, `async def` task support) along with the **lazy settings** companion. See
`docs/api-reference.md` (Testing Tasks, `.apply()`, `AsyncResult`/`EagerResult`)
and `docs/configuration.md` (`DJANGO_QSTASH_ALWAYS_EAGER`,
`DJANGO_QSTASH_RESULT_POLL_INTERVAL`, `DJANGO_QSTASH_DEDUP_SUCCESSFUL`).

## High priority

### 1. Eager / test mode for adopters (`apply()` + `ALWAYS_EAGER`) — DONE

**Problem:** Any project that uses this library cannot unit-test its own tasks without a live QStash token and domain. `QStashTask.__call__` raises `ImproperlyConfigured` when `QSTASH_TOKEN`/`DJANGO_QSTASH_DOMAIN` are unset, and `.delay()` makes a network call.

**Shipped:**
- `task.apply(args, kwargs)` executes synchronously and returns an `EagerResult` carrying the value (or exception). No QStash config or network required.
- `DJANGO_QSTASH_ALWAYS_EAGER` makes `.delay()`/`.apply_async()` run inline (mirrors Celery's `CELERY_TASK_ALWAYS_EAGER`).

**Files:** `src/django_qstash/app/base.py`

### 2. `AsyncResult.get()` / `.status` reads from the results backend — DONE

**Problem:** `AsyncResult.get()` raised `NotImplementedError`, which broke the most common Celery idiom: `result = task.delay(...); result.get()`.

**Shipped:** `AsyncResult` looks up `TaskResult` by `task_id` (the QStash `message_id`) and exposes `.status`/`.state`, `.result`, `.traceback`, `ready()`/`successful()`/`failed()`, and a polling `.get(timeout=...)`. The results app is now a real (eventually-consistent) result backend. `EagerResult` resolves in memory with no round-trip.

**Files:** `src/django_qstash/app/base.py`, `src/django_qstash/results/`

### 3. Idempotency / exactly-once guard at the webhook — DONE

**Problem:** QStash is at-least-once, so a task with side effects could re-run on redelivery with no guard.

**Shipped:** The webhook short-circuits (returns `200` with `{"status": "duplicate"}`) when the incoming message already has a `SUCCESS` `TaskResult` row, gated by `DJANGO_QSTASH_DEDUP_SUCCESSFUL` (default on). Prior *failures* still re-execute, so legitimate retries are unaffected. At-least-once semantics are documented in `configuration.md`.

**Files:** `src/django_qstash/handlers.py`, `src/django_qstash/results/`

### 4. `async def` tasks — DONE

**Problem:** `execute_task` did `result = task_func(...)`. An `async def` task returned an un-awaited coroutine, logged success, and stored a coroutine as the result.

**Shipped:** `QStashTask.actual_func` runs coroutine task functions to completion via `asgiref.sync.async_to_sync`, so the webhook handler and eager execution always receive a concrete value. Sync tasks are unaffected.

**Files:** `src/django_qstash/handlers.py`, `src/django_qstash/app/base.py`

## Medium priority

### 5. Lazy settings access (testability + override_settings) — DONE

**Problem:** Many settings were captured as module-level constants at import. Consequences: `@override_settings(...)` did not take effect, and the import-time `warnings.warn` fired in any project that imported the package before settings were configured.

**Shipped:** A lazy `qstash_settings` accessor (plus PEP 562 module `__getattr__` for back-compat) reads from Django settings at access time, so `@override_settings` works everywhere and the import-time warning footgun is gone. `client.py`, `callbacks.py`, `handlers.py`, and `app/base.py` all read lazily.

**Files:** `src/django_qstash/settings.py`, `src/django_qstash/client.py`, `src/django_qstash/app/base.py`

### 6. `bind=True` / task `self` context

**Problem:** Celery's `@shared_task(bind=True)` gives the body `self.request.id`, `self.request.retries`, etc. Migrated Celery code that uses `self.request` breaks.

**Proposal:** Thread a lightweight context object (carrying correlation id, message id, retry count) into the task call when `bind=True`. You already have the correlation id and message id at webhook time. This also unlocks #7.

**Files:** `src/django_qstash/app/base.py`, `src/django_qstash/app/decorators.py`, `src/django_qstash/handlers.py`

### 7. Minimal task chaining (Celery canvas, scoped down)

**Problem:** No way to chain tasks. Full `chain`/`group`/`chord` is out of scope, but the most common case (run B after A succeeds) is common in migrated code.

**Proposal:** QStash callbacks already give the primitive: task A's QStash callback can be task B's webhook. A small `link=` / `.then()` that wires one task's success callback to the next covers the common sequential `chain` case without any broker. Worth at least a documented recipe even if not a full API.

**Files:** `src/django_qstash/app/base.py`, `docs/`

### 8. Celery compatibility matrix doc

**Problem:** The README sells "drop-in replacement," but adopters need to know exactly what is supported.

**Proposal:** Add `docs/celery-compatibility.md` with a crisp table: supported (`delay`, `apply_async`, `countdown`, `eta`, queues, retries, dedup) vs. not-yet (`bind`, `self.retry`, canvas, `.get()`, `chord`). Sets expectations and doubles as a migration aid and marketing asset.

**Files:** `docs/celery-compatibility.md`

## Low priority / polish

- ~~**Rate limiting** on the webhook is still listed as open in `prod-readiness.md`. Signature verification lowers the risk; a documented note ("put it behind your platform's rate limiter") closes the item.~~ DONE. Addressed via documentation: signature verification is the authenticity control, and a concise note in `configuration.md` (plus the existing `security.md` Rate Limiting section) directs adopters to throttle at their proxy/edge/middleware layer.
- ~~**HTTP response body** returns the literal string `"null"` for `None` results~~ — DONE. The success body now serializes `None` as a real JSON `null`.
- ~~**`PayloadError` is logged as "Authentication error"**~~ — DONE. `PayloadError` and `SignatureError` now log distinctly (still both `400`).
- ~~**`discover_tasks` cache is cleared on every `request_started`** (`discovery/utils.py`). For high-traffic apps that is a `dir()`-walk of every tasks module per request. Consider clearing only on autoreload / explicit signal, or caching more durably in production.~~ DONE. The per-request clear is now gated by `DJANGO_QSTASH_DISCOVER_CLEAR_CACHE_ON_REQUEST` (defaults to `settings.DEBUG`), so development still picks up new tasks while production keeps the cache; explicit `discover_tasks.cache_clear()` remains for manual use.
- ~~**`prod-readiness.md` is stamped v0.2.3** while the project is on 0.4.1. Several of its "remaining issues" (content-type validation, HTTPS parsing, mypy in CI) are now done. Refresh or archive it to avoid signaling stale gaps.~~ DONE. `prod-readiness.md` is refreshed to v0.5.0 (2026-06-29) with each remaining issue re-verified against current code.

## Suggested first PR — SHIPPED

The recommended first PR (**#1 + #2 + #5**, eager mode + a working `AsyncResult`
+ lazy settings) has shipped, together with **#3** (idempotency) and **#4**
(`async def` support), completing the high-priority tier. The remaining open
work is the medium-priority items (#6 `bind=True`, #7 task chaining, #8
compatibility matrix) and the remaining low-priority polish.

## Next up

The strongest follow-on is **#8 (Celery compatibility matrix doc)** since the
supported/not-yet surface area is now concrete, followed by **#6 (`bind=True`)**
which unlocks **#7 (minimal chaining)**.
