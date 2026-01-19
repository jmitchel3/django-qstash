# API Reference

This document provides detailed documentation for all public APIs in django-qstash.

## Table of Contents

- [Decorators](#decorators)
  - [@stashed_task](#stashed_task)
  - [@shared_task](#shared_task)
- [Task Methods](#task-methods)
  - [.delay()](#delay)
  - [.apply_async()](#apply_async)
  - [Direct Execution](#direct-execution)
- [AsyncResult](#asyncresult)
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
    **options: dict[str, Any],
) -> QStashTask:
    ...
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `func` | `Callable` | `None` | The function to wrap (auto-populated when used as decorator) |
| `name` | `str` | Function name | Custom name for the task (used in logging and admin) |
| `deduplicated` | `bool` | `False` | Enable content-based deduplication in QStash |
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
def delay(self, *args, **kwargs) -> AsyncResult:
    ...
```

#### Parameters

All positional and keyword arguments are passed directly to the task function.

#### Returns

An `AsyncResult` object containing the task ID.

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
    **options: dict[str, Any],
) -> AsyncResult:
    ...
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `args` | `tuple` | `None` | Positional arguments for the task |
| `kwargs` | `dict` | `None` | Keyword arguments for the task |
| `countdown` | `int` | `None` | Delay in seconds before executing |
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

### Direct Execution

Tasks can be called directly like normal functions (without going through QStash):

```python
from myapp.tasks import send_email

# Execute immediately in the current process
result = send_email("user@example.com", subject="Test", body="Hello")
```

This is useful for:
- Testing tasks locally
- Running tasks synchronously when needed
- Debugging task logic

---

## AsyncResult

A minimal Celery-compatible result object returned by `.delay()` and `.apply_async()`.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `task_id` | `str` | The QStash message ID |
| `id` | `str` | Alias for `task_id` |

### Methods

#### `.get()`

```python
def get(self, timeout: int | None = None) -> Any:
    ...
```

**Note**: This method raises `NotImplementedError` because QStash does not support result retrieval in the same way as Celery. Use the `TaskResult` model if you need to access results.

### Example

```python
result = my_task.delay(arg1, arg2)

# Access the task ID
print(f"Task ID: {result.task_id}")
print(f"Task ID: {result.id}")  # Same as above

# This will raise NotImplementedError
# result.get()
```

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
| `task` | `TaskField` | The task to execute (dropdown of discovered tasks) |
| `task_name` | `CharField(255)` | Original Python path of the task |
| `args` | `JSONField` | Positional arguments as JSON list |
| `kwargs` | `JSONField` | Keyword arguments as JSON dict |
| `cron` | `CharField(255)` | Cron expression (e.g., `"0 0 * * *"`) |
| `retries` | `IntegerField` | Number of retries (default: 3, max: 5) |
| `timeout` | `CharField(10)` | Timeout duration string (e.g., `"60s"`) |
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
