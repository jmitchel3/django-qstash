from __future__ import annotations

from django.dispatch import Signal

# Fired when a webhook request is received
# Arguments: message_id (str), task_path (str|None), source_ip (str)
webhook_received = Signal()

# Fired when a task starts execution
# Arguments: task_name (str), correlation_id (str), args (list), kwargs (dict)
task_started = Signal()

# Fired when a task completes successfully
# Arguments: task_name (str), correlation_id (str), duration (float), result (Any)
task_completed = Signal()

# Fired when a task fails
# Arguments: task_name (str), correlation_id (str), duration (float), exception (Exception)
task_failed = Signal()
