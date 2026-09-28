"""The nats-server executable the real NATS checks start their own servers from."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping


def require_nats_server(
    resolver: Callable[[str], str | None] = shutil.which,
    environ: Mapping[str, str] = os.environ,
) -> str:
    """``$NATS_SERVER``, else the nats-server on PATH; a missing one fails the gate instead of skipping its checks.

    It names an executable each check starts on its own port, never a running server.
    """
    executable = environ.get("NATS_SERVER") or resolver("nats-server")
    if executable is None:
        raise RuntimeError("nats-server is required for the Linux integration gate; set NATS_SERVER or put it on PATH")
    return executable
