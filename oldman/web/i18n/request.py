"""Sanic Request subclass for language-prefixed routes."""

from __future__ import annotations

from typing import Any

from httptools import parse_url
from sanic import Request as SanicRequest

from oldman.i18n.utils import split_language_from_path
from oldman.logging import logger


class I18nRequest(SanicRequest):
    """Strip a configured language prefix before Sanic route matching."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the native request and rewrite one recognized prefix."""
        super().__init__(*args, **kwargs)

        # Sanic may reuse request context storage, so source behavior explicitly
        # clears the path metadata before parsing the next request.
        self.ctx.detected_lang = None
        self.ctx.clean_path = None
        self.ctx.original_path = None

        from oldman.web.i18n.translation import translation

        prefix, clean_path = split_language_from_path(self.path)
        detected_language = translation.resolve_language(prefix)
        if not detected_language:
            return

        self.ctx.original_path = self.path
        self.ctx.detected_lang = detected_language
        self.ctx.clean_path = clean_path

        original = self._parsed_url
        rewritten_url = (
            (original.schema or b"http")
            + b"://"
            + (original.host or b"localhost")
            + clean_path.encode("utf-8")
            + (b"?" + original.query if original.query else b"")
            + (b"#" + original.fragment if original.fragment else b"")
        )
        self._parsed_url = parse_url(rewritten_url)
        logger.debug(
            "i18n path rewrite: %s -> %s",
            self.ctx.original_path,
            self.path,
        )


__all__ = ["I18nRequest"]
