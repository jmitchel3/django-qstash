from __future__ import annotations

import pytest

from django_qstash.schedules.exceptions import InvalidCronStringValidationError
from django_qstash.schedules.exceptions import InvalidDurationStringValidationError
from django_qstash.schedules.validators import validate_cron_expression
from django_qstash.schedules.validators import validate_duration_string


class TestValidateDurationString:
    @pytest.mark.parametrize("value", ["60s", "5m", "2h", "7d"])
    def test_valid(self, value):
        validate_duration_string(value)  # should not raise

    @pytest.mark.parametrize("value", ["60", "abc", "5x", ""])
    def test_invalid_format(self, value):
        with pytest.raises(InvalidDurationStringValidationError, match="Invalid"):
            validate_duration_string(value)

    @pytest.mark.parametrize("value", ["8d", "169h", "604801s"])
    def test_too_long(self, value):
        with pytest.raises(InvalidDurationStringValidationError, match="too long"):
            validate_duration_string(value)


class TestValidateCronExpression:
    def test_valid(self):
        validate_cron_expression("*/5 * * * *")  # should not raise

    @pytest.mark.parametrize("value", ["* * * *", "* * * * * *", "*", ""])
    def test_wrong_field_count(self, value):
        with pytest.raises(InvalidCronStringValidationError, match="5 fields"):
            validate_cron_expression(value)

    def test_invalid_field_value(self):
        with pytest.raises(InvalidCronStringValidationError):
            validate_cron_expression("99 * * * *")
