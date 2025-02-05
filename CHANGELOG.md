# Changelog

All notable changes to this project will be documented in this file.

## [0.1.1] - 2025-02-06`

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
