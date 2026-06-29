# API Reference

This document provides detailed documentation for all public APIs in django-qstash.

## Table of Contents

- [Decorators](#decorators)
  - [@stashed_task](#stashed_task)
  - [@shared_task](#shared_task)
- [Task Methods](#task-methods)
  - [.delay()](#delay)
  - [.apply_async()](#apply_async)
  - [.apply()](#apply)
  - [Direct Execution](#direct-execution)
- [Bound Tasks (bind=True)](#bound-tasks-bindtrue)
- [Task Chaining (link / .s())](#task-chaining-link--s)
- [Testing Tasks (Eager Mode)](#testing-tasks-eager-mode)
- [AsyncResult](#asyncresult)
  - [EagerResult](#eagerresult)
- [Models](#models)
  - [TaskResult](#taskresult-model)
  - [TaskSchedule](#taskschedule-model)
  - [TaskStatus](#taskstatus)
- [Management Commands](#management-commands)
- [Exceptions](#exceptions)
- [Utility Functions](#utility-functions)

---

## Decorators

### `@stashed_task`

The primary decorator for defining background tasks.

```python
from django_qstash import stashed_task


@stashed_task
def my_task(arg1, arg2, kwarg1=None):
    # Task logic here
    pass
```

#### Signature

```python
def stashed_task(
    func: Callable | None = None,
    name: str | None = None,
    deduplicated: bool = False,
    bind: bool = False,
    **options: dict[str, Any],
) -> QStashTask: ...
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `func` | `Callable` | `None` | The function to wrap (auto-populated when used as decorator) |
| `name` | `str` | Function name | Custom name for the task (used in logging and admin) |
| `deduplicated` | `bool` | `False` | Enable content-based deduplication in QStash |
| `bind` | `bool` | `False` | Pass a bound `self` (with `self.request`) as the task's first argument (see [Bound Tasks](#bound-tasks-bindtrue)) |
| `**options` | `dict` | `{}` | Additional options passed to QStash |

#### Options

The `**options` parameter supports:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `max_retries` | `int` | `3` | Number of retry attempts on failure |

#### Examples

**Basic usage:**

```python
@stashed_task
def send_email(to: str, subject: str, body: str):
    """Send an email in the background."""
    # Email sending logic
    pass
```

**With custom name:**

```python
@stashed_task(name="Email Sender")
def send_email(to: str, subject: str, body: str):
    pass
```

**With deduplication:**

```python
@stashed_task(deduplicated=True)
def process_order(order_id: int):
    """Prevents duplicate processing of the same order."""
    pass
```

**With custom retries:**

```python
@stashed_task(max_retries=5)
def critical_task(data: dict):
    """Retry up to 5 times on failure."""
    pass
```

---

### `@shared_task`

An alias for `@stashed_task` that provides Celery compatibility.

```python
from django_qstash import shared_task


@shared_task
def my_task():
    pass
```

This is functionally identical to `@stashed_task` and exists to make migration from Celery easier:

```python
# Before (Celery)
from celery import shared_task

# After (django-qstash)
from django_qstash import shared_task
```

---

## Task Methods

### `.delay()`

Immediately queue a task for background execution.

#### Signature

```python
def delay(self, *args, **kwargs) -> AsyncResult: ...
```

#### Parameters

All positional and keyword arguments are passed directly to the task function.

#### Returns

An `AsyncResult` object containing the task ID. When
`DJANGO_QSTASH_ALWAYS_EAGER` is enabled, the task runs inline and an
`EagerResult` is returned instead (see [Testing Tasks](#testing-tasks-eager-mode)).

#### Example

```python
from myapp.tasks import send_email

# Queue the task
result = send_email.delay(
    to="user@example.com", subject="Welcome!", body="Thanks for signing up."
)

print(f"Task queued with ID: {result.task_id}")
```

---

### `.apply_async()`

Queue a task with additional control over execution.

#### Signature

```python
def apply_async(
    self,
    args: tuple | None = None,
    kwargs: dict | None = None,
    countdown: int | None = None,
    eta: datetime | int | float | None = None,
    link: Signature | list[Signature] | None = None,
    **options: dict[str, Any],
) -> AsyncResult: ...
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `args` | `tuple` | `None` | Positional arguments for the task |
| `kwargs` | `dict` | `None` | Keyword arguments for the task |
| `countdown` | `int` | `None` | Delay in seconds before executing |
| `eta` | `datetime \| int \| float` | `None` | Absolute time to run (mapped to QStash `not_before`) |
| `link` | `Signature \| list[Signature]` | `None` | Success-link(s) to run after this task succeeds (see [Task Chaining](#task-chaining-link--s)) |
| `**options` | `dict` | `{}` | Additional options (merged with decorator options) |

#### Returns

An `AsyncResult` object containing the task ID.

#### Examples

**Basic usage:**

```python
send_email.apply_async(
    args=("user@example.com",), kwargs={"subject": "Welcome!", "body": "Hello!"}
)
```

**With countdown (delayed execution):**

```python
# Execute in 5 minutes
send_email.apply_async(
    args=("user@example.com",), kwargs={"subject": "Reminder"}, countdown=300
)

# Execute in 1 hour
send_email.apply_async(
    args=("user@example.com",), kwargs={"subject": "Follow-up"}, countdown=3600
)
```

**Override retries:**

```python
send_email.apply_async(args=("user@example.com",), max_retries=5)
```

---

### `.apply()`

Execute the task **synchronously** in the current process and return an
[`EagerResult`](#eagerresult) carrying the return value (or the raised
exception). This is the Celery `Task.apply()` equivalent and is the primary
tool for unit-testing code that enqueues tasks: it requires no `QSTASH_TOKEN`,
no `DJANGO_QSTASH_DOMAIN`, and makes no network calls.

#### Signature

```python
def apply(
    self,
    args: tuple | None = None,
    kwargs: dict | None = None,
    **options: dict[str, Any],
) -> EagerResult: ...
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `args` | `tuple` | `None` | Positional arguments for the task |
| `kwargs` | `dict` | `None` | Keyword arguments for the task |
| `**options` | `dict` | `{}` | Accepted for Celery compatibility and ignored (delivery options have no meaning inline) |

#### Returns

An [`EagerResult`](#eagerresult) holding the task's return value or exception.

#### Examples

```python
from myapp.tasks import add

result = add.apply(args=(2, 3))
assert result.get() == 5
assert result.status == "SUCCESS"

# A task that raises is captured; get() re-raises it (propagate defaults to True)
result = add.apply(args=("bad", "input"))
assert result.failed()
result.get()  # re-raises the original exception
```

`async def` tasks are supported: `apply()` runs them to completion via
`asgiref.sync.async_to_sync`, so `result.get()` returns the resolved value.

---

### Direct Execution

Tasks can be called directly like normal functions (without going through QStash):

```python
from myapp.tasks import send_email

# Execute immediately in the current process
result = send_email("user@example.com", subject="Test", body="Hello")
```

This is useful for:
- Running tasks synchronously when needed
- Debugging task logic

For testing, prefer [`.apply()`](#apply) or
[eager mode](#testing-tasks-eager-mode), which capture the result and do not
require QStash configuration.

---

## Bound Tasks (`bind=True`)

`@stashed_task(bind=True)` (and `@shared_task(bind=True)`) is the Celery
`bind=True` equivalent: the task body receives a bound `self` as its first
positional argument, exposing the execution context via `self.request`.

```python
from django_qstash import shared_task


@shared_task(bind=True)
def process(self, order_id: int):
    print(self.request.id)  # QStash message id (task id)
    print(self.request.retries)  # delivery attempt count from QStash
    # self-reschedule on a transient failure:
    if not ready(order_id):
        self.apply_async(args=(order_id,), countdown=30)
```

### `self.request` attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `id` | `str` | The QStash message id (task id). A generated uuid in eager/direct execution. |
| `retries` | `int` | Current delivery attempt count from QStash's `Upstash-Retried` header. `0` when absent or in eager mode. |
| `correlation_id` | `str` | Correlation id for the request (the message id at the webhook; the generated id in eager mode). |
| `task_name` | `str` | The task's name. |
| `args` | `tuple` | Positional arguments the task was called with. |
| `kwargs` | `dict` | Keyword arguments the task was called with. |

The bound `self` also delegates to the underlying task, so `self.name`,
`self.delay(...)`, `self.apply_async(...)`, and `self.s(...)` are all available
for self-rescheduling and chaining.

A fresh bound object is built for every call, so per-call request state is never
shared across concurrent webhook deliveries (thread-safe by construction).
`bind=True` works identically for `async def` tasks, which are awaited to
completion.

---

## Task Chaining (`link=` / `.s()`)

A minimal, sequential "run B after A succeeds" chain (the common Celery `link`
case). Groups, chords, and parallel canvas are intentionally out of scope.

### `.s()` / `.si()` signatures

`task.s(*args, **kwargs)` returns a `Signature`: a lightweight, serializable
reference to a task call (its function path plus the args/kwargs to invoke it
with). `.si()` is the immutable variant; it behaves identically here because the
parent task's return value is **not** forwarded to linked tasks.

```python
sig = send_receipt.s(order_id=42)
sig.function_path  # "myapp.tasks.send_receipt"
```

### Linking with `apply_async(link=...)`

```python
from myapp.tasks import charge_card, send_receipt, notify_warehouse

# Run send_receipt after charge_card succeeds
charge_card.apply_async(args=(order_id,), link=send_receipt.s(order_id))

# Fan out to several follow-ups (each enqueued after success)
charge_card.apply_async(
    args=(order_id,),
    link=[send_receipt.s(order_id), notify_warehouse.s(order_id)],
)
```

How it works:

- The link signatures are serialized into task A's QStash payload under
  `on_success`.
- After A executes successfully (and its result is stored), the webhook handler
  enqueues each linked task through its normal `apply_async` path.
- Each linked function path is validated against the registered-task allowlist
  (`discover_tasks`). Links that are not registered `@stashed_task`s, cannot be
  imported, or fail to enqueue are logged and skipped; a chaining problem never
  fails task A's `200` response.
- In [eager mode](#testing-tasks-eager-mode) (and `.apply()`), links run inline
  after a successful parent, so chains can be asserted in tests with no network.

`delay()` has no options parameter, so chaining is done via
`apply_async(link=...)` only (this matches Celery).

---

## Testing Tasks (Eager Mode)

Two mechanisms let you run tasks inline without a QStash token, domain, or
network access, mirroring Celery's eager testing story:

1. **`.apply()`** runs a single task synchronously and returns an
   [`EagerResult`](#eagerresult). Use it when you want to call a task directly
   in a test and assert on its result.

2. **`DJANGO_QSTASH_ALWAYS_EAGER = True`** makes every `.delay()` /
   `.apply_async()` call run inline and return an `EagerResult`, so the code
   under test does not need to change. Set this in your test settings.

```python
# test_settings.py
DJANGO_QSTASH_ALWAYS_EAGER = True
```

```python
# In a test
from myapp.tasks import add


def test_add_task():
    result = add.delay(2, 3)  # runs inline because ALWAYS_EAGER is on
    assert result.get() == 5
```

Eager execution preserves the exact return value (no results-backend
round-trip), so types such as `int`, `list`, and custom dicts come back
unchanged.

---

## AsyncResult

A Celery-compatible result handle returned by `.delay()` and `.apply_async()`.
When `django_qstash.results` is installed, it is backed by the
[`TaskResult`](#taskresult-model) table: it looks up rows by the QStash message
id (`task_id`) so you can read a task's status and result after the webhook has
run. Results are **eventually consistent**: until the webhook executes the task,
the status is `PENDING`.

If `django_qstash.results` is not installed, the status is always `PENDING` and
`.get()` will time out.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `task_id` | `str` | The QStash message ID |
| `id` | `str` | Alias for `task_id` |
| `status` | `str` | Latest [`TaskStatus`](#taskstatus) for the task, or `PENDING` |
| `state` | `str` | Alias for `status` |
| `result` | `Any` | The task's return value once available, else `None` |
| `traceback` | `str \| None` | Stored traceback string if the task failed |

### Methods

| Method | Description |
|--------|-------------|
| `ready()` | `True` once a terminal result row exists |
| `successful()` | `True` if the task finished with `SUCCESS` |
| `failed()` | `True` if the task finished with an error status |

#### `.get()`

```python
def get(
    self,
    timeout: float | None = None,
    interval: float | None = None,
    propagate: bool = True,
) -> Any: ...
```

Blocks until a terminal result is stored, polling the results backend every
`interval` seconds (defaults to `DJANGO_QSTASH_RESULT_POLL_INTERVAL`). With
`timeout=None` (the default) it waits indefinitely; otherwise it raises
`TaskTimeoutError` once `timeout` seconds elapse. If the task failed and
`propagate` is `True`, it raises `TaskResultError` carrying the stored
traceback.

### Example

```python
result = my_task.delay(arg1, arg2)

print(f"Task ID: {result.id}")

# Poll the results backend for up to 30 seconds
value = result.get(timeout=30)

# Or inspect without blocking
if result.ready():
    print(result.status, result.result)
```

### EagerResult

Returned by [`.apply()`](#apply) and by `.delay()` / `.apply_async()` when
`DJANGO_QSTASH_ALWAYS_EAGER` is enabled. It carries the return value (or
exception) in memory, so `status`, `result`, and `get()` resolve immediately
with no database round-trip:

```python
result = my_task.apply(args=(2, 3))
assert result.ready() is True
assert result.get() == 5
```

For a task that raised, `get()` re-raises the original exception (or returns it
when called with `propagate=False`).

---

## Models

### TaskResult Model

Stores task execution results. Available when `django_qstash.results` is installed.

**Location**: `django_qstash.results.models.TaskResult`

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | `UUIDField` | Primary key (auto-generated UUID) |
| `task_id` | `CharField(255)` | QStash message ID |
| `task_name` | `CharField(255)` | Name of the task |
| `status` | `CharField(50)` | Task status (see [TaskStatus](#taskstatus)) |
| `date_created` | `DateTimeField` | When the result was created |
| `date_done` | `DateTimeField` | When the task completed (nullable) |
| `result` | `JSONField` | Task return value (nullable) |
| `traceback` | `TextField` | Error traceback if failed (nullable) |
| `function_path` | `TextField` | Full Python path to the task function |
| `args` | `JSONField` | Positional arguments passed to the task |
| `kwargs` | `JSONField` | Keyword arguments passed to the task |

#### Example Queries

```python
from django_qstash.results.models import TaskResult
from django_qstash.db.models import TaskStatus

# Get all successful results
successful = TaskResult.objects.filter(status=TaskStatus.SUCCESS)

# Get failed results
failed = TaskResult.objects.filter(
    status__in=[TaskStatus.EXECUTION_ERROR, TaskStatus.INTERNAL_ERROR]
)

# Get results for a specific task
email_results = TaskResult.objects.filter(task_name="send_email")

# Get recent results
from django.utils import timezone
from datetime import timedelta

recent = TaskResult.objects.filter(date_done__gte=timezone.now() - timedelta(hours=24))
```

---

### TaskSchedule Model

Represents a scheduled task using QStash Schedules. Available when `django_qstash.schedules` is installed.

**Location**: `django_qstash.schedules.models.TaskSchedule`

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `schedule_id` | `CharField(255)` | QStash schedule ID (auto-populated) |
| `name` | `CharField(200)` | Human-readable name for the schedule |
| `task` | `TaskField` | The task to execute. In forms/admin this is a dropdown of discovered tasks; in Python it can be a dotted task path or decorated task object. |
| `task_name` | `CharField(255)` | Managed Python path of the selected task |
| `args` | `JSONField` | Positional arguments as JSON list |
| `kwargs` | `JSONField` | Keyword arguments as JSON dict |
| `cron` | `CharField(255)` | Cron expression (e.g., `"0 0 * * *"`) |
| `retries` | `IntegerField` | Number of retries (default: 3, max: 5) |
| `timeout` | `CharField(10)` | Timeout duration string (e.g., `"60s"`) |
| `retry_delay` | `CharField(255)` | Optional QStash retry-delay expression |
| `delay` | `CharField(32)` | Optional delivery delay after each cron trigger |
| `queue` | `CharField(255)` | Optional QStash queue for FIFO scheduled delivery |
| `headers` | `JSONField` | Headers forwarded to the task webhook |
| `callback` | `URLField(2048)` | Optional callback URL called after each delivery attempt |
| `callback_headers` | `JSONField` | Headers forwarded to the callback URL |
| `failure_callback` | `URLField(2048)` | Optional callback URL called after retries are exhausted |
| `failure_callback_headers` | `JSONField` | Headers forwarded to the failure callback URL |
| `flow_control` | `JSONField` | Optional QStash flow control settings |
| `label` | `CharField(255)` | Optional QStash label for logs and DLQ filtering |
| `redact` | `JSONField` | Optional QStash log redaction settings |
| `updated_at` | `DateTimeField` | Last update timestamp |
| `is_active` | `BooleanField` | Whether the schedule is active |
| `active_at` | `DateTimeField` | When the schedule was activated |
| `is_paused` | `BooleanField` | Whether the schedule is paused |
| `paused_at` | `DateTimeField` | When the schedule was paused |
| `is_resumed` | `BooleanField` | Whether the schedule was resumed |
| `resumed_at` | `DateTimeField` | When the schedule was resumed |

#### Cron Expression Format

The `cron` field uses standard cron syntax:

```
* * * * *
| | | | |
| | | | +-- Day of week (0-7, where 0 and 7 are Sunday)
| | | +---- Month (1-12)
| | +------ Day of month (1-31)
| +-------- Hour (0-23)
+---------- Minute (0-59)
```

Use [crontab.guru](https://crontab.guru/) to build cron expressions.

QStash timezone prefixes are supported:

```text
CRON_TZ=America/New_York 0 4 * * *
```

#### Example: Creating a Schedule

```python
from django_qstash.schedules.models import TaskSchedule

# Run every day at midnight
TaskSchedule.objects.create(
    name="Daily Report",
    task="myapp.tasks.generate_daily_report",
    cron="0 0 * * *",
    args=[],
    kwargs={"format": "pdf"},
)

# Run every 5 minutes
TaskSchedule.objects.create(
    name="Health Check",
    task="myapp.tasks.health_check",
    cron="*/5 * * * *",
)

# Run every Monday at 9 AM
TaskSchedule.objects.create(
    name="Weekly Summary",
    task="myapp.tasks.send_weekly_summary",
    cron="0 9 * * 1",
    retries=5,
    timeout="300s",
)

# Run every morning in a specific timezone with QStash delivery controls
TaskSchedule.objects.create(
    name="Daily Email Digest",
    task="myapp.tasks.send_daily_digest",
    cron="CRON_TZ=America/New_York 0 7 * * *",
    retries=5,
    retry_delay="1000 * (1 + retried)",
    timeout="120s",
    delay="30s",
    queue="emails",
    headers={"X-Trace-Source": "daily-digest"},
    failure_callback="https://example.com/qstash/failure/",
    flow_control={"key": "daily-digest", "rate": 10, "period": "1m"},
    label="scheduled,email",
    redact={"body": True},
)
```

#### Methods

| Method | Description |
|--------|-------------|
| `did_just_resume(delta_seconds=60)` | Check if schedule was resumed within the time window |
| `did_just_pause(delta_seconds=60)` | Check if schedule was paused within the time window |

---

### TaskStatus

Enumeration of possible task statuses.

**Location**: `django_qstash.db.models.TaskStatus`

| Status | Value | Description |
|--------|-------|-------------|
| `PENDING` | `"PENDING"` | Task is queued but not yet executed |
| `SUCCESS` | `"SUCCESS"` | Task completed successfully |
| `EXECUTION_ERROR` | `"EXECUTION_ERROR"` | Task raised an exception |
| `INTERNAL_ERROR` | `"INTERNAL_ERROR"` | Unexpected error in webhook handler |
| `OTHER_ERROR` | `"OTHER_ERROR"` | Other error type |
| `UNKNOWN` | `"UNKNOWN"` | Unknown status |

#### Usage

```python
from django_qstash.db.models import TaskStatus
from django_qstash.results.models import TaskResult

# Filter by status
errors = TaskResult.objects.filter(
    status__in=[
        TaskStatus.EXECUTION_ERROR,
        TaskStatus.INTERNAL_ERROR,
        TaskStatus.OTHER_ERROR,
    ]
)
```

---

## Management Commands

### `available_tasks`

List all discovered tasks in your Django project.

```bash
python manage.py available_tasks
```

**Options:**

| Option | Description |
|--------|-------------|
| `--locations` | Only show task paths (without additional details) |

**Output Example:**

```
Available tasks:
  Name: send_email
  Location: myapp.tasks.send_email
  Field Label: myapp.tasks.send_email

  Name: Cleanup Task Results
  Location: django_qstash.results.tasks.clear_stale_results_task
  Field Label: Cleanup Task Results (django_qstash.results.tasks)
```

---

### `clear_stale_results`

Remove old task results from the database.

```bash
python manage.py clear_stale_results
```

**Requirements:** `django_qstash.results` must be installed.

**Options:**

| Option | Description |
|--------|-------------|
| `--since <seconds>` | Delete results older than this many seconds (default: `DJANGO_QSTASH_RESULT_TTL`) |
| `--no-input` | Skip confirmation prompt |
| `--delay` | Run as a background task via django-qstash |

**Examples:**

```bash
# Delete results older than 7 days (default)
python manage.py clear_stale_results

# Delete results older than 24 hours
python manage.py clear_stale_results --since 86400

# Delete without confirmation
python manage.py clear_stale_results --no-input

# Run as a background task
python manage.py clear_stale_results --delay
```

---

### `task_schedules`

List and sync QStash schedules.

```bash
python manage.py task_schedules --list
```

**Requirements:** `django_qstash.schedules` must be installed.

**Options:**

| Option | Description |
|--------|-------------|
| `--list` | List all schedules from QStash |
| `--sync` | Sync remote schedules to local database |
| `--no-input` | Skip confirmation prompt during sync |

**Examples:**

```bash
# List schedules
python manage.py task_schedules --list

# Sync schedules to local database
python manage.py task_schedules --sync

# Sync without confirmation
python manage.py task_schedules --sync --no-input
```

**Output Example:**

```
Found 2 remote schedules based on destination: https://example.com/qstash/webhook/

Schedule ID: sched_abc123
  Task: Daily Report (myapp.tasks.generate_daily_report)
  Cron: 0 0 * * *
  Destination: https://example.com/qstash/webhook/
  Retries: 3
  Status: Active

Schedule ID: sched_def456
  Task: Health Check (myapp.tasks.health_check)
  Cron: */5 * * * *
  Destination: https://example.com/qstash/webhook/
  Retries: 3
  Status: Paused
```

---

### `qstash_dlq`

List, inspect, and delete QStash dead letter queue messages.

```bash
python manage.py qstash_dlq --list
```

**Options:**

| Option | Description |
|--------|-------------|
| `--list` | List DLQ messages |
| `--get <dlq_id>` | Fetch one DLQ message |
| `--delete <dlq_id>` | Delete one DLQ message |
| `--delete-many <dlq_id> [<dlq_id> ...]` | Delete multiple DLQ messages |
| `--count <n>` | Maximum number of DLQ messages to list |
| `--cursor <cursor>` | Pagination cursor returned by a previous list call |
| `--message-id <message_id>` | Filter by QStash message ID |
| `--url <url>` | Filter by destination URL |
| `--url-group <name>` | Filter by URL group |
| `--queue <name>` | Filter by queue name |
| `--schedule-id <schedule_id>` | Filter by schedule ID |
| `--response-status <status>` | Filter by final HTTP response status |
| `--label <label>` | Filter by QStash label |

**Examples:**

```bash
# List recent DLQ messages
python manage.py qstash_dlq --list --count 20

# Filter failed scheduled email deliveries
python manage.py qstash_dlq --list --queue emails --label scheduled,email

# Inspect one failed delivery
python manage.py qstash_dlq --get dlq_abc123

# Delete DLQ entries after triage
python manage.py qstash_dlq --delete dlq_abc123
python manage.py qstash_dlq --delete-many dlq_abc123 dlq_def456
```

---

## Exceptions

All exceptions are defined in `django_qstash.exceptions`.

### `WebhookError`

Base exception for webhook handling errors.

```python
from django_qstash.exceptions import WebhookError
```

### `SignatureError`

Raised when webhook signature verification fails.

```python
from django_qstash.exceptions import SignatureError
```

**Common Causes:**
- Invalid or missing `Upstash-Signature` header
- Incorrect signing keys in settings
- URL mismatch (HTTP vs HTTPS)

### `PayloadError`

Raised when the webhook payload is invalid.

```python
from django_qstash.exceptions import PayloadError
```

**Common Causes:**
- Invalid JSON in request body
- Missing required fields (`function`, `module`, `args`, `kwargs`)
- Invalid argument types

### `TaskError`

Raised when task execution fails.

```python
from django_qstash.exceptions import TaskError
```

**Common Causes:**
- Task function raised an exception
- Task function could not be imported

### `TaskResultError`

Raised by [`AsyncResult.get()`](#get-1) when resolving a task that did not
succeed (and `propagate=True`). The original traceback string from the results
backend is preserved in the message.

```python
from django_qstash.exceptions import TaskResultError
```

### `TaskTimeoutError`

Subclass of `TaskResultError`, raised by `AsyncResult.get(timeout=...)` when the
timeout elapses before a terminal result is stored.

```python
from django_qstash.exceptions import TaskTimeoutError
```

---

## Utility Functions

### Task Discovery

```python
from django_qstash.discovery.utils import discover_tasks

# Get all tasks with metadata
tasks = discover_tasks()
# Returns: [{"name": "...", "field_label": "...", "location": "..."}, ...]

# Get only task locations
locations = discover_tasks(locations_only=True)
# Returns: ["myapp.tasks.my_task", "other_app.tasks.other_task", ...]
```

### Callback URL

```python
from django_qstash.callbacks import get_callback_url

# Get the full webhook URL
url = get_callback_url()
# Returns: "https://example.com/qstash/webhook/"
```

---

## Arguments Serialization

All task arguments must be JSON-serializable. The following types are supported:

**Supported:**
- `str`, `int`, `float`, `bool`, `None`
- `list`, `tuple` (converted to list)
- `dict` (with string keys)

**Not Supported (must be converted):**
- Django model instances (use `model.pk` instead)
- QuerySets (use `list(qs.values_list('pk', flat=True))`)
- `datetime` objects (use `.isoformat()` or `.timestamp()`)
- Custom objects

**Example:**

```python
# Wrong - will fail
@stashed_task
def process_user(user):  # Django User object
    pass


user = User.objects.get(pk=1)
process_user.delay(user)  # Raises JSON serialization error


# Correct
@stashed_task
def process_user(user_id: int):
    user = User.objects.get(pk=user_id)
    # Process user...


user = User.objects.get(pk=1)
process_user.delay(user.pk)  # Works!
```

---

## Related Documentation

- [Getting Started](getting-started.md) - Quick setup guide
- [Configuration](configuration.md) - All settings reference
- [Troubleshooting](troubleshooting.md) - Common issues and solutions
