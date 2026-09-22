"""Strongly typed browser response actions."""

from __future__ import annotations

from typing import Annotated, Any

import msgspec

from oldman.i18n import LazyTranslation, TranslatableMsgspecModel
from oldman.utils.http import is_safe_link
from oldman.web.api.enums import ApiResponseAction, FeedbackMode, HtmlSwap


class ResponseAction(
    TranslatableMsgspecModel,
    tag_field="action",
    kw_only=True,
    omit_defaults=True,
):
    """Base contract for one ordered browser action."""

    target: str | None = None
    data: Any = None


class FeedbackAction(ResponseAction, tag=ApiResponseAction.FEEDBACK.value, kw_only=True):
    """Show one plain-text toast or alert."""

    mode: FeedbackMode = FeedbackMode.TOAST
    title: str | LazyTranslation
    text: str | LazyTranslation | None = None
    icon: str | None = None


class ReplaceHtmlAction(ResponseAction, tag=ApiResponseAction.REPLACE_HTML.value, kw_only=True):
    """Replace one page-scoped HTML target."""

    html: str
    swap: HtmlSwap | None = None


class CloseModalAction(ResponseAction, tag=ApiResponseAction.CLOSE_MODAL.value, kw_only=True):
    """Close an explicit or source-adjacent modal."""


class ReloadTableAction(ResponseAction, tag=ApiResponseAction.RELOAD_TABLE.value, kw_only=True):
    """Reload one mounted table."""

    target: str  # pyright: ignore[reportGeneralTypeIssues] -- this tagged subtype makes the inherited optional target required


class RedirectAction(ResponseAction, tag=ApiResponseAction.REDIRECT.value, kw_only=True):
    """Navigate after an optional non-negative delay.

    `url` is held to the same rule as a Dashboard activity item's `href`, and for the same reason:
    the browser hands this value straight to `window.location.assign`, and a `javascript:` URL
    there is a script, not a destination. Escaping is not the defence — nothing escapes this
    value; only the scheme check does.

    It is a denylist, not an allowlist: redirecting to an external payment page, an OAuth
    provider or an object store is ordinary business, and requiring a local path would push
    users into working around the framework.
    """

    url: str
    delay_ms: Annotated[int, msgspec.Meta(ge=0)] = 0

    def __post_init__(self) -> None:
        """Reject a destination that executes, and a delay that cannot represent a future navigation."""
        if not is_safe_link(self.url):
            raise ValueError("url must not use a scheme that executes (javascript:, data:, ...)")
        if self.delay_ms < 0:
            raise ValueError("delay_ms must be greater than or equal to zero")


__all__ = [
    "CloseModalAction",
    "FeedbackAction",
    "RedirectAction",
    "ReloadTableAction",
    "ReplaceHtmlAction",
    "ResponseAction",
]
