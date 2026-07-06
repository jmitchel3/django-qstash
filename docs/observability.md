# Serverless Observability

django-qstash exposes task state through your Django database, admin, management
commands, structured logs, and Django signals. There is no Flower process,
broker, websocket stream, or bundled metrics backend, so the app can still scale
to zero.

## Result Dashboard

Install the results app and run migrations:

```python
INSTALLED_APPS = [
    # ...
    "django_qstash",
    "django_qstash.results",
]
```

```bash
python manage.py migrate django_qstash_results
```

The `TaskResult` admin is a read-only operational dashboard. The list view shows
task name, status, attempt, correlation id, task id, parent task id, duration,
and completion time. Search by task name, function path, task id, parent id, or
correlation id to inspect a whole lifecycle.

The detail view shows the task metadata plus formatted `args`, `kwargs`,
`result`, and `traceback`.

## Retry And Chain Lineage

Each task execution keeps a per-message `task_id` and a stable root
`correlation_id`.

- Initial deliveries use the incoming QStash message id as the correlation id.
- `self.retry()` re-enqueues the same task with the same `correlation_id`, the
  current message id as `parent_task_id`, and an incremented `attempt`.
- `apply_async(..., link=other_task.s(...))` passes the same `correlation_id` to
  linked follow-up tasks and records the parent message id.

This means a task lifecycle is queryable even when QStash assigns a new message
id to a retry or linked task. `AsyncResult` for the original retrying message can
follow the lineage to the terminal retry result for the same task function.

## Metrics

Use the built-in command for lightweight aggregates over recent `TaskResult`
rows:

```bash
python manage.py qstash_metrics --window 3600
python manage.py qstash_metrics --window 86400 --json
```

The command reports:

- total task result rows in the window
- counts by status
- success rate
- p50 and p95 duration in milliseconds

These metrics are calculated on demand from the database. For long-term graphs,
ship the JSON output or the structured logs to your metrics/log platform.

## Recovery

Failed `TaskResult` rows can be requeued from the admin action or the management
command:

```bash
python manage.py qstash_requeue --result-id <task-result-uuid>
python manage.py qstash_requeue --task-id <qstash-message-id>
python manage.py qstash_requeue --task-id <qstash-message-id> --queue emails
```

The replacement message keeps the original `correlation_id`, stores the failed
message as `parent_task_id`, and increments `attempt`.

Dead-letter queue messages can be inspected and requeued:

```bash
python manage.py qstash_dlq --list
python manage.py qstash_dlq --get <dlq-id>
python manage.py qstash_dlq --requeue <dlq-id>
python manage.py qstash_requeue --dlq-id <dlq-id> --delete-dlq
```

Use `--delete-dlq` or `--delete-after-requeue` only when you want the original
DLQ entry removed after the replacement message is accepted by QStash.

## Logs And Signals

Structured logs and Django signals are the serverless analog of Celery task
events. They are emitted during webhook receipt, task start, completion, failure,
and retry scheduling.

Enable JSON log formatting in Django and send those logs to your aggregator:

```python
LOGGING = {
    "version": 1,
    "filters": {
        "qstash_context": {
            "()": "django_qstash.logging.StructuredLogFilter",
        },
    },
    "formatters": {
        "json": {
            "()": "django_qstash.logging.JSONFormatter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["qstash_context"],
            "formatter": "json",
        },
    },
    "loggers": {
        "django_qstash": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
```

By default task arguments are not written to logs. Set
`DJANGO_QSTASH_LOG_TASK_ARGS=True` only when the payloads are safe for your log
destination.

Signals remain useful for local hooks and custom instrumentation:

- `webhook_received`
- `task_started`
- `task_completed`
- `task_failed`
