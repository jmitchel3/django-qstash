# Deployment Guide

This guide covers deploying django-qstash to production environments, including infrastructure requirements, configuration, and platform-specific instructions.

## Table of Contents

- [Infrastructure Requirements](#infrastructure-requirements)
- [Environment Configuration](#environment-configuration)
- [Reverse Proxy Setup](#reverse-proxy-setup)
- [Platform Deployments](#platform-deployments)
  - [Docker Deployment](#docker-deployment)
  - [Railway](#railway)
  - [Render](#render)
  - [Fly.io](#flyio)
  - [AWS (ECS/Lambda)](#aws-ecslambda)
  - [Google Cloud Run](#google-cloud-run)
- [Database Configuration](#database-configuration)
- [Scaling Considerations](#scaling-considerations)
- [Monitoring and Observability](#monitoring-and-observability)

---

## Infrastructure Requirements

### Minimum Requirements

| Component | Requirement |
|-----------|-------------|
| Python | 3.10+ |
| Django | 5.0+ |
| Database | SQLite (dev), PostgreSQL (prod recommended) |
| Memory | 256MB minimum |
| Network | Publicly accessible HTTPS endpoint |

### Upstash Requirements

- Active [Upstash](https://upstash.com/) account
- QStash enabled
- Valid API credentials:
  - `QSTASH_TOKEN`
  - `QSTASH_CURRENT_SIGNING_KEY`
  - `QSTASH_NEXT_SIGNING_KEY`

### Network Requirements

- **Inbound**: HTTPS (port 443) for webhook delivery
- **Outbound**: HTTPS to `*.upstash.io` for QStash API calls

---

## Environment Configuration

### Production Settings

```python
# settings/production.py
import os

DEBUG = False
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

# Hosts and Security
ALLOWED_HOSTS = [os.environ["ALLOWED_HOST"]]
CSRF_TRUSTED_ORIGINS = [os.environ["CSRF_TRUSTED_ORIGIN"]]

# HTTPS Security
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# QStash Configuration
QSTASH_TOKEN = os.environ["QSTASH_TOKEN"]
QSTASH_CURRENT_SIGNING_KEY = os.environ["QSTASH_CURRENT_SIGNING_KEY"]
QSTASH_NEXT_SIGNING_KEY = os.environ["QSTASH_NEXT_SIGNING_KEY"]

# django-qstash Configuration
DJANGO_QSTASH_DOMAIN = os.environ["DJANGO_QSTASH_DOMAIN"]
DJANGO_QSTASH_WEBHOOK_PATH = "/qstash/webhook/"
DJANGO_QSTASH_FORCE_HTTPS = True
DJANGO_QSTASH_RESULT_TTL = 604800  # 7 days

# Installed Apps
INSTALLED_APPS = [
    # Django apps...
    "django_qstash",
    "django_qstash.results",
    "django_qstash.schedules",
    # Your apps...
]
```

### Environment Variables Template

```bash
# Production environment variables
DJANGO_SECRET_KEY=your-secure-random-key
DJANGO_DEBUG=False
ALLOWED_HOST=your-domain.com
CSRF_TRUSTED_ORIGIN=https://your-domain.com

# Database
DATABASE_URL=postgres://user:pass@host:5432/dbname

# QStash
QSTASH_TOKEN=your-qstash-token
QSTASH_CURRENT_SIGNING_KEY=your-current-key
QSTASH_NEXT_SIGNING_KEY=your-next-key

# django-qstash
DJANGO_QSTASH_DOMAIN=https://your-domain.com
DJANGO_QSTASH_WEBHOOK_PATH=/qstash/webhook/
```

---

## Reverse Proxy Setup

### Nginx Configuration

```nginx
upstream django {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # Security headers
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # QStash webhook endpoint
    location /qstash/webhook/ {
        proxy_pass http://django;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Important for signature verification
        proxy_set_header Upstash-Signature $http_upstash_signature;

        # Timeout for long-running tasks
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    # Static files
    location /static/ {
        alias /app/staticfiles/;
    }

    # Default location
    location / {
        proxy_pass http://django;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Caddy Configuration

```caddyfile
your-domain.com {
    # Automatic HTTPS
    encode gzip

    # QStash webhook endpoint
    handle /qstash/webhook/* {
        reverse_proxy localhost:8000 {
            header_up X-Forwarded-Proto {scheme}
        }
    }

    # Static files
    handle /static/* {
        root * /app/staticfiles
        file_server
    }

    # Django application
    handle {
        reverse_proxy localhost:8000 {
            header_up X-Forwarded-Proto {scheme}
        }
    }
}
```

---

## Platform Deployments

### Docker Deployment

#### Dockerfile

```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Collect static files
RUN python manage.py collectstatic --noinput

# Run with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "myproject.wsgi:application"]
```

#### docker-compose.yml

```yaml
version: '3.8'

services:
  web:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DJANGO_SETTINGS_MODULE=myproject.settings.production
      - DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY}
      - DATABASE_URL=${DATABASE_URL}
      - QSTASH_TOKEN=${QSTASH_TOKEN}
      - QSTASH_CURRENT_SIGNING_KEY=${QSTASH_CURRENT_SIGNING_KEY}
      - QSTASH_NEXT_SIGNING_KEY=${QSTASH_NEXT_SIGNING_KEY}
      - DJANGO_QSTASH_DOMAIN=${DJANGO_QSTASH_DOMAIN}
    depends_on:
      - db
    command: gunicorn --bind 0.0.0.0:8000 --workers 2 myproject.wsgi:application

  db:
    image: postgres:15
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=myproject
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}

volumes:
  postgres_data:
```

---

### Railway

#### railway.json

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "NIXPACKS"
  },
  "deploy": {
    "startCommand": "python manage.py migrate && gunicorn myproject.wsgi:application --bind 0.0.0.0:$PORT",
    "healthcheckPath": "/health/",
    "healthcheckTimeout": 100
  }
}
```

#### Environment Variables (Railway Dashboard)

```
DJANGO_SETTINGS_MODULE=myproject.settings.production
DJANGO_SECRET_KEY=<generate-secure-key>
ALLOWED_HOST=${{RAILWAY_PUBLIC_DOMAIN}}
CSRF_TRUSTED_ORIGIN=https://${{RAILWAY_PUBLIC_DOMAIN}}
DJANGO_QSTASH_DOMAIN=https://${{RAILWAY_PUBLIC_DOMAIN}}
QSTASH_TOKEN=<from-upstash>
QSTASH_CURRENT_SIGNING_KEY=<from-upstash>
QSTASH_NEXT_SIGNING_KEY=<from-upstash>
```

---

### Render

#### render.yaml

```yaml
services:
  - type: web
    name: django-app
    env: python
    buildCommand: pip install -r requirements.txt && python manage.py collectstatic --noinput
    startCommand: gunicorn myproject.wsgi:application
    envVars:
      - key: DJANGO_SETTINGS_MODULE
        value: myproject.settings.production
      - key: DJANGO_SECRET_KEY
        generateValue: true
      - key: ALLOWED_HOST
        fromService:
          type: web
          name: django-app
          property: host
      - key: DJANGO_QSTASH_DOMAIN
        fromService:
          type: web
          name: django-app
          property: hostURL
      - key: QSTASH_TOKEN
        sync: false
      - key: QSTASH_CURRENT_SIGNING_KEY
        sync: false
      - key: QSTASH_NEXT_SIGNING_KEY
        sync: false
      - key: DATABASE_URL
        fromDatabase:
          name: django-db
          property: connectionString

databases:
  - name: django-db
    plan: free
```

---

### Fly.io

#### fly.toml

```toml
app = "your-app-name"
primary_region = "ord"

[build]
  builder = "paketobuildpacks/builder:base"

[env]
  DJANGO_SETTINGS_MODULE = "myproject.settings.production"
  PORT = "8000"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true
  min_machines_running = 0

[[vm]]
  cpu_kind = "shared"
  cpus = 1
  memory_mb = 256

[deploy]
  release_command = "python manage.py migrate"
```

#### Secrets

```bash
fly secrets set DJANGO_SECRET_KEY="your-secret-key"
fly secrets set QSTASH_TOKEN="your-qstash-token"
fly secrets set QSTASH_CURRENT_SIGNING_KEY="your-current-key"
fly secrets set QSTASH_NEXT_SIGNING_KEY="your-next-key"
fly secrets set DJANGO_QSTASH_DOMAIN="https://your-app-name.fly.dev"
fly secrets set DATABASE_URL="postgres://..."
```

---

### AWS (ECS/Lambda)

#### ECS Task Definition (excerpt)

```json
{
  "containerDefinitions": [
    {
      "name": "django-app",
      "image": "your-ecr-repo/django-app:latest",
      "portMappings": [
        {
          "containerPort": 8000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {
          "name": "DJANGO_SETTINGS_MODULE",
          "value": "myproject.settings.production"
        }
      ],
      "secrets": [
        {
          "name": "DJANGO_SECRET_KEY",
          "valueFrom": "arn:aws:secretsmanager:region:account:secret:django/secret-key"
        },
        {
          "name": "QSTASH_TOKEN",
          "valueFrom": "arn:aws:secretsmanager:region:account:secret:qstash/token"
        },
        {
          "name": "QSTASH_CURRENT_SIGNING_KEY",
          "valueFrom": "arn:aws:secretsmanager:region:account:secret:qstash/current-key"
        },
        {
          "name": "QSTASH_NEXT_SIGNING_KEY",
          "valueFrom": "arn:aws:secretsmanager:region:account:secret:qstash/next-key"
        }
      ]
    }
  ]
}
```

---

### Google Cloud Run

#### Deployment

```bash
# Build and push image
gcloud builds submit --tag gcr.io/PROJECT_ID/django-app

# Deploy
gcloud run deploy django-app \
  --image gcr.io/PROJECT_ID/django-app \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars="DJANGO_SETTINGS_MODULE=myproject.settings.production" \
  --set-secrets="DJANGO_SECRET_KEY=django-secret:latest" \
  --set-secrets="QSTASH_TOKEN=qstash-token:latest" \
  --set-secrets="QSTASH_CURRENT_SIGNING_KEY=qstash-current-key:latest" \
  --set-secrets="QSTASH_NEXT_SIGNING_KEY=qstash-next-key:latest"
```

After deployment, set `DJANGO_QSTASH_DOMAIN` to the Cloud Run service URL.

---

## Database Configuration

### PostgreSQL (Recommended)

```python
# settings/production.py
import dj_database_url

DATABASES = {
    "default": dj_database_url.config(
        default=os.environ.get("DATABASE_URL"),
        conn_max_age=600,
        conn_health_checks=True,
    )
}
```

### Migrations

Always run migrations before starting the application:

```bash
# Manual
python manage.py migrate

# In deployment scripts
python manage.py migrate --noinput
```

### Task Result Cleanup

For `django_qstash.results`, schedule regular cleanup:

```bash
# Cron job
0 0 * * * /app/venv/bin/python /app/manage.py clear_stale_results --no-input

# Or use TaskSchedule
```

---

## Scaling Considerations

### Horizontal Scaling

django-qstash is stateless and scales horizontally without modification:

- Each instance can receive webhook requests
- Task results are stored in the shared database
- No coordination required between instances

### Webhook Timeout

QStash has a configurable timeout for webhook responses. Ensure your tasks complete within the timeout:

```python
# For TaskSchedule
TaskSchedule.objects.create(
    name="Long Running Task",
    task="myapp.tasks.long_task",
    cron="0 0 * * *",
    timeout="300s",  # 5 minutes
)
```

### Connection Pooling

For high-throughput scenarios, use connection pooling:

```python
# settings/production.py
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "mydb",
        "USER": "myuser",
        "PASSWORD": "mypassword",
        "HOST": "localhost",
        "PORT": "5432",
        "CONN_MAX_AGE": 600,  # 10 minutes
        "OPTIONS": {
            "MAX_CONNS": 20,
        },
    }
}
```

### Gunicorn Configuration

```python
# gunicorn.conf.py
import multiprocessing

workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"  # or 'gevent' for async
timeout = 120  # Match QStash timeout expectations
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
```

---

## Monitoring and Observability

### Logging Configuration

```python
# settings/production.py
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django_qstash": {
            "handlers": ["console"],
            "level": "INFO",
        },
    },
}
```

### Health Check Endpoint

```python
# views.py
from django.http import JsonResponse


def health_check(request):
    return JsonResponse({"status": "healthy"})


# urls.py
urlpatterns = [
    path("health/", health_check, name="health_check"),
    # ...
]
```

### Metrics to Monitor

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| Webhook response time | Time to process webhook | > 30s |
| Task success rate | Successful / Total tasks | < 95% |
| Signature failures | Failed verifications | > 0 (investigate) |
| Task result backlog | Pending results count | Growing trend |

---

## Production Checklist

Use this comprehensive checklist before deploying django-qstash to production.

### Security

- [ ] **Signing keys configured**
  - [ ] `QSTASH_CURRENT_SIGNING_KEY` is set from Upstash Console
  - [ ] `QSTASH_NEXT_SIGNING_KEY` is set from Upstash Console
  - [ ] Keys are stored securely (environment variables or secret manager)
  - [ ] Keys are not committed to version control

- [ ] **HTTPS enforcement**
  - [ ] `DJANGO_QSTASH_FORCE_HTTPS = True` in settings
  - [ ] SSL/TLS certificate is valid and not expiring soon
  - [ ] `SECURE_SSL_REDIRECT = True` in Django settings
  - [ ] `SECURE_PROXY_SSL_HEADER` configured if behind reverse proxy

- [ ] **Django security settings**
  - [ ] `DEBUG = False`
  - [ ] `SECRET_KEY` is a strong, unique value
  - [ ] `ALLOWED_HOSTS` is properly configured
  - [ ] `CSRF_TRUSTED_ORIGINS` includes your domain
  - [ ] `SESSION_COOKIE_SECURE = True`
  - [ ] `CSRF_COOKIE_SECURE = True`

- [ ] **Rate limiting configured** (see [Security Guide - Rate Limiting](security.md#rate-limiting))
  - [ ] Reverse proxy rate limiting (Nginx/Caddy) OR
  - [ ] Cloud WAF rate limiting (AWS WAF/Cloudflare) OR
  - [ ] Django middleware rate limiting (`django-ratelimit`)

- [ ] **Audit logging enabled**
  - [ ] `django_qstash` logger configured
  - [ ] Signature failures are logged
  - [ ] Task executions are logged with correlation IDs

### Infrastructure

- [ ] **Reverse proxy**
  - [ ] Nginx, Caddy, or cloud load balancer in front of Django
  - [ ] Proper headers forwarded (`X-Forwarded-For`, `X-Forwarded-Proto`)
  - [ ] `Upstash-Signature` header is preserved
  - [ ] Appropriate timeouts configured (match QStash timeout)

- [ ] **Health check endpoint**
  - [ ] `/health/` or similar endpoint returns 200 OK
  - [ ] Health check is monitored by load balancer/orchestrator
  - [ ] Health check excludes authentication requirements

- [ ] **Rate limiting**
  - [ ] Rate limits applied to `/qstash/webhook/` endpoint
  - [ ] HTTP 429 returned for rate-limited requests
  - [ ] Rate limit events are logged for monitoring

- [ ] **Monitoring and alerting**
  - [ ] Application metrics collected (response time, error rate)
  - [ ] Signature verification failures trigger alerts
  - [ ] Task execution errors are tracked
  - [ ] Rate limit triggers are monitored

### Application Configuration

- [ ] **Environment variables**
  - [ ] `QSTASH_TOKEN` is set
  - [ ] `DJANGO_QSTASH_DOMAIN` matches your public URL
  - [ ] `DJANGO_QSTASH_WEBHOOK_PATH` is correct (default: `/qstash/webhook/`)

- [ ] **Database**
  - [ ] Migrations have been run (`python manage.py migrate`)
  - [ ] Database connection pooling configured for production
  - [ ] Task result cleanup scheduled (if using `django_qstash.results`)

- [ ] **Static files**
  - [ ] `collectstatic` has been run
  - [ ] Static files served by reverse proxy or CDN

### Verification Steps

After deployment, verify everything works:

```bash
# 1. Test health check endpoint
curl -I https://your-domain.com/health/

# 2. Verify webhook endpoint is accessible
curl -I https://your-domain.com/qstash/webhook/
# Should return 405 (GET not allowed) or 400 (missing signature)

# 3. Test a task manually
python manage.py shell
>>> from myapp.tasks import my_task
>>> my_task.delay(arg1, arg2)

# 4. Check logs for successful task execution
# Look for: "Task completed successfully" with correlation ID
```

### Post-Deployment Monitoring

Monitor these metrics for the first 24-48 hours after deployment:

| Metric | Expected | Action if Abnormal |
|--------|----------|-------------------|
| Webhook response time | < 1s (p95) | Check task performance |
| Signature success rate | 100% | Verify signing keys |
| Task completion rate | > 99% | Review error logs |
| Rate limit triggers | 0 (from QStash IPs) | Check rate limit config |

---

## Related Documentation

- [Configuration](configuration.md) - All settings reference
- [Security](security.md) - Security best practices
- [Troubleshooting](troubleshooting.md) - Common issues and solutions
