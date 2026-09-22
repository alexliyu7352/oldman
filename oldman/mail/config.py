"""Resolve the active mail settings, with an override for tests and scripts."""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, cast

from oldman.conf.schemas import MailConfig
from oldman.mail.exceptions import MailConfigurationError

if TYPE_CHECKING:
    from oldman.mail.backends.base import BaseEmailBackend

_override: ContextVar[MailConfig | None] = ContextVar("oldman_mail_config", default=None)


def mail_config() -> MailConfig:
    """Return the mail settings: an active override first, then the bootstrapped process settings."""
    override = _override.get()
    if override is not None:
        return override
    from oldman.conf import settings

    return settings.mail


@contextmanager
def use_mail_config(config: MailConfig) -> Iterator[None]:
    """Bind mail settings for the enclosed block (tests, one-off scripts) without process bootstrap."""
    token = _override.set(config)
    try:
        yield
    finally:
        _override.reset(token)


def import_backend(path: str) -> type[BaseEmailBackend]:
    """Import one backend class from its dotted path and check it is a mail backend."""
    from oldman.mail.backends.base import BaseEmailBackend

    segments = path.split(".")
    if len(segments) < 2 or not all(segment.isidentifier() for segment in segments):
        raise MailConfigurationError(f"mail backend {path!r} must be a dotted import path")
    module_name, attribute = ".".join(segments[:-1]), segments[-1]
    try:
        value = getattr(importlib.import_module(module_name), attribute)
    except Exception as error:
        raise MailConfigurationError(f"could not import mail backend {path!r}") from error
    if not isinstance(value, type) or not issubclass(value, BaseEmailBackend):
        raise MailConfigurationError(f"mail backend {path!r} must be a BaseEmailBackend subclass")
    return cast(type[BaseEmailBackend], value)


__all__ = ["import_backend", "mail_config", "use_mail_config"]
