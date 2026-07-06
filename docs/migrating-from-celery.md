# Migrating from Celery to django-qstash

This guide walks an existing Celery codebase through a move to django-qstash. The
goal is a near drop-in swap: your `@shared_task` functions and your
`.delay()` / `.apply_async()` call sites keep working, but there is no broker
(Redis/RabbitMQ) and no always-on worker. Tasks run when QStash delivers a signed
webhook to your Django app, so the runtime is serverless and scale-to-zero
friendly.

If you only want the quick reference of what maps to what, see
[Celery Compatibility](celery-compatibility.md). This page is the narrative
version: the order to do things in, the gotchas, and how to test.

## At a glance

| Celery | django-qstash |
|--------|---------------|
| `from celery import shared_task` | `from django_qstash import shared_task` |
| Redis / RabbitMQ broker | Upstash QStash (HTTPS, no broker) |
| `celery -A proj worker` process | Your Django app's webhook endpoint |
| `celery -A proj beat` process | QStash Schedules via `django_qstash.schedules` |
| `result_backend` (Redis/DB/RPC) | `django_qstash.results` app (a `TaskResult` table) |
| `task_always_eager` | `DJANGO_QSTASH_ALWAYS_EAGER` |

## Step 1: Install and configure

```bash
pip install django-qstash
```

```python
# settings.py
INSTALLED_APPS = [
    # ...
    "django_qstash",
    "django_qstash.results",  # optional: AsyncResult.get()/.status/.result
    "django_qstash.schedules",  # optional: cron-style scheduling
]

# Required QStash credentials (from the Upstash console)
QSTASH_TOKEN = "..."
QSTASH_CURRENT_SIGNING_KEY = "..."
QSTASH_NEXT_SIGNING_KEY = "..."

# The public base URL QStash calls back into.
DJANGO_QSTASH_DOMAIN = "https://your-app.example.com"
```

Wire up the webhook URL so QStash can deliver tasks:

```python
# urls.py
from django.urls import include, path

urlpatterns = [
    # ...
    path("", include("django_qstash.urls")),  # serves /qstash/webhook/
]
```

Run migrations if you enabled the results or schedules apps:

```bash
python manage.py migrate
```

## Step 2: Swap the import

This is usually the only code change in your task modules:

```diff
-from celery import shared_task
+from django_qstash import shared_task


 @shared_task
 def send_welcome_email(user_id, email):
     ...
```

`@shared_task` and `@stashed_task` are aliases; both wrap your function so that
`.delay()`, `.apply_async()`, and `.apply()` behave the way Celery taught you.

Your call sites do not change:

```python
send_welcome_email.delay(user_id=123, email="user@example.com")
send_welcome_email.apply_async(args=(123, "user@example.com"), countdown=60)
```

## Step 3: Make arguments JSON-serializable

This is the single most common migration fix. Task `args`/`kwargs` are sent to
QStash as a JSON body, so they must be JSON-serializable. Pass identifiers, not
objects:

```diff
-process_order.delay(order)            # a model instance
+process_order.delay(order.id)         # a primary key

-email_users.delay(User.objects.all()) # a queryset
+email_users.delay(list(ids))          # a list of ids

-run_at.delay(datetime.now())          # a datetime
+run_at.delay(timezone.now().isoformat())
```

Inside the task, re-fetch what you need from the database. This is good practice
under Celery too (it avoids stale serialized state), so most codebases need only
a few changes.

## Step 4: `bind=True`, `self.request`, and `self.retry()`

Bound tasks work as in Celery. The task receives a `self` whose `self.request`
exposes `id`, `retries`, `correlation_id`, `task_name`, `args`, and `kwargs`:

```python
@shared_task(bind=True, max_retries=5)
def fetch_report(self, report_id):
    try:
        return call_flaky_api(report_id)
    except TemporaryError as exc:
        # Abort this run and schedule another. self.request.retries increments
        # each attempt; once it reaches max_retries the exc is re-raised.
        raise self.retry(exc=exc, countdown=10)
```

What is the same as Celery:

- `self.retry()` aborts the current run and schedules another.
- `self.request.retries` increments on each attempt.
- `max_retries` (default 3) bounds the attempts; exhausting it raises
  `MaxRetriesExceededError` (or the `exc` you passed).
- `countdown` / `eta`, `args` / `kwargs` overrides, and `max_retries` overrides
  are all honored.

What differs (see [Compatibility](celery-compatibility.md) for the full note):

- A live retry publishes a *new* QStash message, so it gets a new message id. The
  `AsyncResult` from your original `.delay()` does not follow the retried run.
