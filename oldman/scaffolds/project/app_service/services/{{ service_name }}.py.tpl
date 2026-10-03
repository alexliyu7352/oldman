"""Default background service for {{ project_name }}."""

from __future__ import annotations

import asyncio
from typing import Any

from oldman.logging import get_logger
from oldman.runtime import SimpleApplication

log = get_logger(__name__)

# Seconds between two rounds of the example loop.
INTERVAL_SECONDS = 10


class {{ service_class }}(SimpleApplication):
    """Run the project's background workload."""

    def prepare(self) -> None:
        """Prepare synchronous service resources."""

    async def main(self, *args: Any, **kwargs: Any) -> None:
        """Run until `./run.sh {{ service_name }} stop` or Ctrl+C; replace the loop's body with this service's work.

        Stopping cancels this coroutine where it waits, so code after the loop never runs: release what the
        work holds in `before_stop()` or `after_stop()`.
        """
        del args, kwargs
        rounds = 0
        while True:
            rounds += 1
            log.info("Example loop, round %d: this service's work goes here", rounds)
            await asyncio.sleep(INTERVAL_SECONDS)
