from __future__ import annotations

from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        (
            "django_qstash_results",
            "0003_alter_taskresult_status",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="taskresult",
            name="attempt",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="taskresult",
            name="correlation_id",
            field=models.CharField(
                blank=True, db_index=True, default="", max_length=255
            ),
        ),
        migrations.AddField(
            model_name="taskresult",
            name="duration_ms",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="taskresult",
            name="parent_task_id",
            field=models.CharField(
                blank=True, db_index=True, default="", max_length=255
            ),
        ),
        migrations.AlterModelOptions(
            name="taskresult",
            options={"ordering": ["-date_done", "-date_created"]},
        ),
    ]
