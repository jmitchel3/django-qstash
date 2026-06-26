# django-qstash

Run background tasks with Django through webhooks and Upstash QStash.

_django-qstash_ is designed to be a drop-in replacement for Celery's `shared_task` or run alongside Celery.


## How it works

In `tasks.py` in your apps:

```python
from django_qstash import shared_task


@shared_task
def my_task():
    pass
```
> To use django-qstash with Celery, you can use `@stashed_task` instead of `@shared_task` (more below).

To do this we need:

- [Upstash QStash](https://upstash.com/docs/qstash/overall/getstarted)
- A single public _webhook_ to call `@stashed_task` functions automatically

This allows us to:

- Nearly identical usage to Celery's `@shared_task` with far less configuration and overhead
- Focus just on Django
- Drop Celery completely, scale it down, or use it as normal. django-qstash can work hand-in-hand with Celery
- Unlock true serverless and scale-to-zero for Django
- Run background tasks through webhooks
- Cut costs
- Trigger GitHub Actions Workflows or GitLab CI/CD pipelines for handling other kinds of background tasks based on our project's code.


## Demo


### Django QStash in 3 Minutes on YouTube

[![Django QStash Demo in 3 Minutes](https://img.youtube.com/vi/e-hloBp4eVQ/0.jpg)](https://www.youtube.com/watch?v=e-hloBp4eVQ)


### Mini Course on YouTube

Step-by-Step [tutorial playlist on YouTube](https://www.youtube.com/playlist?list=PLEsfXFp6DpzQgNC8Q_ijgqxCVRtSC4_-L) on my [@CodingEntrepreneurs](https://cfe.sh/youtube) Youtube channel.

## Table of Contents

- [django-qstash](#django-qstash)
  - [How it works](#how-it-works)
  - [Demo](#demo)
    - [Django QStash in 3 Minutes on YouTube](#django-qstash-in-3-minutes-on-youtube)
    - [Mini Course on YouTube](#mini-course-on-youtube)
  - [Table of Contents](#table-of-contents)
  - [Installation](#installation)
    - [Using Pip](#using-pip)
    - [Update Settings (`settings.py`)](#update-settings-settingspy)
    - [Configure QStash Webhook Handler](#configure-qstash-webhook-handler)
    - [Required Environment Variables](#required-environment-variables)
  - [Sample Project](#sample-project)
  - [Dependencies](#dependencies)
  - [Usage](#usage)
    - [Define a Task](#define-a-task)
    - [Regular Task Call](#regular-task-call)
    - [Background Task](#background-task)
      - [`.delay()`](#delay)
      - [`.apply_async()`](#apply_async)
      - [`.apply_async()` With Time Delay](#apply_async-with-time-delay)
    - [Arguments Must be JSON-ready](#arguments-must-be-json-ready)
    - [Example Task](#example-task)
  - [Management Commands](#management-commands)
  - [Development](#development)
    - [Development with a Public Domain](#development-with-a-public-domain)
    - [Development with Docker Compose](#development-with-docker-compose)
  - [Django Settings Configuration](#django-settings-configuration)
    - [`DJANGO_QSTASH_DOMAIN`](#django_qstash_domain)
    - [`DJANGO_QSTASH_WEBHOOK_PATH`](#django_qstash_webhook_path)
    - [`DJANGO_QSTASH_FORCE_HTTPS`](#django_qstash_force_https)
    - [Example Django Settings](#example-django-settings)
  - [Schedule Tasks (Optional)](#schedule-tasks-optional)
    - [Installation](#installation-1)
    - [Schedule a Task](#schedule-a-task)
  - [Store Task Results (Optional)](#store-task-results-optional)
    - [Clear Stale Results](#clear-stale-results)
  - [Definitions](#definitions)
  - [Motivation](#motivation)


## Installation

### Using Pip
```bash
pip install django-qstash
```

### Update Settings (`settings.py`)

```python
INSTALLED_APPS = [
    ##...
    "django_qstash",
    "django_qstash.results",
    "django_qstash.schedules",
    ##...
]
```
- `django_qstash` Includes the `@shared_task` and `@stashed_task` decorators and webhook view
- `django_qstash.results` (Optional): Store task results in Django DB
- `django_qstash.schedules` (Optional): Use QStash Schedules to run your `django_qstash` tasks. Out of the box support for _django_qstash_ `@stashed_task`. Schedule tasks using _cron_ (e.g. `0 0 * * *`) format which is required based on [QStash Schedules](https://upstash.com/docs/qstash/features/schedules). use [contrab.guru](https://crontab.guru/) for writing the cron format.

### Configure QStash Webhook Handler

Set it and forget it. `django_qstash` will handle the webhook from qstash automatically for you.

In your `ROOT_URLCONF` (e.g. `urls.py`), add the following:

```python
from django.urls import include

urlpatterns = [
    # ...
    path("qstash/webhook/", include("django_qstash.urls")),
    # ...
]
```
Be sure to use this path in your `DJANGO_QSTASH_WEBHOOK_PATH` environment variable.


The `django_qstash` webhook handler runs your `@shared_task` or `@stashed_task` functions via the `importlib` module. In other words, you should not need to modify the webhook handler.

```mermaid
sequenceDiagram
    participant App as Django code
    participant Q as Upstash QStash
    participant Webhook as /qstash/webhook/
    participant Task as Task function

    App->>Q: my_task.delay(args) publishes JSON payload
    Q->>Webhook: POST signed JSON webhook
    Webhook->>Webhook: Verify signature and validate payload
    Webhook->>Task: Import module.function and call with args
    Task-->>Webhook: Return result or raise error
    Webhook-->>Q: HTTP response controls retry behavior
```


### Required Environment Variables

Get your QStash token and signing keys from [Upstash](https://upstash.com/).

```python
QSTASH_TOKEN = "your_token"
QSTASH_CURRENT_SIGNING_KEY = "your_current_signing_key"
QSTASH_NEXT_SIGNING_KEY = "your_next_signing_key"

# required for django-qstash
DJANGO_QSTASH_DOMAIN = "https://example.com"
DJANGO_QSTASH_WEBHOOK_PATH = "/qstash/webhook/"
```
> Review [.env.sample](.env.sample) to see all the environment variables you need to set.


## Sample Project
There is a sample project in [sample_project/](sample_project/) that shows how all this is implemented. It runs **fully locally** — including the task round-trip — with a single command:

```bash
docker compose -f compose.dev.yaml up --build
```

See [sample_project/README.md](sample_project/README.md) for the full walkthrough (and a host-Django alternative).

## Dependencies

- [Python 3.10+](https://www.python.org/)
- [Django 5+](https://docs.djangoproject.com/)
- [qstash-py](https://github.com/upstash/qstash-py)
- [Upstash](https://upstash.com/) account

## Usage

Django-QStash revolves around the `stashed_task` decorator. The goal is to be a drop-in replacement for Celery's `shared_task` decorator.

Here's how it works:
- Define a Task
- Call a Task with `.delay()` or `.apply_async()`

### Define a Task
```python
# from celery import shared_task
from django_qstash import shared_task
from django_qstash import stashed_task


@stashed_task
def hello_world(name: str, age: int = None, activity: str = None):
    if age is None:
        print(f"Hello {name}! I see you're {activity}.")
        return
    print(f"Hello {name}! I see you're {activity} at {age} years old.")


@shared_task
def hello_world_redux(name: str, age: int = None, activity: str = None):
    if age is None:
        print(f"Hello {name}! I see you're {activity}.")
        return
    print(f"Hello {name}! I see you're {activity} at {age} years old.")
```

- `hello_world` and `hello_world_redux` work the same with django-qstash.
- If you use Celery's `@shared_task` instead, Celery would handle only `hello_world_redux` and django-qstash would handle only `hello_world`.

### Regular Task Call
Nothing special here. Just call the function like any other to verify it works.

```python
# normal function call
hello_world("Tony Stark", age=40, activity="building in a cave with a box of scraps.")
```

### Background Task

Using `.delay()` or `.apply_async()` is how you trigger a background task. These background tasks are actually setting up a QStash message that will be delivered via webhook to your Django application. django-qstash handles the webhook and the message delivery assuming installed correctly.

This functionality is modeled after Celery and it works as you'd expect.


#### `.delay()`
```python
hello_world.delay(
    "Tony Stark", age=40, activity="building in a cave with a box of scraps."
)
```

#### `.apply_async()`
```python
hello_world.apply_async(
    args=("Tony Stark",),
    kwargs={"activity": "building in a cave with a box of scraps."},
)
```

#### `.apply_async()` With Time Delay

Just use the `countdown` parameter to delay the task by N seconds. (always in seconds): `.apply_async(*args, **kwargs, countdown=N)`


```python
# async task delayed 35 seconds
delay_35_seconds = 35
hello_world.apply_async(
    args=("Tony Stark",),
    kwargs={"activity": "building in a cave with a box of scraps."},
    countdown=delay_35_seconds,
)
```

### Arguments Must be JSON-ready

Arguments to django-qstash managed functions must be _JSON_ serializable.

The way you find out:
```python
import json

data = {
    "args": ("Tony Stark",),
    "kwargs": {"activity": "building in a cave with a box of scraps."},
}
print(json.dumps(data))
# no errors, you're good to go.
```
If you have `errors` you'll need to fix them. Here's a few common errors you might see:

- Using a Django queryset directly as an argument
- Using a Django model instance directly as an argument
- Using a datetime object directly as an argument (e.g. `datetime.datetime` or `datetime.date`) instead of a timestamp or date string (e.g. `datetime.datetime.now().timestamp()` or `datetime.datetime.now.strftime("%Y-%m-%d")`)

### Example Task

```python
# from celery import shared_task
# becomes
# from django_qstash import shared_task
# or
from django_qstash import stashed_task


@stashed_task
def math_add_task(a, b, save_to_file=False, *args, **kwargs):
    logger.info(f"Adding {a} and {b}")
    if save_to_file:
        with open("math-add-result.txt", "w") as f:
            f.write(f"{a} + {b} = {a + b}")
    return a + b
```


Calling:
```python
math_add_task.apply_async(args=(12, 454), save_to_file=True)
```
is the same as
```python
math_add_task.delay(12, 454, save_to_file=True)
```

But if you need to delay the task, use `.apply_async()` with the `countdown` parameter.

```python
five_hours = 5 * 60 * 60
math_add_task.apply_async(
    args=(12, 454), kwargs={"save_to_file": True}, countdown=five_hours
)
```

The `.delay()` method does not support a countdown parameter because it simply passes the arguments (*args, **kwargs) to the `apply_async()` method.


## Management Commands

- `python manage.py available_tasks` to view all available tasks found by django-qstash. Unlike Celery, django-qstash does not assign tasks to a specific Celery app (e.g. `app = Celery()`).

_Requires `django_qstash.schedules` installed._
- `python manage.py task_schedules --list` see all schedules relate to the `DJANGO_QSTASH_DOMAIN`
- `python manage.py task_schedules --sync` sync schedules based on the `DJANGO_QSTASH_DOMAIN` to store in the Django Admin.

QStash dead letter queue:
- `python manage.py qstash_dlq --list` list exhausted QStash messages
- `python manage.py qstash_dlq --get <dlq_id>` inspect one DLQ message
- `python manage.py qstash_dlq --delete <dlq_id>` delete one DLQ message
- `python manage.py qstash_dlq --list --queue emails --label scheduled,email` filter DLQ messages

## Development

During development, you have two options:

- Use Upstash.com with a publicly accessible domain (preferred)
- Use Docker Compose with [compose.dev.yaml](./compose.dev.yaml)

### Development with a Public Domain

The closer your development environment is to production the better. For that reason, using a publicly accessible domain is the preferred with to develop with _django-qstash_.

To get a public domain during development, we recommend any of the following:

- [Cloudflare Tunnels](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) with a domain name you control.
- [ngrok](https://ngrok.com/)

Once you have a domain name, you can configure the `DJANGO_QSTASH_DOMAIN` setting in your Django settings.

### Development with Docker Compose
Upstash covers how to run QStash during development on [this guide](https://upstash.com/docs/qstash/howto/local-development). [compose.dev.yaml](./compose.dev.yaml) runs the QStash dev server (and, optionally, the sample Django app) entirely locally — no public domain or Upstash account required.

The QStash dev server runs in Docker and **calls back into your Django app** to execute tasks, so two things matter locally:

- `DJANGO_QSTASH_DOMAIN` must be reachable *from the container*. Run Django on `0.0.0.0` and point the domain at `http://host.docker.internal:8000`.
- `DJANGO_QSTASH_FORCE_HTTPS=False`, so the plain-http callback verifies.

To wire it up:

- `docker compose -f compose.dev.yaml up qstash` — start just the dev server.
- Add `QSTASH_URL=http://127.0.0.1:8585` to your `.env` file.
- Use the `QSTASH_TOKEN`, `QSTASH_CURRENT_SIGNING_KEY`, and `QSTASH_NEXT_SIGNING_KEY` from the Docker compose terminal output _or_ the values listed in [compose.dev.yaml](./compose.dev.yaml).

The [sample project](sample_project/README.md) ships a ready-to-run `.env.sample` plus a `qstash_smoke_test` management command that enqueues a task and waits for the webhook result — a one-command way to confirm your local setup round-trips end to end. You can also bring up the whole stack (Django + QStash) at once with `docker compose -f compose.dev.yaml up --build`.

## Django Settings Configuration

Various options are available to configure django-qstash.

### `DJANGO_QSTASH_DOMAIN`
- Required: Yes
- Default:`None`
- Description: Must be a valid and publicly accessible domain. For example `https://djangoqstash.com`. Review [Development usage](#development-usage) for setting up a domain name during development.

### `DJANGO_QSTASH_WEBHOOK_PATH`
- Required: Yes
- Default:`/qstash/webhook/`
- Description: The path where QStash will send webhooks to your Django application.

### `DJANGO_QSTASH_FORCE_HTTPS`
- Required: No
- Default: `True`
- Description: Whether to force HTTPS for the webhook.

###`DJANGO_QSTASH_RESULT_TTL`
- Required: No
- Default:`604800`
- Description: A number of seconds after which task result data can be safely deleted. Defaults to 604800 seconds (7 days or 7 * 24 * 60 * 60).


### Example Django Settings

For a complete example, review [sample_project/cfehome/settings.py](sample_project/cfehome/settings.py) where [python-decouple](https://github.com/henriquebastos/python-decouple) is used to set the environment variables via the `.env` file or system environment variables (for production use).

Using `os.environ`:
```python
import os

###########################
# django settings
###########################
DJANGO_DEBUG = str(os.environ.get("DJANGO_DEBUG")) == "1"
DJANGO_SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = [os.environ.get("ALLOWED_HOST")]
CSRF_TRUSTED_ORIGINS = [os.environ.get("CSRF_TRUSTED_ORIGIN")]
###########################
# qstash-py settings
###########################
USE_LOCAL_QSTASH = str(os.environ.get("USE_LOCAL_QSTASH")) == "1"
QSTASH_TOKEN = os.environ.get("QSTASH_TOKEN")
QSTASH_CURRENT_SIGNING_KEY = os.environ.get("QSTASH_CURRENT_SIGNING_KEY")
QSTASH_NEXT_SIGNING_KEY = os.environ.get("QSTASH_NEXT_SIGNING_KEY")
if DJANGO_DEBUG and USE_LOCAL_QSTASH:
    # connect to the docker compose qstash instance
    os.environ["QSTASH_URL"] = "http://127.0.0.1:8585"
###########################
# django_qstash settings
###########################
DJANGO_QSTASH_DOMAIN = os.environ.get("DJANGO_QSTASH_DOMAIN")
DJANGO_QSTASH_WEBHOOK_PATH = os.environ.get("DJANGO_QSTASH_WEBHOOK_PATH")
DJANGO_QSTASH_FORCE_HTTPS = True
DJANGO_QSTASH_RESULT_TTL = 604800
```


## Schedule Tasks (Optional)

Run background tasks on a CRON schedule.

The `django_qstash.schedules` app schedules tasks using Upstash [QStash Schedules](https://upstash.com/docs/qstash/features/schedules) via `@shared_task` or `@stashed_task` decorators along with the `TaskSchedule` model.

### Installation

Update your `INSTALLED_APPS` setting to include `django_qstash.schedules`.

```python
INSTALLED_APPS = [
    # ...
    "django_qstash",  # required
    "django_qstash.schedules",
    # ...
]
```

Run migrations:
```bash
python manage.py migrate django_qstash_schedules
```

### Schedule a Task

Tasks must exist before you can schedule them. Review [Define a Task](#define-a-task) for more information.

Here's how you can schedule a task:
- Django Admin (`/admin/django_qstash_schedules/taskschedule/add/`)
- Django shell (`python manage.py shell`)

```python
from django_qstash.schedules.models import TaskSchedule
from django_qstash.discovery.utils import discover_tasks

all_available_tasks = discover_tasks(locations_only=True)

desired_task = "django_qstash.results.tasks.clear_stale_results_task"
# or desired_task = "example_app.tasks.my_task"

task_to_use = desired_task
if desired_task not in all_available_tasks:
    task_to_use = all_available_tasks[0]

print(f"Using task: {task_to_use}")

TaskSchedule.objects.create(
    name="My Schedule",
    cron="0 0 * * *",
    task=task_to_use,
    args=["arg1", "arg2"],
    kwargs={"kwarg1": "value1", "kwarg2": "value2"},
)
```
- `django_qstash.results.tasks.clear_stale_results_task` is a built-in task that `django_qstash.results` provides
- Use the `task` field for the dotted Python path of the decorated task. You can also pass an imported `@shared_task`/`@stashed_task` object to `task`. `task_name` is managed by django-qstash and mirrors the selected task path.
- `args` and `kwargs` are the arguments to pass to the task
- `cron` is the cron schedule to run the task. Use [crontab.guru](https://crontab.guru/) for writing the cron format. QStash timezone prefixes are supported, e.g. `CRON_TZ=America/New_York 0 4 * * *`.

Scheduled tasks can use QStash delivery controls for retries, callbacks, queues, flow control, labels, headers, and redaction:

```python
TaskSchedule.objects.create(
    name="Daily Email Digest",
    task="example_app.tasks.send_daily_digest",
    cron="CRON_TZ=America/New_York 0 7 * * *",
    retries=5,
    retry_delay="1000 * (1 + retried)",
    timeout="120s",
    queue="emails",
    label="scheduled,email",
    headers={"X-Trace-Source": "daily-digest"},
    failure_callback="https://example.com/qstash/failure/",
    flow_control={"key": "daily-digest", "rate": 10, "period": "1m"},
    redact={"body": True},
)
```


## Store Task Results (Optional)

Retain the results of background tasks in the database with clear-out functionality.

In `django_qstash.results.models` we have the `TaskResult` model class that can be used to track async task results. These entries are created via the django-qstash webhook view handler (`qstash_webhook_view`).

To install it, just add `django_qstash.results` to your `INSTALLED_APPS` setting.

```python
INSTALLED_APPS = [
    # ...
    "django_qstash",
    "django_qstash.results",
    # ...
]
```

Run migrations:
```bash
python manage.py migrate django_qstash_results
```

Key configuration:

- [DJANGO_QSTASH_WEBHOOK_PATH](#django-settings-configuration)
- [DJANGO_QSTASH_DOMAIN](#django-settings-configuration)
- [DJANGO_QSTASH_RESULT_TTL](#django-settings-configuration)

### Clear Stale Results

We recommend purging the `TaskResult` model after a certain amount of time.
```bash
python manage.py clear_stale_results --since 604800
```
Args:
- `--since` is the number of seconds ago to clear results for. Defaults to 604800 seconds (7 days or the `DJANGO_QSTASH_RESULT_TTL` setting).
- `--no-input` is a flag to skip the confirmation prompt to delete the results.



## Definitions

- **Background Task**: A function or task that is not part of the request/response cycle.
  - Examples include as sending an email, running a report, or updating a database.
  - Pro: Background tasks can drastically improve the end-user experience since they can move on with their day while the task runs in the background.
  - Con: Processes that run background tasks (like Celery) typically have to run 24/7.
- **Scale-to-Zero**: Depending on the amount of traffic, Django can be effectively turned off. If done right, when more traffic comes in, Django can be turned back on very quickly.
- **Serverless**: A cloud computing model where code runs without server management, with scaling and billing tied to usage. Often used interchangeably with "scale-to-zero".


## Motivation

TLDR - Celery cannot be serverless. I want serverless "Celery" so I only pay for the apps that have attention and traffic. Upstash created QStash to help solve the problem of message queues in a serverless environment. django-qstash is the goldilocks that combines the functionality of Celery with the functionality of QStash all to unlock fully serverless Django.

I run a lot of side projects with Django. Some as demos for tutorials based on my work at [@codingforentrepreneurs](https://cfe.sh/github) and some are new businesses that haven't found much traction yet.

Most web apps can benefit from async background tasks such as sending emails, running reports, or updating databases.

But how?

Traditionally, I'd reach for Celery but that can get expensive really quick. Running a lot of Django projects can add up too -- "death by a thousand cuts" if you will. A server for Django, for celery worker, for celery beat scheduler, and so on. It adds up fast.

I think serverless is the answer. Pay for what you use and scale to zero when you don't need it and scale up when you do -- all automated.

Django can be serverless and is pretty easy to do thanks to Docker and the countless hosting options and services out there. Celery cannot be serverless, at least yet.

Let's face it. Celery is a powerful tool to run async background tasks but it comes at a cost. It needs at least one server running 24/7. For best performance, it needs 2 (one worker, one beat). It also needs Redis or RabbitMQ. In a traditional Django setup with Celery and Redis, you need to run 3 to 4 different processes. Most background processes that are tied to web apps are not serverless; they have to "listen" for their next task.

To make Django truly scale-to-zero and serverless, we need to drop Celery.

Enter __django-qstash__.

django-qstash is designed to be a near drop-in replacement for Celery's `shared_task` decorator.

It works by leveraging Upstash QStash to deliver messages about your tasks (e.g. the function's arguments) via webhooks to your Django application.  In the QStash [docs](https://upstash.com/docs/qstash/overall/getstarted), it is described as:

> QStash is a serverless messaging and scheduling solution. It fits easily into your existing workflow and allows you to build reliable systems without managing infrastructure.
>
> Instead of calling an endpoint directly, QStash acts as a middleman between you and an API to guarantee delivery, perform automatic retries on failure, and more.

Compared to a traditional setup with Django, Celery, and Redis, which requires 3 to 4 processes, you only need to run a single process and can delegate the rest to Upstash QStash, significantly simplifying your infrastructure.

django-qstash has a webhook handler that converts a QStash message to run a specific `@shared_task` function (the one that called `.delay()` or `.apply_async()`). It's easy, it's cheap, it's effective, and best of all, it unlocks the scale-to-zero potential of Django as a serverless app.
