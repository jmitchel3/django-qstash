# django-qstash Documentation

Welcome to the official documentation for **django-qstash** - a serverless background task solution for Django using Upstash QStash.

## What is django-qstash?

django-qstash is designed to be a drop-in replacement for Celery's `shared_task` decorator. It enables background task execution in Django applications through webhooks and Upstash QStash, allowing you to build truly serverless Django applications that can scale to zero.

### Key Features

- **Celery-Compatible API**: Use familiar `.delay()` and `.apply_async()` methods
- **No Infrastructure Overhead**: No Redis, RabbitMQ, or worker processes required
- **Scale-to-Zero**: Perfect for serverless deployments
- **Task Scheduling**: Built-in cron-based task scheduling via QStash Schedules
- **Result Storage**: Optional task result persistence in your Django database
- **Automatic Task Discovery**: Tasks are automatically discovered from your Django apps
- **Webhook Security**: Built-in signature verification for secure webhook handling

### How It Works

1. You define tasks using the `@stashed_task` or `@shared_task` decorator
2. When you call `.delay()` or `.apply_async()`, django-qstash sends a message to QStash
3. QStash delivers the message to your Django application's webhook endpoint
4. The webhook handler executes your task function

This architecture eliminates the need for long-running worker processes, making it ideal for serverless and cost-conscious deployments.

## Quick Links

| Document | Description |
|----------|-------------|
| [Getting Started](getting-started.md) | Quick installation and setup guide |
| [Configuration](configuration.md) | Complete settings reference |
| [API Reference](api-reference.md) | Detailed API documentation |
| [Security](security.md) | Security best practices and webhook verification |
| [Deployment](deployment.md) | Production deployment guide |
| [Troubleshooting](troubleshooting.md) | Common issues and solutions |

## Requirements

- Python 3.10+
- Django 5.0+
- [Upstash](https://upstash.com/) account (for QStash credentials)
- A publicly accessible domain for webhook delivery

## Installation

```bash
pip install django-qstash
```

See the [Getting Started](getting-started.md) guide for complete installation instructions.

## Basic Example

```python
# myapp/tasks.py
from django_qstash import stashed_task


@stashed_task
def send_welcome_email(user_id: int, email: str):
    """Send a welcome email to a new user."""
    # Your email sending logic here
    print(f"Sending welcome email to {email}")


# Trigger the task
send_welcome_email.delay(user_id=123, email="user@example.com")
```

## Optional Features

### Task Scheduling

Schedule tasks to run on a cron schedule using the `django_qstash.schedules` app:

```python
INSTALLED_APPS = [
    # ...
    "django_qstash",
    "django_qstash.schedules",  # Enable scheduling
]
```

See [API Reference - TaskSchedule](api-reference.md#taskschedule-model) for details.

### Task Result Storage

Store task execution results in your database using the `django_qstash.results` app:

```python
INSTALLED_APPS = [
    # ...
    "django_qstash",
    "django_qstash.results",  # Enable result storage
]
```

See [API Reference - TaskResult](api-reference.md#taskresult-model) for details.

## Why django-qstash?

### vs. Celery

| Aspect | Celery | django-qstash |
|--------|--------|---------------|
| Infrastructure | Requires Redis/RabbitMQ + worker processes | No additional infrastructure |
| Scaling | Manual worker scaling | Automatic with serverless |
| Cost | Always-on workers | Pay-per-use |
| Complexity | Complex setup | Simple configuration |
| Serverless | Not compatible | Native support |

### Use Cases

- **Serverless Django**: Deploy on platforms like Railway, Render, or AWS Lambda
- **Side Projects**: Cost-effective background tasks without infrastructure overhead
- **Microservices**: Lightweight task processing for distributed systems
- **Scale-to-Zero**: Applications with variable or low traffic

## Resources

- [GitHub Repository](https://github.com/codingforentrepreneurs/django-qstash)
- [PyPI Package](https://pypi.org/project/django-qstash/)
- [Upstash QStash Documentation](https://upstash.com/docs/qstash/overall/getstarted)
- [Video Tutorial Playlist](https://www.youtube.com/playlist?list=PLEsfXFp6DpzQgNC8Q_ijgqxCVRtSC4_-L)

## Support

- Open an issue on [GitHub](https://github.com/codingforentrepreneurs/django-qstash/issues)
- Check the [Troubleshooting Guide](troubleshooting.md)

## License

django-qstash is open source software. See the repository for license details.
