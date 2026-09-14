"""The concrete process-local connection, configured only at its first startup."""

from oldman.providers.nats.config import nats_connection_options
from oldman.providers.nats.connection import NATSConnection


class _ConfiguredNATSConnection(NATSConnection):
    """Bind service settings once; inherit registration, communication and cleanup."""

    _configured = False

    async def _connect(self) -> None:
        """Only this managed instance reads Settings; declarations remain offline."""
        if not self._configured:
            from oldman.conf import settings

            config = settings.nats_bus
            if not config.enabled:
                raise RuntimeError("NATS bus is disabled; enable settings.nats_bus before using it")
            options = nats_connection_options(settings.nats[config.nats_alias])
            self.servers = options.pop("servers")
            self.namespace = config.namespace
            self._peer_id = config.peer_id
            self.serializer_mode = config.serializer_mode
            self.startup_timeout = config.startup_timeout
            self._configure_broker(graceful_timeout=config.graceful_timeout, **options)
            self._configured = True
        await super()._connect()


# Creating routers/options is offline. Client and loop ownership begin at startup.
bus = _ConfiguredNATSConnection(name="nats-bus")
