"""Purpose-separated keys derived from the configured Web root secret."""

from __future__ import annotations

import base64
import hashlib
import hmac
from enum import StrEnum


class WebSecurityPurpose(StrEnum):
    """Protocols that must not reuse one another's signing key."""

    CSRF = "oldman.web.csrf.v1"
    SELECT_BINDING = "oldman.web.forms.select.v1"
    FLASH = "oldman.web.messages.flash.v1"
    PROXY_URL = "oldman.contrib.proxy.url.v1"


def derive_web_security_key(
    root_secret: str,
    purpose: WebSecurityPurpose,
) -> str:
    """Derive one URL-safe key without exposing the configured root."""
    if not isinstance(root_secret, str) or len(root_secret) < 32:
        raise ValueError("root_secret must contain at least 32 characters")
    if not isinstance(purpose, WebSecurityPurpose):
        raise TypeError("purpose must be a WebSecurityPurpose")
    digest = hmac.new(
        root_secret.encode("utf-8"),
        purpose.value.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")


def configured_web_security_key(purpose: WebSecurityPurpose) -> str:
    """Derive one key from the process-wide typed Web settings."""
    import oldman.conf as conf

    root_secret = conf.settings.web.security.secret_key
    if root_secret is None:
        raise RuntimeError("settings.web.security.secret_key is empty; run `oldman <service> settings sync`")
    return derive_web_security_key(root_secret, purpose)


__all__ = [
    "WebSecurityPurpose",
    "configured_web_security_key",
    "derive_web_security_key",
]
