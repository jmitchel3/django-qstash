from __future__ import annotations

SECRET_KEY = "NOTASECRET"

DEBUG = True
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
    # Secondary alias used to exercise transaction.on_commit(using="other").
    "other": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
}

INSTALLED_APPS: list[str] = [
    "django_qstash",
    "django_qstash.results",
    "django_qstash.schedules",
    "tests.discovery",
]

MIDDLEWARE: list[str] = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
]

ROOT_URLCONF = "tests.urls"
QSTASH_TOKEN = "test-token"
DJANGO_QSTASH_DOMAIN = "example.com"
QSTASH_CURRENT_SIGNING_KEY = "current-key"
QSTASH_NEXT_SIGNING_KEY = "next-key"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "OPTIONS": {"context_processors": []},
    }
]

USE_TZ = True
