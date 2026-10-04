"""The concrete process-local connection, configured only at its first startup."""

from oldman.providers.nats.config import nats_connection_options
from oldman.providers.nats.connection import NATSConnection


class _ConfiguredNATSConnection(NATSConnection):
    """Bind service settings once; inherit registration, communication and cleanup."""

    _configured = False

    def _configure(self) -> None:
        """Only this managed instance reads Settings, once and without I/O; declarations remain offline."""
        if self._configured:
            return
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

    def _check_consuming(self) -> None:
        """The receiving check reads the configured peer_id, which a service checks before it connects."""
        self._configure()
        super()._check_consuming()

    async def _connect(self) -> None:
        self._configure()
        await super()._connect()


# Creating routers/options is offline. Client and loop ownership begin at startup.
bus = _ConfiguredNATSConnection(name="nats-bus")