- The current delivery is acked (HTTP 200) and recorded with a `RETRY` status so
  QStash does not *also* auto-retry it (which would double-run the task).

`MaxRetriesExceededError` and `Retry` live in `django_qstash.exceptions`:

```python
from django_qstash.exceptions import MaxRetriesExceededError
```

## Step 5: Chaining (run B after A)

Celery's `chain` / `link=` for the sequential "run B after A succeeds" case maps
to `apply_async(link=...)`:

```python
from django_qstash import shared_task


@shared_task
def step_a(x, y):
    return x + y


@shared_task
def step_b(label): ...


# Enqueue step_b after step_a succeeds.
step_a.apply_async(args=(1, 2), link=step_b.s("done"))
```

`.s()` / `.si()` build signatures just like Celery. Only registered
`@stashed_task` functions are chained, and the parent's return value is not
forwarded to the linked task. Parallel `group` and `chord` are **not** supported:
there is no broker primitive to fan results back in. If you depend on `chord`,
keep that specific workflow on Celery or restructure it.

## Step 6: Scheduling (replace Celery beat)

Drop the `celery beat` process. Use `django_qstash.schedules`, which stores cron
schedules in a `TaskSchedule` model and registers them with QStash Schedules. See
[API Reference - TaskSchedule](api-reference.md#taskschedule-model).

## Step 7: Results (replace your result backend)

Install `django_qstash.results` to get a Celery-shaped `AsyncResult`:

```python
result = my_task.delay(1, 2)
result.id  # the QStash message id
result.status  # PENDING until the webhook runs the task
result.get()  # blocks (polls the TaskResult table) until terminal
```

Two differences to internalize:

- **Eventual consistency.** Results arrive via webhook, so `.get()` in the same
  request that called `.delay()` will block (or time out); it will not return
  immediately.
- **The results app is required** for `.get()` / `.status` / `.result` to
  resolve. Without it, every lookup stays `PENDING`. `EagerResult` (from
  `.apply()` or eager mode) is the exception, since it holds the value in memory.

## Step 8: Update your tests

Replace `task_always_eager` with `DJANGO_QSTASH_ALWAYS_EAGER`:

```python
from django.test import override_settings


@override_settings(DJANGO_QSTASH_ALWAYS_EAGER=True)
def test_signup_sends_email():
    sign_up(user_id=1)
    # .delay()/.apply_async() ran inline and returned an EagerResult.
```

Or call `.apply()` directly, which always runs inline and needs no QStash token,
domain, or network. It returns an `EagerResult` carrying the exact return value
(or the raised exception):

```python
def test_add():
    assert add.apply(args=(2, 3)).get() == 5
```

Eager mode also runs `link=` chains and inline `self.retry()` loops, so your
retry/branching logic is testable without a broker.

## Things that stay on Celery (or get redesigned)

These have no broker-free equivalent:

- `group` / `chord` (parallel fan-out + join).
- `rate_limit` as a per-task decorator option (use QStash `flow_control`).
- `soft_time_limit` / `time_limit` with `SoftTimeLimitExceeded` (the closest knob
  is the QStash `timeout` message option, which bounds the webhook request).
- Flower / task-event monitoring (inspect the `TaskResult` table, the Django
  admin, structured logs, and the `qstash_dlq` management command instead).

## Migration checklist

- [ ] `pip install django-qstash`, set credentials + `DJANGO_QSTASH_DOMAIN`.
- [ ] Add `django_qstash` (and optionally `.results` / `.schedules`) to
      `INSTALLED_APPS`; include `django_qstash.urls`; run `migrate`.
- [ ] Replace `from celery import shared_task` with
      `from django_qstash import shared_task`.
- [ ] Make all task `args`/`kwargs` JSON-serializable (ids, not objects).
- [ ] Confirm `bind=True` tasks and any `self.retry()` calls behave as expected.
- [ ] Port `chain` / `link=` chains; flag any `group` / `chord` usage for
      redesign.
- [ ] Move `celery beat` schedules to `django_qstash.schedules`.
- [ ] Swap `task_always_eager` for `DJANGO_QSTASH_ALWAYS_EAGER` in tests.
- [ ] Decommission the broker and worker/beat processes.

## See also

- [Celery Compatibility](celery-compatibility.md) - the full supported-vs-differs matrix
- [API Reference](api-reference.md) - decorators, task methods, `AsyncResult` / `EagerResult`
- [Configuration](configuration.md) - every setting, including the eager/dedup flags
- [Getting Started](getting-started.md) - installation and first task
