"""Dedicated scheduled-task service."""

from oldman.runtime import TaskiqSchedulerApplication


class {{ service_class }}(TaskiqSchedulerApplication):
    """Publish due tasks; execution remains in separately started Workers."""
