"""Outgoing mail: django.core.mail's shape, async, on the stdlib email package and aiosmtplib.

    from oldman.mail import send_mail
    await send_mail("Subject", "Body", None, ["someone@example.com"])

Backends come from `mail.backend` (console by default); `outbox` collects messages sent through the
locmem backend so tests can assert on them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from oldman.mail.backends.base import BaseEmailBackend
from oldman.mail.config import import_backend, mail_config, use_mail_config
from oldman.mail.exceptions import MailConfigurationError, MailError
from oldman.mail.message import Attachment, EmailMessage, EmailMultiAlternatives
from oldman.mail.templated import RenderedMail, render_mail, send_templated_mail

outbox: list[EmailMessage] = []


def get_connection(backend: str | None = None, fail_silently: bool = False, **options: Any) -> BaseEmailBackend:
    """Instantiate a backend: the configured one, or `backend` given as a dotted path."""
    backend_class = import_backend(backend or mail_config().backend)
    return backend_class(fail_silently=fail_silently, **options)


async def send_mail(
    subject: str,
    message: str,
    from_email: str | None,
    recipient_list: Sequence[str],
    *,
    fail_silently: bool = False,
    connection: BaseEmailBackend | None = None,
    html_message: str | None = None,
) -> int:
    """Send one message to `recipient_list`; `html_message` adds an HTML alternative. Returns the sent count."""
    connection = connection or get_connection(fail_silently=fail_silently)
    email = EmailMultiAlternatives(subject, message, from_email, recipient_list, connection=connection)
    if html_message:
        email.attach_alternative(html_message, "text/html")
    return await email.send()


async def send_mass_mail(
    datatuple: Sequence[tuple[str, str, str | None, Sequence[str]]],
    *,
    fail_silently: bool = False,
    connection: BaseEmailBackend | None = None,
) -> int:
    """Send several `(subject, message, from_email, recipient_list)` messages over one connection."""
    connection = connection or get_connection(fail_silently=fail_silently)
    messages = [EmailMessage(subject, message, sender, recipients, connection=connection) for subject, message, sender, recipients in datatuple]
    async with connection:
        return await connection.send_messages(messages)


async def mail_admins(
    subject: str,
    message: str,
    *,
    fail_silently: bool = False,
    connection: BaseEmailBackend | None = None,
    html_message: str | None = None,
) -> int:
    """Send to `mail.admins` with `mail.subject_prefix` in front of the subject; nothing when the list is empty."""
    config = mail_config()
    if not config.admins:
        return 0
    email = EmailMultiAlternatives(f"{config.subject_prefix}{subject}", message, config.default_from_email, list(config.admins), connection=connection or get_connection(fail_silently=fail_silently))
    if html_message:
        email.attach_alternative(html_message, "text/html")
    return await email.send()


__all__ = [
    "Attachment",
    "BaseEmailBackend",
    "EmailMessage",
    "EmailMultiAlternatives",
    "MailConfigurationError",
    "MailError",
    "RenderedMail",
    "get_connection",
    "mail_admins",
    "mail_config",
    "outbox",
    "render_mail",
    "send_mail",
    "send_mass_mail",
    "send_templated_mail",
    "use_mail_config",
]
