> :warning: **BETA Software**: Working on being production-ready soon.

# django-qstash

_django-qstash_ is a drop-in replacement for Celery's `shared_task`.

To do this, we use:

- [Upstash QStash](https://upstash.com/docs/qstash/overall/getstarted)
- A single public _webhook_ to call `@shared_task` functions automatically

This allows us to:

- Focus just on Django
- Drop Celery
- Truly scale Django to zero
- Run background tasks through webhooks
- Cut costs
- Trigger GitHub Actions Workflows or GitLab CI/CD pipelines for handling other kinds of background tasks based on our project's code.


## Table of Contents

- [django-qstash](#django-qstash)
  - [Table of Contents](#table-of-contents)
  - [Installation](#installation)
    - [Using Pip](#using-pip)
    - [Update Settings (`settings.py`)](#update-settings-settingspy)
    - [Configure Webhook URL](#configure-webhook-url)
    - [Required Environment Variables](#required-environment-variables)
  - [Sample Project](#sample-project)
  - [Dependencies](#dependencies)
  - [Usage](#usage)
    - [Define a Task](#define-a-task)
    - [Regular Task Call](#regular-task-call)
    - [Async Task](#async-task)
      - [`.delay()`](#delay)
      - [`.apply_async()`](#apply_async)
      - [`.apply_async()` With Time Delay](#apply_async-with-time-delay)
    - [JSON-ready Arguments](#json-ready-arguments)
    - [Example Task](#example-task)
  - [Management Commands](#management-commands)
  - [Development Usage](#development-usage)
  - [Django Settings Configuration](#django-settings-configuration)
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
- `django_qstash` Includes the `@shared_task` decorator and webhook view
- `django_qstash.results` (Optional): Store task results in Django DB
- `django_qstash.schedules` (Optional): Use QStash Schedules to run your `django_qstash` tasks. Out of the box support for _django_qstash_ `@shared_task`. Schedule tasks using _cron_ (e.g. `0 0 * * *`) format which is required based on [QStash Schedules](https://upstash.com/docs/qstash/features/schedules). use [contrab.guru](https://crontab.guru/) for writing the cron format.

### Configure Webhook URL

In your `ROOT_URLCONF` (e.g. `urls.py`), add the following:
```python
from django_qstash.views import qstash_webhook_view

urlpatterns = [
    # ...
    path("qstash/webhook/", qstash_webhook_view),
    # ...
]
```
Be sure to use this path in your `DJANGO_QSTASH_WEBHOOK_PATH` environment variable.

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
There is a sample project in [sample_project/](sample_project/) that shows how all this is implemented.

## Dependencies

- [Python 3.10+](https://www.python.org/)
- [Django 5+](https://docs.djangoproject.com/)
- [qstash-py](https://github.com/upstash/qstash-py)
- [Upstash](https://upstash.com/) account

## Usage

Django-QStash revolves around the `shared_task` decorator. The goal is to be a drop-in replacement for Celery's `shared_task` decorator.

Here's how it works:
- Define a Task
- Call a Task with `.delay()` or `.apply_async()`

### Define a Task
```python
from django_qstash import shared_task


@shared_task
def hello_world(name: str, age: int = None, activity: str = None):
    if age is None:
        print(f"Hello {name}! I see you're {activity}.")
        return
    print(f"Hello {name}! I see you're {activity} at {age} years old.")
```

### Regular Task Call
Nothing special here. Just call the function like any other to verify it works.

```python
# normal function call
hello_world("Tony Stark", age=40, activity="building in a cave with a box of scraps.")
```

### Async Task

Using `.delay()` or `.apply_async()` is how you call an async task. This is modeled after Celery and it works as you'd expect.


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

### JSON-ready Arguments

Each argument needs to be _JSON_ serializable. The way you find out:

```python
import json

data = {
    "args": ("Tony Stark",),
    "kwargs": {"activity": "building in a cave with a box of scraps."},
}
print(json.dumps(data))
# no errors, you're good to go.
```

### Example Task

```python
# from celery import shared_task
from django_qstash import shared_task


@shared_task
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

- `python manage.py available_tasks` to view all available tasks

_Requires `django_qstash.schedules` installed._
- `python manage.py task_schedules --list` see all schedules relate to the `DJANGO_QSTASH_DOMAIN`
- `python manage.py task_schedules --sync` sync schedules based on the `DJANGO_QSTASH_DOMAIN` to store in the Django Admin.

## Development Usage

django-qstash requires a public domain to work (e.g. `https://djangoqstash.com`). There are many ways to do this, we recommend:

- [Cloudflare Tunnels](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) with a domain name you control.
- [ngrok](https://ngrok.com/)

Once you have a domain name, you can configure the `DJANGO_QSTASH_DOMAIN` setting in your Django settings.


## Django Settings Configuration

In Django settings, you can configure the following:

- `DJANGO_QSTASH_DOMAIN`: Must be a valid and publicly accessible domain. For example `https://djangoqstash.com`. Review [Development usage](#development-usage) for setting up a domain name during development.

- `DJANGO_QSTASH_WEBHOOK_PATH` (default:`/qstash/webhook/`): The path where QStash will send webhooks to your Django application.

- `DJANGO_QSTASH_FORCE_HTTPS` (default:`True`): Whether to force HTTPS for the webhook.

- `DJANGO_QSTASH_RESULT_TTL` (default:`604800`): A number of seconds after which task result data can be safely deleted. Defaults to 604800 seconds (7 days or 7 * 24 * 60 * 60).


## Schedule Tasks (Optional)

The `django_qstash.schedules` app schedules tasks using Upstash [QStash Schedules](https://upstash.com/docs/qstash/features/schedules) and the django-qstash `@shared_task` decorator.

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


## Schedule a Task

Tasks must exist before you can schedule them. Review [Define a Task](#define-a-task) for more information.

Here's how you can schedule a task:
- Django Admin (`/admin/django_qstash_schedules/taskschedule/add/`)
- Django shell (`python manage.py shell`)




```python
from django_qstash.schedules.models import TaskSchedule
from django_qstash.discovery.utils import discover_tasks

all_available_tasks = discover_tasks(paths_only=True)

desired_task = "django_qstash.results.clear_stale_results_task"
# or desired_task = "example_app.tasks.my_task"

task_to_use = desired_task
if desired_task not in available_task_locations:
    task_to_use = available_task_locations[0]

print(f"Using task: {task_to_use}")

TaskSchedule.objects.create(
    name="My Schedule",
    cron="0 0 * * *",
    task_name=task_to_use,
    args=["arg1", "arg2"],
    kwargs={"kwarg1": "value1", "kwarg2": "value2"},
)
```
- `django_qstash.results.clear_stale_results_task` is a built-in task that `django_qstash.results` provides
- `args` and `kwargs` are the arguments to pass to the task
- `cron` is the cron schedule to run the task. Use [contrab.guru](https://crontab.guru/) for writing the cron format.



## Store Task Results (Optional)

In `django_qstash.results.models` we have the `TaskResult` model class that can be used to track async task results. These entries are created via webhooks.

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

Let's face it. Celery is a powerful tool to run async background tasks but it comes at a cost. It needs at least one server running 24/7. For best performance it needs 2 (one worker, one beat). It also needs Redis or RabbitMQ. Most background processes that are tied to web apps are not serverless; they have to "listen" for their next task.

To make Django truly scale-to-zero and serverless, we need to drop Celery.

Enter __django-qstash__.

django-qstash is designed to be a near drop-in replacement for Celery's `shared_task` decorator.

It works by leveraging Upstash QStash to deliver messages about your tasks (e.g. the function's arguments) via webhooks to your Django application.  In the QStash [docs](https://upstash.com/docs/qstash/overall/getstarted), it is described as:

> QStash is a serverless messaging and scheduling solution. It fits easily into your existing workflow and allows you to build reliable systems without managing infrastructure.
>
> Instead of calling an endpoint directly, QStash acts as a middleman between you and an API to guarantee delivery, perform automatic retries on failure, and more.

django-qstash has a webhook handler that converts a QStash message to run a specific `@shared_task` function (the one that called `.delay()` or `.apply_async()`). It's easy, it's cheap, it's effective, and best of all, it unlocks the scale-to-zero potential of Django as a serverless app.
