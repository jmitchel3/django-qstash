# Configuration Reference

This document provides a complete reference for all django-qstash configuration options.

## Required Settings

These settings must be configured for django-qstash to function.

### QStash Credentials

These credentials are obtained from the [Upstash Console](https://console.upstash.com/).

#### `QSTASH_TOKEN`

- **Type**: `str`
- **Required**: Yes
- **Default**: `None`

Your QStash API token for authenticating requests to the QStash API.

```python
QSTASH_TOKEN = os.environ.get("QSTASH_TOKEN")
```

#### `QSTASH_CURRENT_SIGNING_KEY`

- **Type**: `str`
- **Required**: Yes
- **Default**: `None`

The current signing key used to verify webhook signatures from QStash.

```python
QSTASH_CURRENT_SIGNING_KEY = os.environ.get("QSTASH_CURRENT_SIGNING_KEY")
```

#### `QSTASH_NEXT_SIGNING_KEY`

- **Type**: `str`
- **Required**: Yes
- **Default**: `None`

The next signing key for key rotation. QStash uses two keys to allow seamless key rotation without downtime.

```python
QSTASH_NEXT_SIGNING_KEY = os.environ.get("QSTASH_NEXT_SIGNING_KEY")
```

### django-qstash Settings

#### `DJANGO_QSTASH_DOMAIN`

- **Type**: `str`
- **Required**: Yes
- **Default**: `None`

The publicly accessible domain where your Django application is hosted. QStash will send webhook requests to this domain.

```python
# Production
DJANGO_QSTASH_DOMAIN = "https://myapp.example.com"

# Development with ngrok
DJANGO_QSTASH_DOMAIN = "https://abc123.ngrok.io"

# From environment variable (recommended)
DJANGO_QSTASH_DOMAIN = os.environ.get("DJANGO_QSTASH_DOMAIN")
```

**Important Notes:**
- Must be a valid URL accessible from the internet
- Should include the protocol (`https://`)
- Do not include a trailing slash
- During development, use a tunneling service like ngrok or Cloudflare Tunnels

#### `DJANGO_QSTASH_WEBHOOK_PATH`

- **Type**: `str`
- **Required**: Yes
- **Default**: `"/qstash/webhook/"`

The URL path where QStash will send webhook requests. This must match the path configured in your `urls.py`.

```python
DJANGO_QSTASH_WEBHOOK_PATH = "/qstash/webhook/"
```

**Important Notes:**
- Must include leading and trailing slashes
- Must match your URL configuration exactly:
  ```python
  # urls.py
  path("qstash/webhook/", include("django_qstash.urls"))
  ```

## Optional Settings

### `DJANGO_QSTASH_FORCE_HTTPS`

- **Type**: `bool`
- **Required**: No
- **Default**: `True`

Forces HTTPS protocol when constructing the callback URL for signature verification.

```python
# Recommended for production
DJANGO_QSTASH_FORCE_HTTPS = True

# May be needed for local development
DJANGO_QSTASH_FORCE_HTTPS = False
```

**When to Disable:**
- When using a local QStash instance via Docker
- When your reverse proxy handles SSL termination and passes HTTP to Django

### `DJANGO_QSTASH_RESULT_TTL`

- **Type**: `int`
- **Required**: No
- **Default**: `604800` (7 days)

Time-to-live in seconds for task results. Results older than this value are considered stale and can be cleaned up using the `clear_stale_results` management command.

```python
# Keep results for 7 days (default)
DJANGO_QSTASH_RESULT_TTL = 604800

# Keep results for 24 hours
DJANGO_QSTASH_RESULT_TTL = 86400

# Keep results for 30 days
DJANGO_QSTASH_RESULT_TTL = 2592000
```

**Note**: This setting only applies when `django_qstash.results` is installed.

### `DJANGO_QSTASH_DISCOVER_INCLUDE_SETTINGS_DIR`

- **Type**: `bool`
- **Required**: No
- **Default**: `True`

Whether to include the directory containing `settings.py` when discovering tasks. If `True`, tasks defined in a `tasks.py` file in your settings directory will be discovered.

```python
# Include settings directory in task discovery (default)
DJANGO_QSTASH_DISCOVER_INCLUDE_SETTINGS_DIR = True

# Only discover tasks from installed apps
DJANGO_QSTASH_DISCOVER_INCLUDE_SETTINGS_DIR = False
```

## Environment Variables

### `QSTASH_URL`

- **Type**: `str`
- **Required**: No (Development only)
- **Default**: Upstash production URL

Override the QStash API URL. Only used for local development with a Docker-based QStash instance.

```bash
# .env for local development
QSTASH_URL=http://127.0.0.1:8585
```

**Warning**: This should never be set in production. Using a non-Upstash URL will trigger a runtime warning.

## Complete Configuration Example

Here is a complete example using `python-decouple` for environment variable management:

```python
# settings.py
from decouple import config

# Django settings
DEBUG = config("DJANGO_DEBUG", default=False, cast=bool)
SECRET_KEY = config("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = [config("ALLOWED_HOST")]
CSRF_TRUSTED_ORIGINS = [config("CSRF_TRUSTED_ORIGIN")]

# Installed apps
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # django-qstash
    "django_qstash",
    "django_qstash.results",  # Optional: task results
    "django_qstash.schedules",  # Optional: task scheduling
    # Your apps
    "myapp",
]

# QStash credentials
QSTASH_TOKEN = config("QSTASH_TOKEN")
QSTASH_CURRENT_SIGNING_KEY = config("QSTASH_CURRENT_SIGNING_KEY")
QSTASH_NEXT_SIGNING_KEY = config("QSTASH_NEXT_SIGNING_KEY")

# django-qstash configuration
DJANGO_QSTASH_DOMAIN = config("DJANGO_QSTASH_DOMAIN")
DJANGO_QSTASH_WEBHOOK_PATH = config(
    "DJANGO_QSTASH_WEBHOOK_PATH", default="/qstash/webhook/"
)
DJANGO_QSTASH_FORCE_HTTPS = config("DJANGO_QSTASH_FORCE_HTTPS", default=True, cast=bool)
DJANGO_QSTASH_RESULT_TTL = config("DJANGO_QSTASH_RESULT_TTL", default=604800, cast=int)

# Local development with Docker QStash
USE_LOCAL_QSTASH = config("USE_LOCAL_QSTASH", default=False, cast=bool)
if DEBUG and USE_LOCAL_QSTASH:
    import os

    os.environ["QSTASH_URL"] = "http://127.0.0.1:8585"
```

Corresponding `.env` file:

```bash
# Django
DJANGO_DEBUG=True
DJANGO_SECRET_KEY=your-secret-key-here
ALLOWED_HOST=localhost
CSRF_TRUSTED_ORIGIN=http://localhost:8000

# QStash credentials
QSTASH_TOKEN=your-qstash-token
QSTASH_CURRENT_SIGNING_KEY=your-current-signing-key
QSTASH_NEXT_SIGNING_KEY=your-next-signing-key

# django-qstash
DJANGO_QSTASH_DOMAIN=https://your-domain.ngrok.io
DJANGO_QSTASH_WEBHOOK_PATH=/qstash/webhook/
DJANGO_QSTASH_FORCE_HTTPS=True
DJANGO_QSTASH_RESULT_TTL=604800

# Local development
USE_LOCAL_QSTASH=False
```

## Configuration for Different Environments

### Development

```python
# settings/development.py
import os

DEBUG = True

# QStash credentials (from Upstash or local Docker)
QSTASH_TOKEN = os.environ.get("QSTASH_TOKEN")
QSTASH_CURRENT_SIGNING_KEY = os.environ.get("QSTASH_CURRENT_SIGNING_KEY")
QSTASH_NEXT_SIGNING_KEY = os.environ.get("QSTASH_NEXT_SIGNING_KEY")

# Use ngrok or similar for public URL
DJANGO_QSTASH_DOMAIN = os.environ.get("DJANGO_QSTASH_DOMAIN")
DJANGO_QSTASH_WEBHOOK_PATH = "/qstash/webhook/"

# May need to disable for local testing
DJANGO_QSTASH_FORCE_HTTPS = False
```

### Production

```python
# settings/production.py
import os

DEBUG = False

# QStash credentials
QSTASH_TOKEN = os.environ["QSTASH_TOKEN"]
QSTASH_CURRENT_SIGNING_KEY = os.environ["QSTASH_CURRENT_SIGNING_KEY"]
QSTASH_NEXT_SIGNING_KEY = os.environ["QSTASH_NEXT_SIGNING_KEY"]

# Your production domain
DJANGO_QSTASH_DOMAIN = os.environ["DJANGO_QSTASH_DOMAIN"]
DJANGO_QSTASH_WEBHOOK_PATH = "/qstash/webhook/"

# Always use HTTPS in production
DJANGO_QSTASH_FORCE_HTTPS = True

# Keep results for 30 days
DJANGO_QSTASH_RESULT_TTL = 2592000
```

## Settings Validation

django-qstash will raise warnings or errors for misconfiguration:

### Missing Required Settings

If `QSTASH_TOKEN` or `DJANGO_QSTASH_DOMAIN` is not set:

```
RuntimeWarning: DJANGO_SETTINGS_MODULE (settings.py required) requires
QSTASH_TOKEN and DJANGO_QSTASH_DOMAIN should be set for QStash functionality
```

### Non-Production QStash URL

If `QSTASH_URL` is set to a non-Upstash domain:

```
RuntimeWarning: Using http://127.0.0.1:8585 as your QStash URL.
This configuration should only be used in development.
```

### Task Execution Without Configuration

If you try to execute a task without proper configuration:

```
ImproperlyConfigured: QSTASH_TOKEN and DJANGO_QSTASH_DOMAIN must be set
to use django-qstash
```

## Related Documentation

- [Getting Started](getting-started.md) - Initial setup guide
- [Security](security.md) - Security configuration
- [Deployment](deployment.md) - Production deployment settings
