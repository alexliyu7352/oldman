"""Illustrative worker service snippet; this is not a standalone project."""

from oldman.runtime.simple import SimpleApplication


class ExampleWorker(SimpleApplication):
    SERVICE_NAME = "Example worker"

    def prepare(self) -> None:
        """Prepare the example worker."""

    async def main(self) -> None:
        print("running")
