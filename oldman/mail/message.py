"""Outgoing message objects modelled on django.core.mail, built on the stdlib email package."""

from __future__ import annotations

import mimetypes
import socket
from collections.abc import Mapping, Sequence
from email.message import EmailMessage as MIMEMessage
from email.utils import formatdate, make_msgid, parseaddr
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from oldman.mail.config import mail_config

if TYPE_CHECKING:
    from oldman.mail.backends.base import BaseEmailBackend

DEFAULT_ATTACHMENT_MIME_TYPE = "application/octet-stream"


class Attachment(NamedTuple):
    """One attachment: a file name, its content (bytes, or text for `text/*`) and a MIME type."""

    filename: str
    content: bytes | str
    mimetype: str


@cache
def message_id_domain() -> str:
    """Domain part of generated Message-ID headers; the host name needs no DNS lookup."""
    return socket.gethostname() or "localhost"


def envelope_address(value: str) -> str:
    """Bare address for the SMTP envelope, from either `addr` or `Name <addr>`."""
    return parseaddr(value)[1] or value


def _address_list(name: str, value: Sequence[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raise TypeError(f'"{name}" argument must be a list or tuple')
    return list(value)


class EmailMessage:
    """A plain-text message with optional attachments; `send()` hands it to a backend."""

    content_subtype = "plain"

    def __init__(
        self,
        subject: str = "",
        body: str = "",
        from_email: str | None = None,
        to: Sequence[str] | None = None,
        bcc: Sequence[str] | None = None,
        connection: BaseEmailBackend | None = None,
        attachments: Sequence[Attachment | tuple[str, bytes | str, str | None]] | None = None,
        headers: Mapping[str, str] | None = None,
        cc: Sequence[str] | None = None,
        reply_to: Sequence[str] | None = None,
    ) -> None:
        self.subject = subject
        self.body = body or ""
        self.from_email = from_email or mail_config().default_from_email
        self.to = _address_list("to", to)
        self.cc = _address_list("cc", cc)
        self.bcc = _address_list("bcc", bcc)
        self.reply_to = _address_list("reply_to", reply_to)
        self.extra_headers: dict[str, str] = dict(headers or {})
        self.connection = connection
        self.attachments: list[Attachment] = []
        for attachment in attachments or ():
            if isinstance(attachment, Attachment):
                self.attachments.append(attachment)
            else:
                filename, content, mimetype = attachment
                self.attach(filename, content, mimetype)

    def get_connection(self, fail_silently: bool = False) -> BaseEmailBackend:
        """Return the message's backend, creating the configured one on first use."""
        from oldman.mail import get_connection

        if self.connection is None:
            self.connection = get_connection(fail_silently=fail_silently)
        return self.connection

    def recipients(self) -> list[str]:
        """Every envelope recipient: To, then Cc, then Bcc."""
        return [*self.to, *self.cc, *self.bcc]

    def attach(self, filename: str, content: bytes | str, mimetype: str | None = None) -> None:
        """Add an attachment; the MIME type is guessed from the file name when not given."""
        if not isinstance(content, (bytes, str)):
            raise TypeError("attachment content must be bytes or str")
        resolved = mimetype or mimetypes.guess_type(filename)[0] or DEFAULT_ATTACHMENT_MIME_TYPE
        if isinstance(content, str) and not resolved.startswith("text/"):
            raise TypeError(f"attachment {filename!r} has text content but a non-text MIME type {resolved!r}")
        self.attachments.append(Attachment(filename, content, resolved))

    def attach_file(self, path: str | Path, mimetype: str | None = None) -> None:
        """Attach a file from disk under its own base name; text types are read as UTF-8 text."""
        file_path = Path(path)
        resolved = mimetype or mimetypes.guess_type(file_path.name)[0] or DEFAULT_ATTACHMENT_MIME_TYPE
        content: bytes | str = file_path.read_bytes()
        if resolved.startswith("text/"):
            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                resolved = DEFAULT_ATTACHMENT_MIME_TYPE
        self.attachments.append(Attachment(file_path.name, content, resolved))

    def message(self) -> MIMEMessage:
        """Build the MIME message: body, alternatives, attachments, then the headers."""
        mime = MIMEMessage()
        # 8bit like Django: UTF-8 text stays readable in the console and file backends instead of base64.
        mime.set_content(self.body, subtype=self.content_subtype, cte="8bit")
        self._add_alternatives(mime)
        for attachment in self.attachments:
            maintype, _, subtype = attachment.mimetype.partition("/")
            if isinstance(attachment.content, str):
                mime.add_attachment(attachment.content, subtype=subtype or "plain", filename=attachment.filename)
            else:
                mime.add_attachment(attachment.content, maintype=maintype or "application", subtype=subtype or "octet-stream", filename=attachment.filename)
        self._set_headers(mime)
        return mime

    def _add_alternatives(self, mime: MIMEMessage) -> None:
        return None

    def _set_headers(self, mime: MIMEMessage) -> None:
        # An explicit header replaces the generated one whatever its case; the policy allows one of each.
        explicit = {name.lower(): (name, value) for name, value in self.extra_headers.items()}

        def header(name: str, default: str) -> str:
            given = explicit.pop(name.lower(), None)
            return default if given is None else given[1]

        mime["Subject"] = header("Subject", self.subject)
        mime["From"] = header("From", self.from_email)
        recipients = header("To", ", ".join(self.to))
        if recipients:
            mime["To"] = recipients
        cc = header("Cc", ", ".join(self.cc))
        if cc:
            mime["Cc"] = cc
        reply_to = header("Reply-To", ", ".join(self.reply_to))
        if reply_to:
            mime["Reply-To"] = reply_to
        # Bcc never appears in the message; the backend addresses the envelope from recipients().
        for name, value in explicit.values():
            mime[name] = value
        if "Date" not in mime:
            mime["Date"] = formatdate(localtime=True)
        if "Message-ID" not in mime:
            mime["Message-ID"] = make_msgid(domain=message_id_domain())

    async def send(self, fail_silently: bool = False) -> int:
        """Send through the message's backend; a message without recipients is not sent."""
        if not self.recipients():
            return 0
        return await self.get_connection(fail_silently).send_messages([self])


class EmailMultiAlternatives(EmailMessage):
    """A text message with alternative renderings, typically an HTML version."""

    def __init__(self, *args: Any, alternatives: Sequence[tuple[str, str]] | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.alternatives: list[tuple[str, str]] = list(alternatives or [])

    def attach_alternative(self, content: str, mimetype: str) -> None:
        """Add an alternative body, for example the HTML rendering as `text/html`."""
        if not isinstance(content, str):
            raise TypeError("alternative content must be str")
        self.alternatives.append((content, mimetype))

    def _add_alternatives(self, mime: MIMEMessage) -> None:
        for content, mimetype in self.alternatives:
            _maintype, _, subtype = mimetype.partition("/")
            mime.add_alternative(content, subtype=subtype or "html", cte="8bit")


__all__ = ["Attachment", "EmailMessage", "EmailMultiAlternatives", "envelope_address"]
