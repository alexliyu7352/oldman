"""Strongly typed browser response actions."""

from __future__ import annotations

from typing import Annotated, Any

import msgspec

from oldman.i18n import LazyTranslation, TranslatableMsgspecModel
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
    """Navigate after an optional non-negative delay."""

    url: str
    delay_ms: Annotated[int, msgspec.Meta(ge=0)] = 0

    def __post_init__(self) -> None:
        """Reject a delay that cannot represent a future navigation."""
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
