"""Transient Dashboard browser messages."""

from __future__ import annotations

from oldman.i18n import LazyTranslation
from oldman.web.api import ResponseAction
from oldman.web.messages.paths import is_safe_link


class DashboardActivityAction(ResponseAction, tag="dashboard_activity", kw_only=True):
    """Add one non-persistent item to the Dashboard current-activity menu.

    `href` is held to the same rule as a stored notification's: a local absolute path.
    The frontend renders it into an anchor and escapes the attribute, which stops the
    value breaking out of the quotes but does nothing about the scheme — `javascript:`
    in an href is a script. Stored notifications refused a foreign href at creation;
    this one did not, so the same field had two answers depending on which message
    carried it.
    """

    title: str | LazyTranslation
    description: str | LazyTranslation = ""
    tone: str = "primary"
    icon: str | None = None
    href: str | None = None
    time: str | LazyTranslation | None = None

    def __post_init__(self) -> None:
        """Refuse an href the Dashboard must not turn into a link."""
        if self.href is not None and not is_safe_link(self.href):
            raise ValueError("href must not use a scheme that executes (javascript:, data:, ...)")


__all__ = ["DashboardActivityAction"]
