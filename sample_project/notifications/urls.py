from django.urls import path

from . import views

urlpatterns = [
    path("register/", views.register_user, name="register_user"),
    path("dashboard/", views.task_dashboard, name="task_dashboard"),
]
