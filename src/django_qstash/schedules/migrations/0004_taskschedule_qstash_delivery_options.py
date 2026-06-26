from __future__ import annotations

from django.db import migrations
from django.db import models

import django_qstash.schedules.validators


class Migration(migrations.Migration):
    dependencies = [
        ("django_qstash_schedules", "0003_alter_taskschedule_cron"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskschedule",
            name="retry_delay",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional QStash retry-delay expression, such as '1000' or 'pow(2, retried) * 1000'.",
                max_length=255,
                verbose_name="Retry Delay",
            ),
        ),
        migrations.AddField(
            model_name="taskschedule",
            name="delay",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional delay applied after each cron trigger before delivery (e.g., '30s' or '1d10m').",
                max_length=32,
                validators=[django_qstash.schedules.validators.validate_delay_string],
                verbose_name="Delivery Delay",
            ),
        ),
        migrations.AddField(
            model_name="taskschedule",
            name="queue",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional QStash queue name for FIFO delivery of scheduled messages.",
                max_length=255,
                verbose_name="Queue",
            ),
        ),
        migrations.AddField(
            model_name="taskschedule",
            name="headers",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Headers forwarded to the task webhook by QStash.",
                verbose_name="Headers",
            ),
        ),
        migrations.AddField(
            model_name="taskschedule",
            name="callback",
            field=models.URLField(
                blank=True,
                default="",
                help_text="Optional callback URL QStash calls after each delivery attempt.",
                max_length=2048,
                verbose_name="Callback URL",
            ),
        ),
        migrations.AddField(
            model_name="taskschedule",
            name="callback_headers",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Headers forwarded to the callback URL.",
                verbose_name="Callback Headers",
            ),
        ),
        migrations.AddField(
            model_name="taskschedule",
            name="failure_callback",
            field=models.URLField(
                blank=True,
                default="",
                help_text="Optional callback URL QStash calls after all retries are exhausted.",
                max_length=2048,
                verbose_name="Failure Callback URL",
            ),
        ),
        migrations.AddField(
            model_name="taskschedule",
            name="failure_callback_headers",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Headers forwarded to the failure callback URL.",
                verbose_name="Failure Callback Headers",
            ),
        ),
        migrations.AddField(
            model_name="taskschedule",
            name="flow_control",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Optional QStash flow control settings, such as {'key': 'emails', 'rate': 10, 'period': '1m'}.",
                verbose_name="Flow Control",
            ),
        ),
        migrations.AddField(
            model_name="taskschedule",
            name="label",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional QStash label for log and DLQ filtering.",
                max_length=255,
                verbose_name="Label",
            ),
        ),
        migrations.AddField(
            model_name="taskschedule",
            name="redact",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Optional QStash log redaction settings, such as {'body': True} or {'header': ['Authorization']}.",
                verbose_name="Redaction",
            ),
        ),
    ]
