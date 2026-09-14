"""Transient Dashboard browser messages."""

from __future__ import annotations

from oldman.i18n import LazyTranslation
from oldman.web.api import ResponseAction


class DashboardActivityAction(ResponseAction, tag="dashboard_activity", kw_only=True):
    """Add one non-persistent item to the Dashboard current-activity menu."""

    title: str | LazyTranslation
    description: str | LazyTranslation = ""
    tone: str = "primary"
    icon: str | None = None
    href: str | None = None
    time: str | LazyTranslation | None = None


__all__ = ["DashboardActivityAction"]
