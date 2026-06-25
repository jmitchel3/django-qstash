from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include
from django.urls import path

from . import views

urlpatterns = [
    path("", views.index),
    path("admin/", admin.site.urls),
    path("", include("notifications.urls")),
    path("qstash/webhook/", include("django_qstash.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
