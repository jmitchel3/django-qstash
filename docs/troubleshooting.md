# Troubleshooting Guide

This guide helps you diagnose and resolve common issues with django-qstash.

## Table of Contents

- [Quick Diagnostics](#quick-diagnostics)
- [Common Errors](#common-errors)
  - [Configuration Errors](#configuration-errors)
  - [Signature Verification Errors](#signature-verification-errors)
  - [Task Execution Errors](#task-execution-errors)
  - [Scheduling Errors](#scheduling-errors)
- [Debug Mode](#debug-mode)
- [Diagnostic Commands](#diagnostic-commands)
- [FAQ](#faq)

---

## Quick Diagnostics

### Diagnostic Checklist

Run through this checklist when tasks aren't executing:

1. **Check environment variables are set:**
   ```bash
   python -c "import os; print('QSTASH_TOKEN:', 'SET' if os.environ.get('QSTASH_TOKEN') else 'MISSING')"
   python -c "import os; print('QSTASH_CURRENT_SIGNING_KEY:', 'SET' if os.environ.get('QSTASH_CURRENT_SIGNING_KEY') else 'MISSING')"
   python -c "import os; print('QSTASH_NEXT_SIGNING_KEY:', 'SET' if os.environ.get('QSTASH_NEXT_SIGNING_KEY') else 'MISSING')"
   ```

2. **Verify Django settings:**
   ```bash
   python manage.py shell -c "from django.conf import settings; print('DJANGO_QSTASH_DOMAIN:', settings.DJANGO_QSTASH_DOMAIN)"
   python manage.py shell -c "from django.conf import settings; print('DJANGO_QSTASH_WEBHOOK_PATH:', settings.DJANGO_QSTASH_WEBHOOK_PATH)"
   ```

3. **List discovered tasks:**
   ```bash
   python manage.py available_tasks
   ```

4. **Test webhook URL construction:**
   ```bash
   python manage.py shell -c "from django_qstash.callbacks import get_callback_url; print('Callback URL:', get_callback_url())"
   ```

5. **Verify webhook endpoint is accessible:**
   ```bash
   curl -X POST https://your-domain.com/qstash/webhook/ -H "Content-Type: application/json" -d '{}'
   # Should return 400 (missing signature), not 404 or 500
   ```

---

## Common Errors

### Configuration Errors

#### Error: `ImproperlyConfigured: QSTASH_TOKEN and DJANGO_QSTASH_DOMAIN must be set`

**Cause:** Required settings are missing.

**Solution:**
```python
# settings.py
QSTASH_TOKEN = os.environ.get("QSTASH_TOKEN")
DJANGO_QSTASH_DOMAIN = os.environ.get("DJANGO_QSTASH_DOMAIN")
```

Ensure these environment variables are set in your environment.

---

#### Error: `RuntimeWarning: DJANGO_SETTINGS_MODULE ... requires QSTASH_TOKEN and DJANGO_QSTASH_DOMAIN`

**Cause:** Settings are not configured when Django initializes.

**Solution:** Set the environment variables before Django starts:
```bash
export QSTASH_TOKEN="your-token"
export DJANGO_QSTASH_DOMAIN="https://your-domain.com"
python manage.py runserver
```

---

#### Error: `ImproperlyConfigured: DJANGO_QSTASH_DOMAIN is not set`

**Cause:** The domain setting is None or empty.

**Solution:**
```python
# Ensure the domain is a valid URL with protocol
DJANGO_QSTASH_DOMAIN = "https://your-domain.com"  # Include https://
```

---

### Signature Verification Errors

#### Error: `SignatureError: Missing Upstash-Signature header`

**Cause:** The incoming request doesn't have a signature header.

**Possible Causes:**
- Request is not from QStash
- Reverse proxy is stripping headers

**Solution:**

1. Verify the request comes from QStash (check Upstash Console for delivery logs)

2. Ensure your reverse proxy passes headers:
   ```nginx
   # Nginx
   proxy_set_header Upstash-Signature $http_upstash_signature;
   ```

---

#### Error: `SignatureError: Invalid signature: ...`

**Cause:** Signature verification failed.

**Common Causes:**

1. **Wrong signing keys:**
   ```python
   # Verify keys match Upstash Console
   QSTASH_CURRENT_SIGNING_KEY = "sig_..."  # Must match exactly
   QSTASH_NEXT_SIGNING_KEY = "sig_..."
   ```

2. **URL mismatch (HTTP vs HTTPS):**
   ```python
   # If your proxy handles SSL, ensure DJANGO_QSTASH_FORCE_HTTPS matches
   DJANGO_QSTASH_FORCE_HTTPS = True  # If webhook receives HTTPS
   DJANGO_QSTASH_FORCE_HTTPS = False  # If proxy terminates SSL
   ```

3. **Domain mismatch:**
   ```python
   # DJANGO_QSTASH_DOMAIN must match the URL QStash calls
   DJANGO_QSTASH_DOMAIN = "https://your-domain.com"  # Not http://
   ```

**Debugging:**
```python
# Add logging to see what URL is being verified
import logging

logging.getLogger("django_qstash").setLevel(logging.DEBUG)
```

---

### Task Execution Errors

#### Error: `TaskError: Could not import task function: ...`

**Cause:** The task function cannot be imported.

**Solutions:**

1. **Verify task is discoverable:**
   ```bash
   python manage.py available_tasks
   # Your task should appear in the list
   ```

2. **Check the import path:**
   ```bash
   # The function must be importable
   python manage.py shell -c "from myapp.tasks import my_task; print(my_task)"
   ```

3. **Ensure tasks.py exists in your app:**
   ```
   myapp/
   ├── __init__.py
   ├── tasks.py  # Must exist
   └── ...
   ```

---

#### Error: `TaskError: Task execution failed: ...`

**Cause:** Your task function raised an exception.

**Solutions:**

1. **Test the task directly:**
   ```python
   # Call without .delay() to see the actual error
   from myapp.tasks import my_task

   my_task("arg1", kwarg="value")  # Will show the actual traceback
   ```

2. **Check task arguments:**
   ```python
   # Arguments must be JSON-serializable
   import json

   args = (your_args,)
   kwargs = {"your": "kwargs"}
   json.dumps({"args": args, "kwargs": kwargs})  # Should not raise
   ```

3. **Check logs:**
   If `django_qstash.results` is installed, check the `TaskResult` model:
   ```python
   from django_qstash.results.models import TaskResult
   from django_qstash.db.models import TaskStatus

   errors = TaskResult.objects.filter(
       status__in=[TaskStatus.EXECUTION_ERROR, TaskStatus.INTERNAL_ERROR]
   ).order_by("-date_created")[:10]

   for error in errors:
       print(f"Task: {error.task_name}")
       print(f"Traceback: {error.traceback}")
       print("---")
   ```

---

#### Error: `TypeError: Object of type ... is not JSON serializable`

**Cause:** Task arguments contain non-JSON-serializable objects.

**Solutions:**

```python
# Wrong - Django model instance
@stashed_task
def process_user(user):  # User object not serializable
    pass


user = User.objects.get(pk=1)
process_user.delay(user)  # Fails!


# Correct - Pass the ID
@stashed_task
def process_user(user_id):
    user = User.objects.get(pk=user_id)
    # Process...


process_user.delay(user.pk)  # Works!
```

**Common non-serializable types:**
| Type | Solution |
|------|----------|
| Django Model | Pass `model.pk` |
| QuerySet | Pass `list(qs.values_list('pk', flat=True))` |
| datetime | Use `.isoformat()` or `.timestamp()` |
| Decimal | Convert to `float` or `str` |
| UUID | Convert to `str` |

---

### Scheduling Errors

#### Error: `LookupError: No installed app with label 'django_qstash_schedules'`

**Cause:** The schedules app is not installed.

**Solution:**
```python
INSTALLED_APPS = [
    # ...
    "django_qstash",
    "django_qstash.schedules",  # Add this
]
```

Then run migrations:
```bash
python manage.py migrate django_qstash_schedules
```

---

#### Error: Schedule not executing

**Causes and Solutions:**

1. **Schedule is paused:**
   ```python
   from django_qstash.schedules.models import TaskSchedule

   schedule = TaskSchedule.objects.get(name="My Schedule")
   print(f"Is Active: {schedule.is_active}")
   print(f"Is Paused: {schedule.is_paused}")

   # Activate if needed
   schedule.is_active = True
   schedule.save()
   ```

2. **Invalid cron expression:**
   ```python
   # Validate cron syntax at crontab.guru
   # Example: "0 0 * * *" = daily at midnight
   ```

3. **Schedule not synced to QStash:**
   ```bash
   python manage.py task_schedules --list
   # Verify your schedule appears
   ```

---

## Debug Mode

### Enable Detailed Logging

```python
# settings.py
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {funcName} {lineno} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file": {
            "class": "logging.FileHandler",
            "filename": "django_qstash_debug.log",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django_qstash": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
            "propagate": True,
        },
    },
}
```

### Log All Webhook Requests

Create a middleware to log incoming webhooks:

```python
# middleware.py
import logging
import json

logger = logging.getLogger("django_qstash.debug")


class QStashDebugMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if "/qstash/webhook/" in request.path:
            logger.debug(f"Webhook request received")
            logger.debug(f"Method: {request.method}")
            logger.debug(f"Headers: {dict(request.headers)}")
            logger.debug(f"Body: {request.body.decode()[:1000]}")

        response = self.get_response(request)

        if "/qstash/webhook/" in request.path:
            logger.debug(f"Response status: {response.status_code}")

        return response


# settings.py
MIDDLEWARE = [
    "myapp.middleware.QStashDebugMiddleware",  # Add at the top
    # ... other middleware
]
```

---

## Diagnostic Commands

### Check Task Discovery

```bash
# List all tasks
python manage.py available_tasks

# List only task paths
python manage.py available_tasks --locations
```

### Check Schedules

```bash
# List schedules from QStash
python manage.py task_schedules --list

# Sync schedules to local database
python manage.py task_schedules --sync
```

### Check Task Results

```bash
# Django shell
python manage.py shell
```

```python
from django_qstash.results.models import TaskResult
from django_qstash.db.models import TaskStatus
from django.utils import timezone
from datetime import timedelta

# Recent results
recent = TaskResult.objects.filter(
    date_created__gte=timezone.now() - timedelta(hours=24)
)
print(f"Results in last 24h: {recent.count()}")

# By status
for status in TaskStatus:
    count = TaskResult.objects.filter(status=status).count()
    print(f"{status.label}: {count}")

# Recent errors
errors = TaskResult.objects.filter(
    status__in=[TaskStatus.EXECUTION_ERROR, TaskStatus.INTERNAL_ERROR]
).order_by("-date_created")[:5]

for e in errors:
    print(f"\n{e.task_name} at {e.date_created}")
    print(f"Error: {e.traceback}")
```

### Test Webhook Locally

```bash
# Generate a test request (signature will be invalid, but useful for testing routing)
curl -X POST http://localhost:8000/qstash/webhook/ \
  -H "Content-Type: application/json" \
  -H "Upstash-Signature: test" \
  -d '{"function": "test", "module": "test", "args": [], "kwargs": {}}'

# Expected response: 400 with "Invalid signature" error
```

---

## FAQ

### Why aren't my tasks executing?

1. Check that your domain is publicly accessible
2. Verify QStash credentials are correct
3. Ensure the webhook path matches your URL configuration
4. Check Django logs for errors

### How do I test tasks locally?

Option 1: Call directly without `.delay()`:
```python
from myapp.tasks import my_task

result = my_task("arg1", kwarg="value")
```

Option 2: Use a tunnel service (ngrok, Cloudflare Tunnels):
```bash
ngrok http 8000
# Update DJANGO_QSTASH_DOMAIN with the ngrok URL
```

Option 3: Use local QStash with Docker:
```bash
docker compose -f compose.dev.yaml up
```

### How do I debug signature verification?

1. Enable debug logging
2. Check that `DJANGO_QSTASH_FORCE_HTTPS` matches your setup
3. Verify signing keys in Upstash Console
4. Ensure URL in settings matches actual webhook URL

### How do I view task results?

```python
from django_qstash.results.models import TaskResult

# Get latest results
results = TaskResult.objects.order_by("-date_created")[:10]
for r in results:
    print(f"{r.task_name}: {r.status} - {r.result}")
```

### How do I clear old results?

```bash
# Clear results older than 7 days
python manage.py clear_stale_results

# Clear results older than 24 hours
python manage.py clear_stale_results --since 86400

# Skip confirmation
python manage.py clear_stale_results --no-input
```

### Why is my scheduled task not running?

1. Verify schedule is active: `schedule.is_active = True`
2. Check cron syntax at [crontab.guru](https://crontab.guru)
3. List schedules: `python manage.py task_schedules --list`
4. Check Upstash Console for schedule status

### How do I handle long-running tasks?

Configure appropriate timeouts:
```python
# For scheduled tasks
TaskSchedule.objects.create(
    name="Long Task",
    task="myapp.tasks.long_task",
    cron="0 0 * * *",
    timeout="300s",  # 5 minutes
)
```

Note: QStash has maximum timeout limits based on your Upstash plan.

### How do I migrate from Celery?

1. Replace imports:
   ```python
   # Before
   from celery import shared_task

   # After
   from django_qstash import shared_task
   ```

2. Ensure arguments are JSON-serializable (no Django models)

3. Remove Celery-specific options (bind, queue, etc.)

4. Test each task thoroughly

---

## Getting Help

If you're still having issues:

1. **Check the [GitHub Issues](https://github.com/codingforentrepreneurs/django-qstash/issues)** for similar problems

2. **Enable debug logging** and review the output

3. **Create a minimal reproduction** of the issue

4. **Open a new issue** with:
   - django-qstash version
   - Django version
   - Python version
   - Error message and traceback
   - Steps to reproduce

---

## Related Documentation

- [Getting Started](getting-started.md) - Initial setup
- [Configuration](configuration.md) - Settings reference
- [API Reference](api-reference.md) - Detailed API docs
- [Security](security.md) - Security guide
