# Celery Compatibility Matrix

django-qstash aims to be a near drop-in replacement for Celery's `shared_task`:
you keep the familiar `@shared_task` / `@stashed_task` decorators and the
`.delay()` / `.apply_async()` call style, but there is no broker (Redis or
RabbitMQ) and no always-on worker. Tasks run when QStash delivers a signed
webhook to your Django app, which makes the runtime serverless and scale-to-zero
friendly. This page is the crisp reference for what carries over from Celery,
what behaves differently, and what is not implemented yet.

## Supported

These features map directly onto a Celery equivalent. The behavioral notes call
out the cases where the QStash delivery model changes the semantics.

| Feature | Celery equivalent | django-qstash | Notes / differences |
|---------|-------------------|---------------|---------------------|
| Task decorator | `@shared_task` | `@shared_task`, `@stashed_task` | `@shared_task` is an alias for `@stashed_task`. Both wrap a function as a `QStashTask`. See [API reference](api-reference.md#decorators). |
| Enqueue (simple) | `task.delay(*args, **kwargs)` | `task.delay(*args, **kwargs)` | Publishes a QStash message and returns an `AsyncResult`. No `countdown`/`eta` here (Celery is the same); use `apply_async` for delayed delivery. |
| Enqueue (full options) | `task.apply_async(args, kwargs, ...)` | `task.apply_async(args, kwargs, countdown=..., eta=..., **options)` | Accepts `args`, `kwargs`, `countdown`, `eta`, plus QStash message options (see below). |
| `countdown` | `apply_async(countdown=N)` | `apply_async(countdown=N)` | Delay in seconds before delivery, mapped to QStash `delay`. |
| `eta` | `apply_async(eta=dt)` | `apply_async(eta=dt)` | Accepts a `datetime` (naive values are treated as UTC) or a unix timestamp, mapped to QStash `not_before`. |
| Inline / eager run | `task.apply(args, kwargs)` | `task.apply(args, kwargs)` | Runs the task body synchronously in-process and returns an `EagerResult`. Requires no `QSTASH_TOKEN`, `DJANGO_QSTASH_DOMAIN`, or network. Primary tool for unit tests. See [API reference](api-reference.md#apply). |
| Always-eager mode | `CELERY_TASK_ALWAYS_EAGER` | `DJANGO_QSTASH_ALWAYS_EAGER` | When `True`, `.delay()` / `.apply_async()` run inline and return an `EagerResult`, so test code does not change. See [configuration](configuration.md#django_qstash_always_eager). |
| Result handle | `AsyncResult` | `AsyncResult` | Returned by `.delay()` / `.apply_async()`. Backed by the results backend; exposes `.id`, `.status`/`.state`, `.result`, `.traceback`, `ready()`, `successful()`, `failed()`, and a polling `.get()`. |
| `result.get()` | `AsyncResult.get(timeout=...)` | `AsyncResult.get(timeout=..., interval=..., propagate=...)` | Polls the `TaskResult` table until a terminal row exists. Eventually consistent: the row appears only after the webhook runs, so an immediate `.get()` in the same request that called `.delay()` will block (or time out), it will not return right away. |
| `result.status` / `.state` | `AsyncResult.status` / `.state` | `AsyncResult.status` / `.state` | Reads the latest `TaskStatus`; `PENDING` until the webhook has executed the task. `.state` is an alias for `.status`. |
| `result.ready()` | `AsyncResult.ready()` | `AsyncResult.ready()` | `True` once a terminal result row exists. |
| `result.successful()` | `AsyncResult.successful()` | `AsyncResult.successful()` | `True` when the stored status is `SUCCESS`. |
| `result.failed()` | `AsyncResult.failed()` | `AsyncResult.failed()` | `True` for any terminal error status. |
| `result.result` | `AsyncResult.result` | `AsyncResult.result` | The stored return value once available, else `None`. |
| `result.traceback` | `AsyncResult.traceback` | `AsyncResult.traceback` | Stored traceback string when the task failed, else `None`. |
| Eager result object | `EagerResult` | `EagerResult` | Returned by `.apply()` and by eager `.delay()` / `.apply_async()`. Holds the value (or exception) in memory, so `status`, `result`, and `get()` resolve immediately with no database round-trip and the exact value type is preserved. See [API reference](api-reference.md#eagerresult). |
| Queues (FIFO) | `apply_async(queue="...")` | `apply_async(queue="...")` | Routes through a QStash queue for ordered (FIFO) delivery instead of a direct publish. |
| Retries | `max_retries` / `retries` | `max_retries` / `retries` | Set on the decorator (`@shared_task(max_retries=5)`) or per call. QStash performs the retries based on the webhook HTTP response; `max_retries` maps to the QStash `retries` option. |
| Deduplication | (no direct equivalent) | `deduplicated=True` / `content_based_deduplication` | Enables QStash content-based deduplication so the same payload is not enqueued twice. Set on the decorator or per call. |
| Success callback | `link=` (callback) | `callback` / `callback_headers` | Maps to QStash's per-message callback URL and headers. |
| Failure callback | `link_error=` | `failure_callback` / `failure_callback_headers` | QStash calls this URL after retries are exhausted. |
| Flow control | rate limit settings | `flow_control` | Passes QStash flow-control settings (key, rate, period) for the message. |
| Custom headers | `headers=` | `headers` | Forwarded to the task webhook request. |
| Scheduled / periodic tasks | Celery beat (`CELERYBEAT_SCHEDULE`) | QStash Schedules + `TaskSchedule` | The `django_qstash.schedules` app stores cron schedules in the `TaskSchedule` model and registers them with QStash Schedules, no separate beat process. See [API reference](api-reference.md#taskschedule-model). |
| Result backend | `result_backend` | `django_qstash.results` app | Optional `TaskResult` model persists status, return value, traceback, args, and kwargs. Required for `AsyncResult` lookups to resolve. See [API reference](api-reference.md#taskresult-model). |
| `bind=True` / `self.request` | `@shared_task(bind=True)` | `@shared_task(bind=True)` | Passes a bound `self` whose `self.request` exposes `id`, `retries`, `correlation_id`, `task_name`, `args`, and `kwargs`. See [API reference](api-reference.md) for details. |
| Sequential chaining | `chain` / `link=` | `apply_async(..., link=other_task.s(...))` | Enqueues `other_task` after the task succeeds (sequential chain only; no `group` / `chord`). See [API reference](api-reference.md) for details. |

### Message options

`apply_async` (and the decorator) accept QStash message options alongside the
Celery-style arguments. The recognized names are: `callback`,
`callback_headers`, `content_based_deduplication`, `deduplicated`,
`deduplication_id`, `delay`, `failure_callback`, `failure_callback_headers`,
`flow_control`, `headers`, `label`, `max_retries`, `method`, `not_before`,
`queue`, `redact`, `retries`, `retry_delay`, and `timeout`. Options set on the
decorator are merged with (and overridden by) options passed per call.

## Supported, with differences

These work, but the QStash delivery model changes the semantics in ways a
Celery user should know about.

- **At-least-once delivery.** QStash guarantees at-least-once delivery, so a
  task can run more than once on redelivery (for example, if your app responds
  slowly and QStash retries). Celery's delivery guarantee is configurable by
  broker; here it is fixed at at-least-once.
- **Idempotency / dedup guard.** To soften at-least-once for tasks with side
  effects, the webhook short-circuits when the incoming message already has a
  `SUCCESS` result, gated by `DJANGO_QSTASH_DEDUP_SUCCESSFUL` (default on). Prior
  failures still re-execute, so legitimate retries are unaffected. See
  [configuration](configuration.md#django_qstash_dedup_successful).
- **Results require the results app.** `AsyncResult.get()`, `.status`,
  `.result`, and `.traceback` only resolve when `django_qstash.results` is
  installed. Without it every lookup stays `PENDING` and `.get()` times out.
  `EagerResult` (from `.apply()` or eager mode) is the exception: it carries the
  value in memory and needs no backend.
- **Eventual consistency.** Results arrive via webhook, so they are eventually
  consistent. Calling `.get()` in the same request that called `.delay()` will
  not return immediately; it blocks until the webhook has stored a terminal
  result (or the timeout elapses).
- **JSON-serializable arguments only.** Task `args` and `kwargs` are sent as a
  JSON payload, so they must be JSON-serializable. Pass model primary keys
  instead of model instances, lists of ids instead of querysets, and ISO strings
  or timestamps instead of `datetime` objects. See the serialization notes in
  the [API reference](api-reference.md#arguments-serialization).
- **Queues vs. delayed delivery.** A `queue=` routes through QStash FIFO
  delivery, which is about ordering rather than per-message scheduling. Reach for
  `countdown` / `eta` on a direct (non-queued) publish when you need delayed
  delivery.

## Not yet supported

These Celery features have no equivalent yet. Most are intentionally out of
scope for a broker-free, worker-free design.

| Feature | Celery | Status in django-qstash |
|---------|--------|-------------------------|
| Full canvas | `group`, `chord`, multi-step `chain` | Not supported. Only the sequential "run B after A succeeds" case is available via `link=`. Parallel groups and chords have no QStash primitive here. |
| In-task retry | `self.retry()` | Not supported. Retries are driven by QStash based on the webhook HTTP response, not by re-raising from inside the task. |
| Per-task rate limits | `rate_limit` | Not supported as a Celery-style decorator option. QStash `flow_control` covers rate/period at the message level instead. |
| Soft/hard time limits | `soft_time_limit`, `time_limit` | Not supported. The closest control is the QStash `timeout` message option, which bounds the webhook request, not in-process soft/hard limits with `SoftTimeLimitExceeded`. |
| Custom result backends | `result_backend` (Redis, DB, RPC, ...) | Not supported. Results are stored only via the `django_qstash.results` app (the `TaskResult` model in your Django database). |
| Task events / monitoring | Flower, task events | Not supported. There is no event stream or Flower integration. Inspect the `TaskResult` table, the Django admin, structured logs, and the QStash DLQ command instead. |

## See also

- [API Reference](api-reference.md) - decorators, task methods, `AsyncResult` / `EagerResult`, and models
- [Configuration](configuration.md) - all settings, including `DJANGO_QSTASH_ALWAYS_EAGER` and `DJANGO_QSTASH_DEDUP_SUCCESSFUL`
- [Getting Started](getting-started.md) - installation and setup
