"""Convert named NATS settings once, before opening an owned native client."""

from __future__ import annotations

import ssl
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

from oldman.conf.schemas import NATSConnectionConfig


def nats_connection_options(config: NATSConnectionConfig) -> dict[str, Any]:
    """Build native connect arguments, keeping credentials out of server addresses.

    Certificate loading belongs to startup, not settings validation. A caller
    supplying the returned TLS context must install the INFO-phase TLS check on
    its client before connect; the check also runs during native reconnects.
    """
    endpoint = urlsplit(config.nats_url)
    options: dict[str, Any] = {
        "servers": [urlunsplit((endpoint.scheme, endpoint.netloc.rsplit("@", 1)[-1], "", "", ""))],
        "connect_timeout": config.connect_timeout,
        "reconnect_time_wait": config.reconnect_time_wait,
        "max_reconnect_attempts": -1,
    }
    if endpoint.username is not None:
        if not endpoint.username:
            raise ValueError("NATS URL credentials require a username or token")
        try:
            identity = unquote(endpoint.username, errors="strict")
            if endpoint.password is None:
                options["token"] = identity
            else:
                options["user"] = identity
                options["password"] = unquote(endpoint.password, errors="strict")
        except UnicodeError:
            raise ValueError("NATS URL credentials must use valid UTF-8 percent encoding") from None
    if config.credentials_file is not None:
        options["user_credentials"] = str(config.credentials_file)
    if endpoint.scheme == "tls" or config.tls_ca_file is not None or config.tls_cert_file is not None:
        context = ssl.create_default_context(cafile=config.tls_ca_file)
        if config.tls_cert_file is not None:
            context.load_cert_chain(config.tls_cert_file, config.tls_key_file)
        options["tls"] = context
    return options
