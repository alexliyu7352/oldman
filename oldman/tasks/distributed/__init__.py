"""Native task declaration and scheduling objects for the configured process.

Import after service bootstrap. The objects are real, stable instances; their
connections belong to the Application lifecycle (or an explicit Shell context).
"""

from oldman.conf import settings
from oldman.tasks.distributed.broker import TaskiqBroker

broker = TaskiqBroker(settings)
schedule_source = broker.schedule_source

__all__ = ["broker", "schedule_source"]
