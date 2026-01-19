# Getting Started

This guide will help you set up django-qstash in your Django project in just a few minutes.

## Prerequisites

Before you begin, ensure you have:

- Python 3.10 or higher
- Django 5.0 or higher
- An [Upstash](https://upstash.com/) account (free tier available)
- A publicly accessible domain (for production) or a tunneling solution (for development)

## Step 1: Install django-qstash

Install the package using pip:

```bash
pip install django-qstash
```

## Step 2: Get Upstash QStash Credentials

1. Sign up or log in to [Upstash Console](https://console.upstash.com/)
2. Navigate to the QStash section
3. Copy your credentials:
   - `QSTASH_TOKEN`
   - `QSTASH_CURRENT_SIGNING_KEY`
   - `QSTASH_NEXT_SIGNING_KEY`

## Step 3: Configure Django Settings

Add django-qstash to your `INSTALLED_APPS`:

```python
# settings.py

INSTALLED_APPS = [
    # Django apps...
    "django.contrib.admin",
    "django.contrib.auth",
    # ...
    # django-qstash (required)
    "django_qstash",
    # Optional: Store task results in database
    "django_qstash.results",
    # Optional: Schedule tasks with cron expressions
    "django_qstash.schedules",
]
```

Add the required settings:

```python
# settings.py
import os

# QStash credentials (from Upstash Console)
QSTASH_TOKEN = os.environ.get("QSTASH_TOKEN")
QSTASH_CURRENT_SIGNING_KEY = os.environ.get("QSTASH_CURRENT_SIGNING_KEY")
QSTASH_NEXT_SIGNING_KEY = os.environ.get("QSTASH_NEXT_SIGNING_KEY")

# django-qstash settings
DJANGO_QSTASH_DOMAIN = os.environ.get(
    "DJANGO_QSTASH_DOMAIN"
)  # e.g., "https://example.com"
DJANGO_QSTASH_WEBHOOK_PATH = "/qstash/webhook/"  # Default path
DJANGO_QSTASH_FORCE_HTTPS = True  # Recommended for production
```

## Step 4: Configure URL Routing

Add the webhook URL to your URL configuration:

```python
# urls.py
from django.urls import path, include

urlpatterns = [
    # Your other URLs...
    path("qstash/webhook/", include("django_qstash.urls")),
]
```

> **Important**: The path must match your `DJANGO_QSTASH_WEBHOOK_PATH` setting.

## Step 5: Set Environment Variables

Create a `.env` file or set environment variables:

```bash
# .env
QSTASH_TOKEN=your_qstash_token
QSTASH_CURRENT_SIGNING_KEY=your_current_signing_key
QSTASH_NEXT_SIGNING_KEY=your_next_signing_key
DJANGO_QSTASH_DOMAIN=https://your-domain.com
DJANGO_QSTASH_WEBHOOK_PATH=/qstash/webhook/
```

## Step 6: Run Migrations (Optional Features)

If you enabled `django_qstash.results` or `django_qstash.schedules`:

```bash
# For task results storage
python manage.py migrate django_qstash_results

# For task scheduling
python manage.py migrate django_qstash_schedules
```

## Step 7: Create Your First Task

Create a `tasks.py` file in any Django app:

```python
# myapp/tasks.py
from django_qstash import stashed_task


@stashed_task
def hello_world(name: str):
    """A simple task that prints a greeting."""
    print(f"Hello, {name}!")
    return f"Greeted {name}"


@stashed_task
def send_notification(user_id: int, message: str):
    """Send a notification to a user."""
    # Your notification logic here
    print(f"Sending to user {user_id}: {message}")
    return {"user_id": user_id, "status": "sent"}
```

## Step 8: Trigger Your Task

You can trigger tasks in several ways:

### Using `.delay()`

```python
# In a view, management command, or anywhere in your code
from myapp.tasks import hello_world, send_notification

# Simple call
hello_world.delay("World")

# With keyword arguments
send_notification.delay(user_id=123, message="Welcome!")
```

### Using `.apply_async()`

```python
# With explicit args and kwargs
send_notification.apply_async(args=(123,), kwargs={"message": "Welcome!"})

# With a delay (countdown in seconds)
send_notification.apply_async(
    args=(123,), kwargs={"message": "Reminder!"}, countdown=3600  # Execute in 1 hour
)
```

### Direct Execution (No Background)

```python
# Execute immediately (not via QStash)
result = hello_world("World")
print(result)  # "Greeted World"
```

## Step 9: Verify Your Setup

### List Available Tasks

```bash
python manage.py available_tasks
```

This should display your registered tasks:

```
Available tasks:
  Name: hello_world
  Location: myapp.tasks.hello_world
  Field Label: myapp.tasks.hello_world

  Name: send_notification
  Location: myapp.tasks.send_notification
  Field Label: myapp.tasks.send_notification
```

### Test Task Execution

1. Start your Django development server:
   ```bash
   python manage.py runserver
   ```

2. If developing locally, set up a tunnel (see [Development Setup](#development-setup))

3. Trigger a task from the Django shell:
   ```bash
   python manage.py shell
   ```
   ```python
   from myapp.tasks import hello_world

   result = hello_world.delay("Test")
   print(f"Task ID: {result.task_id}")
   ```

4. Check your Django logs for the task execution output

## Development Setup

During development, you need QStash to reach your local server. You have two options:

### Option 1: Public Tunnel (Recommended)

Use a tunneling service to expose your local server:

#### Using ngrok

```bash
# Install ngrok
brew install ngrok  # or download from ngrok.com

# Start your Django server
python manage.py runserver

# In another terminal, start ngrok
ngrok http 8000
```

Copy the HTTPS URL (e.g., `https://abc123.ngrok.io`) and set it as `DJANGO_QSTASH_DOMAIN`.

#### Using Cloudflare Tunnels

```bash
# Install cloudflared
brew install cloudflared

# Start tunnel
cloudflared tunnel --url http://localhost:8000
```

### Option 2: Local QStash (Docker)

For fully offline development, you can run a local QStash instance:

```bash
# Start local QStash using Docker Compose
docker compose -f compose.dev.yaml up
```

Then update your `.env`:

```bash
QSTASH_URL=http://127.0.0.1:8585
# Use the tokens from compose.dev.yaml
QSTASH_TOKEN=local_token
QSTASH_CURRENT_SIGNING_KEY=local_current_key
QSTASH_NEXT_SIGNING_KEY=local_next_key
```

## Next Steps

Now that you have django-qstash set up:

1. **Learn the API**: See [API Reference](api-reference.md) for all available options
2. **Configure Settings**: See [Configuration](configuration.md) for all settings
3. **Set Up Scheduling**: Create recurring tasks with cron expressions
4. **Deploy to Production**: See [Deployment Guide](deployment.md)
5. **Secure Your Webhook**: Review [Security Guide](security.md)

## Common Issues

If tasks are not executing:

1. Verify your domain is publicly accessible
2. Check that signing keys are correct
3. Ensure the webhook path matches your URL configuration
4. Check Django logs for error messages

See [Troubleshooting](troubleshooting.md) for more solutions.

## Example Project

A complete sample project is available in the repository at `sample_project/`. You can use it as a reference for your own implementation.
