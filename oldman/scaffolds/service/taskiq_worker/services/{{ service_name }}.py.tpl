"""Run this service's configured distributed task queues."""

from oldman.runtime import TaskiqWorkerApplication


class {{ service_class }}(TaskiqWorkerApplication):
    """Configure Apps, queues and connections in data/{{ service_name }}_settings.yaml."""
