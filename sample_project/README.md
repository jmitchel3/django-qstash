# django-qstash sample project

A small Django project (`cfehome`) with a `notifications` app that shows how to
run background tasks with [django-qstash](../README.md) — `delay()`,
`apply_async()` (with `countdown`), stored results, and the admin.

The whole thing runs **fully locally** using the
[QStash dev server](https://upstash.com/docs/qstash/howto/local-development) —
no Upstash account, no public domain, and no ngrok. The dev server runs in
Docker and calls back to your Django app to execute each task.

## How the round-trip works

```
your view ──delay()──▶ QStash dev server ──webhook POST──▶ /qstash/webhook/ ──▶ task runs ──▶ TaskResult saved
   (Django)              (Docker, :8585)                      (Django)
```

Because QStash calls *back* into Django over HTTP, Django must be reachable from
the QStash container, and HTTPS must not be forced. Both setups below handle
that for you.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (for the QStash dev server)
- Python 3.10+ — these docs use [uv](https://docs.astral.sh/uv/), but plain
  `venv` + `pip` works too.

All commands are run from the **repository root** unless noted.

---

## Option 1 — One command, everything in Docker (recommended)

Runs Django *and* the QStash dev server together on a shared Docker network.

```bash
docker compose -f compose.dev.yaml up --build
```

Then open <http://127.0.0.1:8000>. Migrations run automatically on start.

Verify the full task round-trip:

```bash
docker compose -f compose.dev.yaml exec web python manage.py qstash_smoke_test
```

You should see `PASS: result stored with status=SUCCESS`.

In this mode the container talks to QStash at `http://qstash:8080` and QStash
calls back to Django at `http://web:8000` — all configured inline in
[`compose.dev.yaml`](../compose.dev.yaml).

---

## Option 2 — Django on the host, QStash in Docker

Better for active development (hot reload, breakpoints). Django runs on your
machine; only the QStash dev server runs in Docker.

**1. Start the QStash dev server:**

```bash
docker compose -f compose.dev.yaml up qstash
```

**2. Configure and run Django** (new terminal):

```bash
cd sample_project
cp .env.sample .env          # pre-filled with the dev-server credentials
uv sync                      # or: python -m venv .venv && pip install -r requirements.txt
uv run python manage.py migrate
uv run python manage.py runserver 0.0.0.0:8000
```

> Bind `0.0.0.0` (not `127.0.0.1`) so the QStash container can reach Django via
> `host.docker.internal`, which is what `DJANGO_QSTASH_DOMAIN` points to in
> `.env`.

**3. Verify the round-trip** (new terminal):

```bash
cd sample_project && uv run python manage.py qstash_smoke_test
```

### Using `rav`

[`rav`](../rav.yaml) wraps the above:

```bash
rav run qstash          # start the QStash dev server
rav run sample_setup    # copy .env (if missing) + migrate
rav run sample_server   # runserver on 0.0.0.0:8000
rav run sample_smoke    # end-to-end round-trip check
```

---

## Try it in the browser

1. <http://127.0.0.1:8000> — landing page → **Try Notifications App**
2. **/register/** — submit an email. This fires `send_welcome_notification`
   immediately (`.delay()`) and schedules `send_reminder_notification` for ~24h
   later (`.apply_async(countdown=...)`).
3. **/dashboard/** — lists recent `TaskResult` rows (tasks from the last 24h).
4. **/admin/** — browse `TaskResult` and `TaskSchedule`. Create a superuser
   first:

   ```bash
   uv run python manage.py createsuperuser
   # docker: docker compose -f compose.dev.yaml exec web python manage.py createsuperuser
   ```

## Where to look in the code

| File | What it shows |
| --- | --- |
| `cfehome/settings.py` | django-qstash settings, incl. `DJANGO_QSTASH_FORCE_HTTPS` and local `QSTASH_URL` wiring |
| `cfehome/urls.py` | mounting the webhook at `/qstash/webhook/` |
| `notifications/tasks.py` | defining tasks with `@shared_task` |
| `notifications/views.py` | calling `.delay()` and `.apply_async(countdown=...)` |
| `notifications/management/commands/qstash_smoke_test.py` | enqueue + poll for the result |

## Environment variables

All are documented in [`.env.sample`](.env.sample). The important ones for local
mode:

| Variable | Local value | Why |
| --- | --- | --- |
| `QSTASH_URL` | `http://127.0.0.1:8585` | point the client at the dev server |
| `QSTASH_TOKEN` / `*_SIGNING_KEY` | fixed dev-server values | sign & verify webhooks |
| `DJANGO_QSTASH_DOMAIN` | `http://host.docker.internal:8000` | where QStash calls back |
| `DJANGO_QSTASH_FORCE_HTTPS` | `False` | allow plain-http callbacks locally |

The signing keys and token are the fixed values printed by `qstash dev`; they
are safe to commit **for local development only**.
