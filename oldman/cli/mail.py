"""Send a test message through the configured mail backend of one service."""

from __future__ import annotations

import asyncio
import datetime as dt
import socket
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from oldman.cli.settings import ensure_cwd_on_syspath
from oldman.i18n import gettext
from oldman.runtime import bootstrap_service


@dataclass(frozen=True)
class TestMailResult:
    """What the test send did: how many messages the backend accepted and which backend that was."""

    count: int
    backend: str


def send_test_mail(
    service_module: str,
    recipients: Sequence[str],
    *,
    config_file: Path | None = None,
) -> TestMailResult:
    """Bootstrap the service, then send one plain message to `recipients` like Django's sendtestemail."""
    ensure_cwd_on_syspath()
    context = bootstrap_service(service_module, config_file=config_file)
    from oldman.mail import send_mail

    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = gettext("Test email from %(host)s on %(time)s", host=socket.gethostname(), time=now)
    body = gettext("If you're reading this, the mail settings of this service work.")
    count = asyncio.run(send_mail(subject, body, None, list(recipients)))
    return TestMailResult(count=count, backend=context.settings.mail.backend)


__all__ = ["TestMailResult", "send_test_mail"]
