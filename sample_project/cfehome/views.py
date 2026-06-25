from __future__ import annotations

from django.shortcuts import render


def index(request):
    return render(request, "index.html")
