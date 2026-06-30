# Changelog

All notable changes to this project will be documented in this file.

## [0.6.0] - 2026-06-29

### Added
- `bind=True` support on `@shared_task`/`@stashed_task`. A bound task receives a `self` first argument whose `self.request` exposes `id`, `retries`, `correlation_id`, `task_name`, `args`, and `kwargs`. The retry count is read from QStash's `Upstash-Retried` header at the webhook; eager execution supplies a generated id and `retries=0`. Per-call request state lives on a fresh bound proxy, never on the shared task instance, so concurrent deliveries stay isolated.
- Minimal sequential task chaining. `task.s(...)`/`task.si(...)` build a link signature and `apply_async(..., link=sig_or_list)` enqueues the linked task(s) after the task succeeds. Links are resolved through the task allowlist and enqueued by the webhook handler after success (and inline under eager mode); unresolved links are logged and skipped without failing the original task. Parallel `group`/`chord` canvas remains out of scope.
- `DJANGO_QSTASH_DISCOVER_CLEAR_CACHE_ON_REQUEST` setting (defaults to `settings.DEBUG`) controls whether the task-discovery cache is cleared on every request. Production (`DEBUG=False`) no longer pays a per-request `dir()`-walk of every tasks module; development still picks up newly added tasks under autoreload.
- `docs/celery-compatibility.md`: a compatibility matrix of what django-qstash supports, what differs from Celery, and what is not yet implemented.

### Changed
- Documented that webhook rate limiting belongs at the platform/edge layer (QStash signature verification provides authenticity); see the Security and Configuration guides.
- Refreshed `prod-readiness.md` to v0.5.0 and reconciled its remaining-issues list against the current code (content-type validation, HTTPS parsing, mypy in CI, callback URL validation, and result-service typing are all resolved).

## [0.4.0] - 2026-06-25

### Added
- `TaskSchedule` now supports QStash delivery controls for `retry_delay`, `delay`, `queue`, forwarded headers, callbacks, failure callbacks, flow control, labels, and redaction.
- Schedule formatting forwards the new delivery options to `qstash.schedule.create` when set.
- Cron validation now accepts QStash `CRON_TZ=Area/Location` timezone prefixes.
- Added `qstash_dlq` for listing, filtering, inspecting, and deleting QStash dead letter queue entries.

## [0.3.1] - 2026-06-25

### Fixed
- Scheduled tasks now send QStash webhook payloads with `Content-Type: application/json`, matching normal `.delay()`/`.apply_async()` task dispatch.
- The Task Schedule admin list now shows the human-readable schedule name separately from the raw task path.
- The README schedule example now uses the correct `discover_tasks(locations_only=True)` API and assigns the selected task path to `task`.

### Added
- Added a README workflow diagram showing how `.delay()` publishes to QStash and returns through `/qstash/webhook/`.
- Expanded the sample project into a fully-local Docker Compose walkthrough for Django plus the QStash dev server.
- Added a `qstash_smoke_test` management command that enqueues a sample task and waits for the webhook result.
- Added `rav` shortcuts for running the local QStash server, sample project, and smoke test.

## [0.3.0] - 2026-06-25

### Changed
- **Upgraded the `qstash` dependency to v3 (`qstash>=3,<4`).** This is a major-version bump of the underlying SDK. Apps that use django-qstash exclusively are unaffected, but apps that also import the `qstash` package directly (pinned to v2) must upgrade to v3, which has its own breaking API changes (e.g. the restructured `Schedule` dataclass).
- **Default retry behavior.** When a task does not define `max_retries`, django-qstash no longer forces `retries=3`; it now omits the option so QStash applies your account-level default. Tasks that relied on exactly 3 retries should set `max_retries` explicitly.
- Reworked `QStashTask` so per-call options no longer mutate the shared task wrapper. Previously `apply_async(countdown=...)`/options leaked onto the task and affected later `delay()`/`apply_async()` calls; each call is now independent.

### Added
- `apply_async()` now forwards supported QStash message options (`callback`, `failure_callback`, `headers`, `timeout`, `deduplication_id`, `flow_control`, etc.) and supports Celery-style `eta` alongside `countdown`.
- `apply_async(queue=...)` routes through QStash's `enqueue_json` for FIFO queue delivery. Note: queues do not support `delay`/`not_before`, so combining `queue` with `countdown`/`eta` raises `ImproperlyConfigured`.
- Unsupported message options now raise `ImproperlyConfigured` with guidance to upgrade `qstash`, rather than failing obscurely.

## [0.2.4] - 2026-01-19

### Fixed
- Minor bug fix.
- Updated security test.

## [0.2.3] - 2026-01-19

### Added
- Python 3.14 support.

## [0.2.2] - 2026-01-18

### Changed
- Updated callbacks.

## [0.2.1] - 2026-01-18

### Changed
- Maintenance release.

## [0.2.0] - 2026-01-16

