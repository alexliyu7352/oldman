"""Template-rendered messages: `<name>.subject.txt`, `<name>.txt` and an optional `<name>.html`."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from jinja2 import Environment, TemplateNotFound

from oldman.i18n.translations import bind_translations, reset_translations
from oldman.mail.backends.base import BaseEmailBackend
from oldman.mail.message import Attachment, EmailMultiAlternatives
from oldman.web.template import get_template_environment


@dataclass(frozen=True)
class RenderedMail:
    """Subject, plain-text body and optional HTML body produced from one template base name."""

    subject: str
    body: str
    html: str | None = None


def _one_line(subject: str) -> str:
    """Header injection guard: a subject is one line, whatever the template's whitespace."""
    return " ".join(subject.split())


@contextmanager
def _language(language: str | None) -> Iterator[None]:
    """Render under the recipient's catalog; the Web translation service resolves the code."""
    if language is None:
        yield
        return
    from oldman.web.i18n.translation import translation

    catalog = translation.get_translations(language)
    token = bind_translations(catalog)
    try:
        yield
    finally:
        reset_translations(token)


async def _render(environment: Environment, name: str, context: Mapping[str, Any]) -> str:
    template = environment.get_template(name)
    if getattr(environment, "is_async", False):
        return await template.render_async(**context)
    return template.render(**context)


async def render_mail(
    template_base: str,
    context: Mapping[str, Any] | None = None,
    *,
    language: str | None = None,
    environment: Environment | None = None,
    owner: Any = None,
) -> RenderedMail:
    """Render the three templates behind `template_base`; the `.html` one is optional."""
    environment = environment or get_template_environment(owner)
    values = dict(context or {})
    with _language(language):
        subject = _one_line(await _render(environment, f"{template_base}.subject.txt", values))
        body = await _render(environment, f"{template_base}.txt", values)
        try:
            html: str | None = await _render(environment, f"{template_base}.html", values)
        except TemplateNotFound:
            html = None
    return RenderedMail(subject=subject, body=body, html=html)


async def send_templated_mail(
    template_base: str,
    context: Mapping[str, Any] | None = None,
    *,
    to: Sequence[str],
    from_email: str | None = None,
    cc: Sequence[str] | None = None,
    bcc: Sequence[str] | None = None,
    reply_to: Sequence[str] | None = None,
    headers: Mapping[str, str] | None = None,
    attachments: Sequence[Attachment] | None = None,
    language: str | None = None,
    fail_silently: bool = False,
    connection: BaseEmailBackend | None = None,
    environment: Environment | None = None,
    owner: Any = None,
) -> int:
    """Render `template_base` for `to` and send it; the HTML template, when present, rides along as an alternative."""
    rendered = await render_mail(template_base, context, language=language, environment=environment, owner=owner)
    message = EmailMultiAlternatives(
        rendered.subject,
        rendered.body,
        from_email,
        to,
        bcc=bcc,
        cc=cc,
        reply_to=reply_to,
        headers=headers,
        attachments=attachments,
        connection=connection,
    )
    if rendered.html:
        message.attach_alternative(rendered.html, "text/html")
    return await message.send(fail_silently=fail_silently)


__all__ = ["RenderedMail", "render_mail", "send_templated_mail"]
