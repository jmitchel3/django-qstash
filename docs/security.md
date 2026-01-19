# Security Guide

This guide covers security best practices for deploying django-qstash in production environments.

## Table of Contents

- [Webhook Signature Verification](#webhook-signature-verification)
- [Environment Variables and Secrets](#environment-variables-and-secrets)
- [Key Rotation](#key-rotation)
- [Rate Limiting](#rate-limiting)
- [Network Security](#network-security)
- [Security Checklist](#security-checklist)

---

## Webhook Signature Verification

django-qstash automatically verifies the authenticity of incoming webhook requests from QStash using cryptographic signatures.

### How It Works

1. QStash signs each webhook request using your signing keys
2. The signature is included in the `Upstash-Signature` header
3. django-qstash verifies this signature before processing the request
4. Invalid signatures result in a 400 Bad Request response

### Verification Process

```python
# This happens automatically in django_qstash.handlers.QStashWebhook


class QStashWebhook:
    def __init__(self):
        self.receiver = Receiver(
            current_signing_key=settings.QSTASH_CURRENT_SIGNING_KEY,
            next_signing_key=settings.QSTASH_NEXT_SIGNING_KEY,
        )

    def verify_signature(self, body: str, signature: str, url: str) -> None:
        """Verify QStash signature."""
        if not signature:
            raise SignatureError("Missing Upstash-Signature header")

        # Force HTTPS for signature verification
        if self.force_https and not url.startswith("https://"):
            url = url.replace("http://", "https://")

        try:
            self.receiver.verify(body=body, signature=signature, url=url)
        except Exception as e:
            raise SignatureError(f"Invalid signature: {e}")
```

### Why Two Signing Keys?

QStash uses two signing keys (`QSTASH_CURRENT_SIGNING_KEY` and `QSTASH_NEXT_SIGNING_KEY`) to support seamless key rotation:

- **Current Key**: The primary key used for signing
- **Next Key**: Used during key rotation to ensure zero-downtime transitions

Both keys are checked during verification, allowing you to rotate keys without service interruption.

### Common Signature Verification Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Signature mismatch | Wrong signing keys | Verify keys match Upstash Console |
| URL mismatch | HTTP vs HTTPS difference | Set `DJANGO_QSTASH_FORCE_HTTPS` appropriately |
| Missing header | Request not from QStash | Ensure webhook endpoint is not exposed to unauthorized access |

---

## Environment Variables and Secrets

### Sensitive Configuration Values

The following settings contain sensitive data and should **never** be committed to version control:

| Setting | Sensitivity | Description |
|---------|-------------|-------------|
| `QSTASH_TOKEN` | High | API token for QStash |
| `QSTASH_CURRENT_SIGNING_KEY` | High | Current webhook signing key |
| `QSTASH_NEXT_SIGNING_KEY` | High | Next webhook signing key |
| `DJANGO_SECRET_KEY` | High | Django secret key |

### Best Practices

#### 1. Use Environment Variables

```python
# settings.py
import os

# NEVER hardcode secrets
QSTASH_TOKEN = os.environ.get("QSTASH_TOKEN")
QSTASH_CURRENT_SIGNING_KEY = os.environ.get("QSTASH_CURRENT_SIGNING_KEY")
QSTASH_NEXT_SIGNING_KEY = os.environ.get("QSTASH_NEXT_SIGNING_KEY")
```

#### 2. Use a `.env` File for Development

```bash
# .env (add to .gitignore!)
QSTASH_TOKEN=your-token-here
QSTASH_CURRENT_SIGNING_KEY=your-current-key
QSTASH_NEXT_SIGNING_KEY=your-next-key
```

#### 3. Use Secret Managers in Production

For production deployments, use platform-specific secret managers:

**AWS Secrets Manager:**
```python
import boto3
import json


def get_secrets():
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId="django-qstash-secrets")
    return json.loads(response["SecretString"])


secrets = get_secrets()
QSTASH_TOKEN = secrets["QSTASH_TOKEN"]
```

**Google Cloud Secret Manager:**
```python
from google.cloud import secretmanager


def get_secret(secret_id):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/your-project/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


QSTASH_TOKEN = get_secret("qstash-token")
```

**HashiCorp Vault:**
```python
import hvac

client = hvac.Client(url="https://vault.example.com")
client.token = os.environ.get("VAULT_TOKEN")

secret = client.secrets.kv.read_secret_version(path="django-qstash")
QSTASH_TOKEN = secret["data"]["data"]["QSTASH_TOKEN"]
```

#### 4. Add Secrets to .gitignore

```gitignore
# .gitignore
.env
.env.local
.env.*.local
*.pem
*.key
credentials.json
secrets.json
```

---

## Key Rotation

Periodically rotating your signing keys is a security best practice. QStash's dual-key system makes this seamless.

### Key Rotation Procedure

#### Step 1: Initiate Rotation in Upstash Console

1. Log into [Upstash Console](https://console.upstash.com/)
2. Navigate to QStash settings
3. Click "Rotate Keys"
4. Note the new key values

#### Step 2: Update Your Application

```bash
# Update environment variables
export QSTASH_CURRENT_SIGNING_KEY="new-current-key"
export QSTASH_NEXT_SIGNING_KEY="new-next-key"

# Restart your application
```

#### Step 3: Deploy and Verify

1. Deploy the updated configuration
2. Monitor logs for signature verification errors
3. Verify tasks are executing correctly

### Rotation Timeline

```
Timeline:
    T+0:    Current Key = A, Next Key = B
    T+1:    Rotate keys in Upstash
            Current Key = B, Next Key = C
    T+2:    Update your application with new keys
    T+3:    Verify webhook deliveries succeed
```

During the transition (T+1 to T+2), both the old and new keys will work because:
- Upstash signs with the new current key
- Your app accepts both current and next keys

### Automated Key Rotation Script

```python
#!/usr/bin/env python
"""Automated key rotation helper."""

import os
import subprocess


def rotate_keys():
    """Rotate QStash signing keys."""
    print("Key Rotation Checklist:")
    print("1. [ ] Log into Upstash Console")
    print("2. [ ] Navigate to QStash > Settings")
    print("3. [ ] Click 'Rotate Keys'")
    print("4. [ ] Copy new key values")
    print()

    new_current = input("Enter new QSTASH_CURRENT_SIGNING_KEY: ").strip()
    new_next = input("Enter new QSTASH_NEXT_SIGNING_KEY: ").strip()

    if not new_current or not new_next:
        print("Error: Both keys are required")
        return

    print()
    print("Update your environment with these values:")
    print(f"QSTASH_CURRENT_SIGNING_KEY={new_current}")
    print(f"QSTASH_NEXT_SIGNING_KEY={new_next}")
    print()
    print("5. [ ] Update your deployment secrets")
    print("6. [ ] Redeploy your application")
    print("7. [ ] Monitor logs for errors")


if __name__ == "__main__":
    rotate_keys()
```

---

## Rate Limiting

### Why Rate Limiting Isn't Built-In

django-qstash intentionally does not include built-in rate limiting for several reasons:

1. **Infrastructure Diversity**: Rate limiting is most effective at the infrastructure level (reverse proxy, CDN, or WAF), where it can reject requests before they reach your application.

2. **Avoid Dependencies**: Built-in rate limiting would require additional dependencies (Redis, memcached) that not all deployments have.

3. **Flexibility**: Different deployments have different requirements. A small application may need 10 requests/second, while a high-throughput system may need 1000+.

4. **Signature Verification as Primary Defense**: QStash webhook requests include cryptographic signatures. Even without rate limiting, only legitimate requests from QStash will be processed. However, processing resources are still consumed during signature verification.

**Recommendation**: Implement rate limiting at your reverse proxy or CDN layer for best protection. This rejects malicious requests before they reach your Django application.

### Reverse Proxy Rate Limiting (Recommended)

#### Nginx Configuration

Nginx provides robust rate limiting with the `limit_req` module:

```nginx
http {
    # Define rate limiting zones
    # Zone 'qstash_webhook' stores up to 10MB of IP addresses (about 160,000 IPs)
    # Rate of 100r/s = maximum 100 requests per second per IP
    limit_req_zone $binary_remote_addr zone=qstash_webhook:10m rate=100r/s;

    # Optional: Zone for stricter limiting on signature failures
    # (requires Lua module or custom log parsing)
    limit_req_zone $binary_remote_addr zone=qstash_strict:10m rate=10r/s;

    server {
        listen 443 ssl http2;
        server_name your-domain.com;

        # QStash webhook endpoint with rate limiting
        location /qstash/webhook/ {
            # Allow bursts up to 200 requests, then apply rate limit
            # 'nodelay' processes burst requests immediately rather than queuing
            limit_req zone=qstash_webhook burst=200 nodelay;

            # Return 429 (Too Many Requests) instead of default 503
            limit_req_status 429;

            # Log rate-limited requests for monitoring
            limit_req_log_level warn;

            proxy_pass http://django_app;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Preserve QStash headers for signature verification
            proxy_set_header Upstash-Signature $http_upstash_signature;
        }
    }
}
```

**Nginx Rate Limiting Parameters**:

| Parameter | Description |
|-----------|-------------|
| `rate=100r/s` | Maximum 100 requests per second per IP |
| `burst=200` | Allow up to 200 queued requests during bursts |
| `nodelay` | Process burst requests immediately |
| `limit_req_status 429` | Return HTTP 429 for rate-limited requests |

#### Caddy Configuration

Caddy 2.7+ includes built-in rate limiting via the `rate_limit` directive:

```caddyfile
your-domain.com {
    # Automatic HTTPS (Caddy's default)
    encode gzip

    # QStash webhook endpoint with rate limiting
    route /qstash/webhook/* {
        rate_limit {
            zone qstash_webhook {
                key {remote_host}
                events 100
                window 1s
            }
        }
        reverse_proxy django_app:8000 {
            header_up X-Forwarded-Proto {scheme}
            header_up X-Real-IP {remote_host}
        }
    }

    # Default Django routes
    handle {
        reverse_proxy django_app:8000 {
            header_up X-Forwarded-Proto {scheme}
        }
    }
}
```

**Note**: If using Caddy without the rate_limit plugin, install it via:
```bash
xcaddy build --with github.com/mholt/caddy-ratelimit
```

### Cloud Provider WAF

#### AWS WAF

AWS WAF can protect your ALB, API Gateway, or CloudFront distribution:

1. **Create a Web ACL** in AWS WAF console

2. **Add a Rate-Based Rule**:
   ```json
   {
     "Name": "QStashWebhookRateLimit",
     "Priority": 1,
     "Statement": {
       "RateBasedStatement": {
         "Limit": 1000,
         "AggregateKeyType": "IP"
       }
     },
     "Action": {
       "Block": {}
     },
     "VisibilityConfig": {
       "SampledRequestsEnabled": true,
       "CloudWatchMetricsEnabled": true,
       "MetricName": "QStashWebhookRateLimit"
     }
   }
   ```

3. **Apply to your resource** (ALB, CloudFront, etc.)

**Recommended AWS WAF Settings**:
- Rate limit: 1000 requests per 5 minutes per IP
- Scope down statement: Match `/qstash/webhook/*` path
- Action: Block with 429 response

#### Cloudflare

Cloudflare provides rate limiting in the WAF rules:

1. Navigate to **Security > WAF > Rate limiting rules**

2. **Create a custom rule**:
   - **Rule name**: QStash Webhook Protection
   - **Field**: URI Path
   - **Operator**: starts with
   - **Value**: `/qstash/webhook/`
   - **Requests**: 100
   - **Period**: 10 seconds
   - **Action**: Block (or Managed Challenge)

3. **Advanced settings**:
   - Counting expression: `ip.src`
   - Response type: Custom JSON
   - Response body: `{"error": "rate_limited"}`

**Cloudflare Pro/Business/Enterprise** also supports:
- IP reputation scoring
- Bot management
- Advanced threat intelligence

### Django Middleware

For deployments where infrastructure-level rate limiting is not available, use Django middleware:

```python
# Install: pip install django-ratelimit

# settings.py
INSTALLED_APPS = [
    # ...existing apps...
    "django_ratelimit",
]

# Optional: Configure cache backend for rate limiting
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": "redis://127.0.0.1:6379/1",
    }
}

RATELIMIT_USE_CACHE = "default"
```

Override the webhook view with rate limiting:

```python
# myapp/views.py
import json
from django.http import HttpResponse
from django_ratelimit.decorators import ratelimit
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from django_qstash.handlers import QStashWebhook


@csrf_exempt
@require_http_methods(["POST"])
@ratelimit(key="ip", rate="100/m", method="POST", block=True)
def rate_limited_webhook_view(request):
    """
    Rate-limited webhook endpoint.

    Limits: 100 requests per minute per IP address.
    Blocked requests receive HTTP 403.
    """
    webhook = QStashWebhook()
    response_data, status_code = webhook.handle_request(request)
    return HttpResponse(
        json.dumps(response_data), status=status_code, content_type="application/json"
    )


# urls.py
from django.urls import path
from myapp.views import rate_limited_webhook_view

urlpatterns = [
    # Override the default webhook URL
    path("qstash/webhook/", rate_limited_webhook_view, name="qstash-webhook"),
    # ...other URLs...
]
```

**Available rate limit keys**:
- `ip`: Client IP address
- `user`: Authenticated user (not applicable for webhooks)
- `user_or_ip`: User if authenticated, otherwise IP
- Custom callable: `key=lambda group, request: request.META.get('HTTP_X_FORWARDED_FOR', request.META['REMOTE_ADDR']).split(',')[0]`

### QStash IP Allowlist

For additional security, you can configure your firewall to only accept webhook requests from QStash's IP ranges.

**Important**: QStash IP ranges may change. Contact [Upstash Support](https://upstash.com/docs/common/help/support) for the current list of egress IPs.

Example Nginx configuration with IP allowlist:

```nginx
location /qstash/webhook/ {
    # Allow QStash IPs (example - get current IPs from Upstash)
    # allow 52.xx.xx.xx/24;
    # allow 34.xx.xx.xx/24;
    # deny all;

    # Rate limiting (as a secondary defense)
    limit_req zone=qstash_webhook burst=200 nodelay;

    proxy_pass http://django_app;
}
```

**Cloud Provider IP Allowlists**:

| Provider | Configuration Location |
|----------|----------------------|
| AWS ALB | Security Group inbound rules |
| AWS CloudFront | WAF IP set |
| Cloudflare | IP Access Rules |
| Google Cloud | Cloud Armor security policy |

### Monitoring for Abuse

Effective rate limiting requires monitoring to detect and respond to abuse patterns.

#### Metrics to Monitor

| Metric | Description | Collection Method |
|--------|-------------|-------------------|
| Request rate per IP | Requests/minute grouped by source | Access logs, APM |
| Signature verification failures | Failed `verify_signature()` calls | Application logs |
| HTTP 4xx/5xx error rates | Client and server errors | Access logs, APM |
| Response latency (p50, p95, p99) | Webhook processing time | APM, application metrics |
| Rate limit trigger count | 429 responses served | Reverse proxy logs |

#### Recommended Alert Thresholds

| Alert | Threshold | Severity | Action |
|-------|-----------|----------|--------|
| Signature failures spike | > 10/minute | High | Investigate source IPs, check key configuration |
| Request rate anomaly | > 10x baseline | Medium | Review traffic patterns, consider IP blocking |
| Error rate increase | > 5% of requests | Medium | Check application logs, verify QStash connectivity |
| Response latency spike | p95 > 10s | Medium | Review task performance, check database |
| Sustained rate limiting | > 100 blocked/minute for 5+ minutes | High | Potential DDoS, consider additional blocking |

#### Logging Configuration for Abuse Detection

```python
# settings.py
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message} [ip:{ip}] [msg_id:{message_id}]",
            "style": "{",
        },
    },
    "handlers": {
        "security": {
            "class": "logging.FileHandler",
            "filename": "/var/log/django/qstash_security.log",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django_qstash.handlers": {
            "handlers": ["security"],
            "level": "WARNING",  # Captures signature failures
        },
    },
}
```

#### Example Monitoring Dashboards

**Grafana Query (Prometheus)**:
```promql
# Request rate by status code
sum(rate(django_http_requests_total{path="/qstash/webhook/"}[5m])) by (status)

# Signature failure rate
sum(rate(qstash_signature_failures_total[5m]))
```

**CloudWatch Insights Query**:
```sql
fields @timestamp, @message
| filter @message like /SignatureError/
| stats count(*) as failures by bin(5m)
| sort @timestamp desc
```

### Recommended Limits Summary

| Deployment Type | Rate Limit | Burst | Notes |
|-----------------|------------|-------|-------|
| Low traffic | 10 req/s | 20 | Small applications |
| Standard | 100 req/s | 200 | Most production deployments |
| High throughput | 1000 req/s | 2000 | Enterprise, requires load testing |
| Strict security | 10 req/s + IP allowlist | 20 | Maximum protection |

---

## Network Security

### HTTPS Configuration

Always use HTTPS in production:

```python
# settings.py
DJANGO_QSTASH_FORCE_HTTPS = True

# Additional Django security settings
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

### Firewall Rules

Consider restricting webhook access to Upstash IP ranges (if available) or using additional authentication:

```nginx
# nginx.conf
location /qstash/webhook/ {
    # Allow only Upstash IPs (check Upstash docs for current ranges)
    # allow x.x.x.x/24;
    # deny all;

    proxy_pass http://django;
}
```

### Content Security

```python
# settings.py
# Ensure webhook endpoint only accepts POST
# This is already handled by django_qstash.views

# Additional headers via middleware or nginx
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
```

---

## Security Checklist

Use this checklist before deploying to production:

### Secrets Management

- [ ] All secrets are stored in environment variables
- [ ] No secrets are committed to version control
- [ ] `.env` files are in `.gitignore`
- [ ] Production uses a secret manager (AWS Secrets Manager, Vault, etc.)
- [ ] Secrets are rotated on a schedule (quarterly recommended)

### Webhook Security

- [ ] `DJANGO_QSTASH_FORCE_HTTPS` is `True`
- [ ] Signing keys match Upstash Console values
- [ ] Signature verification is enabled (default)
- [ ] Error messages don't expose sensitive information

### Network Security

- [ ] HTTPS is enforced
- [ ] SSL/TLS certificates are valid and not expiring
- [ ] Rate limiting is configured
- [ ] Django security middleware is enabled

### Application Security

- [ ] `DEBUG = False` in production
- [ ] `ALLOWED_HOSTS` is properly configured
- [ ] `CSRF_TRUSTED_ORIGINS` includes your domain
- [ ] Django security settings are configured:
  - [ ] `SECURE_SSL_REDIRECT = True`
  - [ ] `SESSION_COOKIE_SECURE = True`
  - [ ] `CSRF_COOKIE_SECURE = True`

### Monitoring

- [ ] Logging is configured for webhook errors
- [ ] Alerts are set up for signature verification failures
- [ ] Task execution errors are monitored

### Regular Reviews

- [ ] Review Upstash Console for unusual activity
- [ ] Audit task result data periodically
- [ ] Check for dependency vulnerabilities (`pip-audit`)
- [ ] Review and rotate keys quarterly

---

## Incident Response

### Compromised Signing Keys

If you suspect your signing keys are compromised:

1. **Immediately rotate keys** in Upstash Console
2. **Update your application** with new keys
3. **Review logs** for unauthorized webhook calls
4. **Audit task results** for suspicious executions
5. **Report to Upstash** if you suspect a breach on their end

### Suspicious Webhook Activity

If you see unexpected webhook requests:

1. **Check signature verification logs** - are signatures valid?
2. **Review request patterns** - unusual timing or volume?
3. **Verify task payloads** - expected function names?
4. **Enable detailed logging** temporarily:
   ```python
   LOGGING = {
       "handlers": {
           "file": {
               "level": "DEBUG",
               "class": "logging.FileHandler",
               "filename": "/var/log/django/qstash.log",
           },
       },
       "loggers": {
           "django_qstash": {
               "handlers": ["file"],
               "level": "DEBUG",
           },
       },
   }
   ```

---

## Related Documentation

- [Configuration](configuration.md) - Settings reference
- [Deployment](deployment.md) - Production deployment guide
- [Troubleshooting](troubleshooting.md) - Common issues and solutions
- [Upstash Security Docs](https://upstash.com/docs/qstash/security/overview)