### Changed
- Migrated to [uv](https://docs.astral.sh/uv/) for dependency management.
- Fixed git command paths in `rav.yaml`.

## [0.1.4] - 2026-01-16

### Fixed
- Upstash domain validation no longer always triggers a warning.

### Added
- Added `context7.json` for documentation indexing.
- Updated `rav` scripts.

## [0.1.3] - 2025-09-11

### Changed
- Pinned `qstash-py` to v2.
- Moved a warning.

## [0.1.2] - 2025-04-03

### Added
- Support for Django 5.2.

### Fixed
- Updated test requirements.
- README fixes and typo corrections.

## [0.1.1] - 2025-02-06

### Added
- Fix results stored in `TaskResult` model result field. (Was stored as a JSON string, but should be a JSON object via a Python dict)

## [0.1.0] - 2025-02-05

### Added
- Prepare for public release

## [0.0.15] - 2025-01-24

### Added
- Support for local development with QStash via Docker Compose and [these docs](https://upstash.com/docs/qstash/howto/local-development)
- `QSTASH_URL` support for the django-qstash QStash client
- Docker Compose sample [compose.dev.yaml](./compose.dev.yaml) for local development
- Upgraded Django in tests due to security vulnerability.

## [0.0.14] - 2025-01-22

### Added
- Added `django_qstash.urls` as default for `ROOT_URLCONF`
- Updated `README.md` with new information
- Updated `sample_project` with a few more examples (thanks @Abdusshh)

## [0.0.13] - 2025-01-14

### Added
- Automated django `makemigrations` on commit
- Updated pre-commit hooks to check migrations (fail if any migrations are not created)
- Added `makemigrations` and `migrate` commands to `rav`

## [0.0.12] - 2025-01-06

### Added
- Better tracking support and error handling for `TaskResult` model
  - added the `function_path` field
  - Updated webhook exception handling to store errors in running tasks
- Created dedicated task to clear error results
- Added Cron string validation for `TaskScheduleForm`
- Improved tests

## [0.0.11] - 2025-01-04

### Added
- `shared_task` decorator to enable Celery compatibility

### Changed
- django-qstash's `shared_task` decorator (`django_qstash.app.decorators.shared_task`) is now alternative name for `stashed_task`

## [0.0.10] - 2025-01-03

### Added
- New task discovery to include task name and field label
- `available_tasks` management command to view all available tasks
- `TaskChoiceField` to form fields to select available tasks
- New tests

## [0.0.9] - 2025-01-03

- Fixes issue with schedule_id not being set on TaskSchedule model

## [0.0.8] - 2025-01-03

### Added
- Added `clear_stale_results_task` task to cleanup old task results
- Updated `clear_stale_results` management command to use `clear_stale_results_task` with background trigger
- Moved `shared_task` and `QStashTask` to `django_qstash.app.decorators` and `django_qstash.app.base` respectively
- Updated tests for above changes

## [0.0.7] - 2025-01-02

### Added
- New test cases for django management commands

### Removed
- Import bug in django management commands

## [0.0.6] - 2025-01-02

### Added
- `django_qstash.schedules` for QStash Schedules
- Added task schedule management command to sync QStash schedules with Django models
- Updated Tests for django_qstash.schedules

## [0.0.5] - 2025-01-01

No changes, testing bump2version.

## [0.0.4] - 2025-01-01

### Added
- moved configuration requirements to execution time


## [0.0.3] - 2024-12-30

### Added
- django-qstash results app to store task results
- webhook services to save task results
- decoupled webhook view into handlers and exceptions
- new sample django project (`sample_project/`)
- Added management command to clear old task results
- Add more tests for Django model, handlers, exceptions

### Removed
- Old sample django project (`example_project/`)

## [0.0.2] - Skipped

## [0.0.1] - 2024-12-23

### Added
- Proof of concept release
- Initialized django-qstash package
- Django integration for Upstash QStash message queue service
- Message verification using QStash signatures
- Support for handling QStash webhook requests
- Test suite with pytest
- GitHub Actions CI workflow
- Tox configuration for multiple Python and Django versions
- Documentation and examples

[0.1.1]: https://github.com/jmitchel3/django-qstash/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jmitchel3/django-qstash/compare/v0.0.15...v0.1.1
[0.0.15]: https://github.com/jmitchel3/django-qstash/compare/v0.0.15...v0.1.0
[0.0.14]: https://github.com/jmitchel3/django-qstash/compare/v0.0.14...v0.0.15
[0.0.13]: https://github.com/jmitchel3/django-qstash/compare/v0.0.13...v0.0.14
[0.0.12]: https://github.com/jmitchel3/django-qstash/compare/v0.0.12...v0.0.13
[0.0.11]: https://github.com/jmitchel3/django-qstash/compare/v0.0.11...v0.0.12
[0.0.10]: https://github.com/jmitchel3/django-qstash/compare/v0.0.10...v0.0.11
[0.0.9]: https://github.com/jmitchel3/django-qstash/compare/v0.0.9...v0.0.10
[0.0.8]: https://github.com/jmitchel3/django-qstash/compare/v0.0.8...v0.0.9
[0.0.7]: https://github.com/jmitchel3/django-qstash/compare/v0.0.7...v0.0.8
[0.0.6]: https://github.com/jmitchel3/django-qstash/compare/v0.0.6...v0.0.7
[0.0.5]: https://github.com/jmitchel3/django-qstash/compare/v0.0.5...v0.0.6
[0.0.4]: https://github.com/jmitchel3/django-qstash/compare/v0.0.4...v0.0.5
[0.0.3]: https://github.com/jmitchel3/django-qstash/compare/v0.0.3...v0.0.4
[0.0.2]: https://github.com/jmitchel3/django-qstash/compare/v0.0.2...v0.0.3
[0.0.1]: https://github.com/jmitchel3/django-qstash/compare/v0.0.1...v0.0.2
