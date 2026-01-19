from __future__ import annotations

import json

from django.http import HttpRequest
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .handlers import QStashWebhook


@csrf_exempt
@require_http_methods(["POST"])
def qstash_webhook_view(request: HttpRequest) -> HttpResponse:
    """Handle QStash webhook requests."""
    # Validate Content-Type
    content_type = request.content_type.lower() if request.content_type else ""

    # Extract base content type (before any ;charset= parameters)
    content_type_base = content_type.split(";")[0].strip()

    if content_type_base != "application/json":
        return HttpResponse(
            json.dumps(
                {
                    "status": "error",
                    "error_type": "InvalidContentType",
                    "error": f"Expected Content-Type 'application/json', got '{content_type or 'none'}'",
                }
            ),
            status=415,  # Unsupported Media Type
            content_type="application/json",
        )

    webhook = QStashWebhook()
    response_data, status_code = webhook.handle_request(request)
    return HttpResponse(
        json.dumps(response_data), status=status_code, content_type="application/json"
    )
