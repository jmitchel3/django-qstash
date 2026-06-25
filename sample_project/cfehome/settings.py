"""
Django settings for sample project. We named it cfehome
because all of my Django tutorials use the project name cfehome.
See https://cfe.sh/github to see more.
"""

from __future__ import annotations

import os
from pathlib import Path

from decouple import config
from django.core.management.utils import get_random_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = config("DJANGO_DEBUG", default=False, cast=bool)
SECRET_KEY = config("DJANGO_SECRET_KEY", default=get_random_secret_key())


###########################
# qstash-py settings
###########################
QSTASH_URL = config("QSTASH_URL", default=None)
if DEBUG and QSTASH_URL is not None:
    # if python-decouple loads the QSTASH_URL from the
    # .env file, then we will set the environment variable
    # django-qstash will use to connect to the local
    # qstash instance.
    os.environ["QSTASH_URL"] = QSTASH_URL

QSTASH_TOKEN = config("QSTASH_TOKEN")
QSTASH_CURRENT_SIGNING_KEY = config("QSTASH_CURRENT_SIGNING_KEY")
QSTASH_NEXT_SIGNING_KEY = config("QSTASH_NEXT_SIGNING_KEY")

###########################
# django_qstash settings
###########################
DJANGO_QSTASH_DOMAIN = config("DJANGO_QSTASH_DOMAIN")
DJANGO_QSTASH_WEBHOOK_PATH = config(
    "DJANGO_QSTASH_WEBHOOK_PATH", default="/qstash/webhook/"
)
# In local development the QStash dev server calls back over plain http
# (e.g. http://host.docker.internal:8000), so HTTPS must not be forced.
# In production this should be True (the default) so callbacks use https.
DJANGO_QSTASH_FORCE_HTTPS = config(
    "DJANGO_QSTASH_FORCE_HTTPS", default=not DEBUG, cast=bool
)

# Dangerous: disable host header validation
ALLOWED_HOSTS = ["*"]
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default=[],
    cast=lambda v: [x.strip() for x in v.split(",") if x.strip()] if v else [],
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_qstash",
    "django_qstash.results",
    "django_qstash.schedules",
    "notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "cfehome.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            BASE_DIR / "cfehome" / "templates",
            BASE_DIR / "notifications" / "templates",
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]
WSGI_APPLICATION = "cfehome.wsgi.application"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
