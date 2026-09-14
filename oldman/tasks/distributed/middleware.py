"""Validate task routing and completion acknowledgement at native extension points."""

from __future__ import annotations

from taskiq import TaskiqMessage, TaskiqMiddleware
from taskiq.acks import AcknowledgeType, parse_acknowledge_type

from oldman.conf.schemas import validate_taskiq_name


def is_broadcast(labels: dict[str, object]) -> bool:
    """Accept native labels, including their string form after serialization."""
    return str(labels.get("broadcast", False)).lower() == "true"


def validate_task_labels(message: TaskiqMessage) -> TaskiqMessage:
    """A task may not escape its subject namespace or request early acknowledgement."""
    queue = message.labels.get("queue_name", "default")
    if not isinstance(queue, str):
        raise ValueError("queue_name must be a string")
    validate_taskiq_name(queue)
    ack = message.labels.get("ack_type")
    if ack is not None and parse_acknowledge_type(ack) != AcknowledgeType.WHEN_SAVED:
        raise ValueError("Oldman distributed tasks only support ack_type='when_saved'")
    if is_broadcast(message.labels):
        # Normalize this envelope, never the decorated task's shared labels.
        message.labels.update(ignore_result=True, retry_on_error=False)
    return message


class TaskPolicyMiddleware(TaskiqMiddleware):
    """The same task policy applies to local publication and received envelopes."""

    def pre_send(self, message: TaskiqMessage) -> TaskiqMessage:
        """Validate before serialization and native publication."""
        return validate_task_labels(message)

    def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """Do not let externally supplied labels bypass completion acknowledgement."""
        return validate_task_labels(message)
