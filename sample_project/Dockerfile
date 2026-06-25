# Dockerfile for the django-qstash sample project.
# Build context is the repository root so we can install the local
# django-qstash package alongside the sample app.
#
#   docker compose -f compose.dev.yaml up --build
#
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install the local django-qstash package plus the sample-only dependencies.
COPY pyproject.toml README.md LICENSE /pkg/
COPY src /pkg/src
RUN pip install --no-cache-dir /pkg python-decouple

COPY sample_project /app

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
