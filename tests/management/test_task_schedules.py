from __future__ import annotations

from io import StringIO
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.core.management import call_command


@pytest.mark.django_db
class TestTaskSchedulesCommand:
    @patch("django_qstash.management.commands.task_schedules.qstash_client")
    def test_list_schedules(self, mock_client, capsys):
        """Test that --list displays schedules correctly"""
        # Mock the schedule response
        mock_schedule = Mock()
        mock_schedule.schedule_id = "test-schedule-123"
        mock_schedule.cron = "0 0 * * *"
        mock_schedule.destination = "https://example.com/webhook"
        mock_schedule.retries = 3
        mock_schedule.paused = False
        mock_schedule.body = (
            '{"task_name": "Test Task", "module": "test.tasks", "function": "my_task"}'
        )

        mock_client.schedule.list.return_value = [mock_schedule]

        # Run the command
        call_command("task_schedules", "--list")

        captured = capsys.readouterr()
        assert "Found 1 remote schedules" in captured.out
        assert "Schedule ID: test-schedule-123" in captured.out
        assert "Task: Test Task (test.tasks.my_task)" in captured.out
        assert "Cron: 0 0 * * *" in captured.out

    @patch("django_qstash.management.commands.task_schedules.qstash_client")
    @patch("builtins.input", return_value="y")
    def test_sync_schedules(self, mock_input, mock_client, capsys):
        """Test that --sync creates/updates TaskSchedule objects"""
        # Mock the schedule response
        mock_schedule = Mock()
        mock_schedule.schedule_id = "test-schedule-123"
        mock_schedule.cron = "0 0 * * *"
        mock_schedule.body = """{
            "task_name": "Test Task",
            "module": "test.tasks",
            "function": "my_task",
            "args": [1, 2],
            "kwargs": {"key": "value"}
        }"""

        mock_client.schedule.list.return_value = [mock_schedule]

        # Run the command
        call_command("task_schedules", "--sync")

        captured = capsys.readouterr()
        assert "Found 1 remote schedules" in captured.out

    def test_no_options_specified(self, capsys):
        """Test that command requires either --list or --sync option"""
        call_command("task_schedules")

        captured = capsys.readouterr()
        assert "Please specify either --list or --sync option" in captured.out

    @patch("django_qstash.management.commands.task_schedules.qstash_client")
    def test_handle_api_error(self, mock_client, capsys):
        """Test that API errors are handled gracefully"""
        mock_client.schedule.list.side_effect = Exception("API Error")

        call_command("task_schedules", "--list")

        captured = capsys.readouterr()
        assert "An error occurred: API Error" in captured.out

    @patch("django_qstash.management.commands.task_schedules.qstash_client")
    @patch("builtins.input", return_value="n")
    def test_sync_cancelled(self, mock_input, mock_client, capsys):
        """Test that sync is cancelled when user responds 'n'"""
        # Mock the schedule response
        mock_schedule = Mock()
        mock_schedule.schedule_id = "test-schedule-123"
        mock_schedule.cron = "0 0 * * *"
        mock_schedule.destination = "https://example.com/qstash/webhook/"
        mock_schedule.body = '{"task_name": "Test Task"}'
        mock_client.schedule.list.return_value = [mock_schedule]

        # Run the command with --sync
        call_command("task_schedules", "--sync")

        captured = capsys.readouterr()
        assert "Found 1 remote schedules" in captured.out
        # assert "Operation cancelled" in captured.out

    @patch("django_qstash.management.commands.task_schedules.qstash_client")
    def test_sync_invalid_json(self, mock_client, capsys):
        """Test handling of invalid JSON in schedule body"""
        mock_schedule = Mock()
        mock_schedule.schedule_id = "test-schedule-123"
        mock_schedule.cron = "0 0 * * *"
        mock_schedule.destination = "https://example.com/qstash/webhook/"
        mock_schedule.body = "invalid json"
        mock_client.schedule.list.return_value = [mock_schedule]

        # Run the command with --sync and no-input=True to skip confirmation
        call_command("task_schedules", "--sync", "--no-input")

        captured = capsys.readouterr()
        assert "An error occurred:" in captured.out

    @patch("django_qstash.management.commands.task_schedules.qstash_client")
    def test_sync_missing_required_fields(self, mock_client, capsys):
        """Test handling of missing required fields in schedule body"""
        mock_schedule = Mock()
        mock_schedule.schedule_id = "test-schedule-123"
        mock_schedule.cron = "0 0 * * *"
        mock_schedule.destination = "https://example.com/qstash/webhook/"
        mock_schedule.body = '{"task_name": "Test Task"}'  # Missing module and function
        mock_client.schedule.list.return_value = [mock_schedule]

        # Run the command with --sync and force=True to skip confirmation
        call_command("task_schedules", "--sync", "--force")

        captured = capsys.readouterr()
        assert "An error occurred: 'module'" in captured.out

    @patch("django_qstash.management.commands.task_schedules.apps")
    def test_task_schedule_model_not_found(self, mock_apps, capsys):
        """Test error handling when TaskSchedule model is not available"""
        mock_apps.get_model.side_effect = LookupError("Model not found")

        call_command("task_schedules", "--sync")

        captured = capsys.readouterr()
        print(captured.out)
        assert "An error occurred:" in captured.out

    @patch("django_qstash.management.commands.task_schedules.qstash_client")
    @patch("builtins.input", return_value="y")
    def test_sync_schedules_exception(self, mock_input, mock_client, capsys):
        """Test exception handling in sync_schedules"""
        # Mock a schedule that will cause an exception during sync
        mock_schedule = Mock()
        mock_schedule.schedule_id = "test-schedule-123"
        mock_schedule.cron = "0 0 * * *"
        mock_schedule.body = (
            '{"task_name": "Test Task", "module": "test.tasks", "function": "my_task"}'
        )
        mock_client.schedule.list.return_value = [mock_schedule]

        # Mock TaskSchedule.objects.update_or_create to raise an exception
        with patch(
            "django_qstash.management.commands.task_schedules.apps.get_model"
        ) as mock_get_model:
            mock_model = Mock()
            mock_model.objects.update_or_create.side_effect = Exception(
                "Database error"
            )
            mock_get_model.return_value = mock_model

            call_command("task_schedules", "--sync", "--no-input")

        captured = capsys.readouterr()
        assert "Found 1 remote schedule" in captured.out

    @patch("django_qstash.management.commands.task_schedules.qstash_client")
    def test_no_options_raises_error(self, mock_client, capsys):
        """Test that no options raises CommandError"""
        call_command("task_schedules")
        captured = capsys.readouterr()
        assert "Please specify either --list or --sync option" in captured.out

    @patch("django_qstash.management.commands.task_schedules.apps")
    def test_get_task_schedule_model(self, mock_apps, capsys):
        """Test get_task_schedule_model method for both success and failure cases"""
        from django_qstash.management.commands.task_schedules import Command

        # Test successful model retrieval
        mock_model = Mock()
        mock_apps.get_model.return_value = mock_model

        command = Command()
        result = command.get_task_schedule_model()

        assert result == mock_model
        mock_apps.get_model.assert_called_once_with(
            "django_qstash_schedules", "TaskSchedule"
        )

        # Test model lookup failure
        mock_apps.get_model.side_effect = LookupError("Model not found")

        result = command.get_task_schedule_model()

        captured = capsys.readouterr()
        assert result is None
        assert "Django QStash Schedules not installed" in captured.out
        assert (
            "Add `django_qstash.schedules` to INSTALLED_APPS and run migrations"
            in captured.out
        )

    def test_sync_schedules_returns_when_model_missing(self):
        """sync_schedules should bail out early when TaskSchedule is unavailable"""
        from django_qstash.management.commands.task_schedules import Command

        command = Command()
        schedule = Mock()
        with patch.object(command, "get_task_schedule_model", return_value=None):
            result = command.sync_schedules([schedule])

        assert result is None
        # No schedule should be inspected once the model is missing.
        schedule.body.assert_not_called()

    @pytest.fixture
    def command_output(self):
        stdout = StringIO()
        stderr = StringIO()
        yield stdout, stderr
        stdout.close()
        stderr.close()

    @patch("django_qstash.management.commands.task_schedules.qstash_client")
    def test_sync_command_error(self, mock_client, command_output):
        """Test that command handles errors during sync"""
        # Mock the schedule response with invalid data to trigger an error
        mock_schedule = Mock()
        mock_schedule.schedule_id = "test-schedule-123"
        mock_schedule.cron = "0 0 * * *"
        mock_schedule.body = '{"invalid": "data"}'  # This will cause a KeyError
        mock_client.schedule.list.return_value = [mock_schedule]

        stdout, stderr = command_output
        call_command(
            "task_schedules", "--sync", "--no-input", stdout=stdout, stderr=stderr
        )

        assert "An error occurred: " in stdout.getvalue()

    @patch("django_qstash.management.commands.task_schedules.qstash_client")
    @patch("builtins.input", return_value="n")
    def test_sync_cancelled_message(self, mock_input, mock_client, capsys):
        """Test that correct message is shown when sync is cancelled"""
        # Mock the schedule response
        mock_schedule = Mock()
        mock_schedule.schedule_id = "test-schedule-123"
        mock_schedule.cron = "0 0 * * *"
        mock_schedule.body = (
            '{"task_name": "Test Task", "module": "test.tasks", "function": "my_task"}'
        )
        mock_client.schedule.list.return_value = [mock_schedule]

        # Run the command with --sync
        call_command("task_schedules", "--sync")

        captured = capsys.readouterr()
        assert "Sync cancelled" in captured.out
