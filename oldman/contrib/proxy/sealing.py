"""The URL sealer the proxy classes share, keyed from the configured root secret."""

from __future__ import annotations

import base64
from typing import Any

from oldman.utils import strings_utils
from oldman.utils.crypto import UrlSealer
from oldman.web.security.keys import WebSecurityPurpose, configured_web_security_key


def build_url_sealer() -> UrlSealer:
    """Derive the proxy's own key from `web.security.secret_key`.

    Purpose separation means the proxy never shares a key with CSRF, flash or select
    binding, while the deployment still manages one secret.
    """
    derived = configured_web_security_key(WebSecurityPurpose.PROXY_URL)
    return UrlSealer(base64.urlsafe_b64decode(derived))


class UrlSealingMixin:
    """Give a proxy its sealer, resolved when the instance is built.

    Construction is where the rest of the proxy reads settings, so a missing or weak
    root secret surfaces there rather than on the first stream request.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Build the sealer alongside the proxy's other configured state."""
        super().__init__(*args, **kwargs)
        self.url_sealer: UrlSealer = build_url_sealer()

    def seal_url(self, url: str) -> str:
        """Return the opaque path segment that stands in for `url`."""
        return self.url_sealer.seal(url.encode("utf-8"))

    def unseal_url(self, token: str) -> str | None:
        """Return the real URL, or None when the token was edited, forged or malformed."""
        # Strip the extension from the end only: the old `.replace(ext, "")` removed every
        # occurrence, which is a trap waiting for any token alphabet that can contain a dot.
        ext_name = strings_utils.get_ext_from_filename(token)
        if ext_name and token.endswith(ext_name):
            token = token[: -len(ext_name)]
        data = self.url_sealer.unseal(token)
        if data is None:
            return None
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None


__all__ = ["UrlSealingMixin", "build_url_sealer"]
