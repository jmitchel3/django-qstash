# Feature Roadmap

This page is a historical roadmap for django-qstash. It used to track proposed
Celery-parity work; the adopter-facing status now lives in
[`celery-compatibility.md`](celery-compatibility.md), and API details live in
[`api-reference.md`](api-reference.md).

## Shipped

The original high- and medium-priority roadmap items have shipped:

- Eager/test execution via `.apply()` and `DJANGO_QSTASH_ALWAYS_EAGER`.
- A result backend through `TaskResult`, `AsyncResult`, and `EagerResult`.
- Webhook idempotency for duplicate successful deliveries.
- `async def` task execution.
- Lazy settings access that works with `override_settings`.
- `bind=True` task context with `self.request`.
- In-task retry support via `self.retry()`.
- Minimal sequential chaining through `link=`, `.s()`, and `.si()`.
- A Celery compatibility matrix and migration guide.
- Task-result observability, metrics output, DLQ triage, and requeue commands.

## Still Out Of Scope

The remaining Celery gaps are deliberate tradeoffs for a broker-free,
worker-free design:

- Full canvas primitives such as `group`, `chord`, and multi-step `chain`.
- Celery-style per-task `rate_limit` decorators; use QStash `flow_control`
  message options instead.
- In-process soft and hard time limits; use QStash `timeout` for webhook
  delivery bounds.
- Pluggable Celery result backends; django-qstash stores results in Django via
  `TaskResult`.
- Broker event streams and Flower-style live monitoring; use the admin,
  metrics command, structured logs, signals, and QStash DLQ tooling instead.

## Next Candidates

Future work should be driven by adopter demand rather than Celery parity for its
own sake. The most likely candidates are small usability improvements around the
existing observability and requeue surfaces, or documented recipes for common
deployment platforms.
