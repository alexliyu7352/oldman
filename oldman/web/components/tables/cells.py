"""Cell primitives for column callbacks: badges, muted or truncated text, dates and row-action menus.

Column callbacks return `(display, raw)`; these helpers build the display half in the shared markup so
every site renders the same badge, the same link and the same actions menu.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from markupsafe import Markup, escape

from oldman.i18n import gettext
from oldman.utils.http import is_safe_link
from oldman.web.components.tables.columns import CellDisplayValue, CellRawValue

BADGE_TONES = frozenset({"primary", "secondary", "success", "info", "warning", "danger"})
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M"


def badge(label: object, tone: str = "secondary") -> Markup:
    """One `om-badge`; an unknown tone falls back to the neutral badge."""
    safe_tone = tone if tone in BADGE_TONES else "secondary"
    tone_class = "default" if safe_tone == "secondary" else safe_tone
    return Markup('<span class="om-badge om-badge-{}">{}</span>').format(escape(tone_class), escape(label))


def muted(text: object) -> Markup:
    """Secondary text, for placeholders such as "Never" or "-"."""
    return Markup('<span class="text-default-500">{}</span>').format(escape(text))


def truncated(text: object | None, *, max_width: int, placeholder: str = "-") -> Markup:
    """Muted text clipped to `max_width` pixels; empty values show `placeholder`."""
    return Markup('<span class="text-default-500 truncate inline-block" style="max-width: {}px;">{}</span>').format(
        int(max_width), escape(text or placeholder)
    )


def link(url: str, label: object, *, class_name: str = "link-primary font-medium") -> Markup:
    """An in-table link, by default the primary identity link of a row.

    `escape(url)` keeps the value inside its quotes; it does nothing about the scheme. Column
    callbacks routinely pass row data into this, so the scheme is checked here rather than left
    to every caller. Only schemes that execute are refused — an external link is fine.
    """
    if not is_safe_link(url):
        raise ValueError("url must not use a scheme that executes (javascript:, data:, ...)")
    return Markup('<a class="{}" href="{}">{}</a>').format(escape(class_name), escape(url), escape(label))


def date_cell(value: object, *, date_format: str = DEFAULT_DATE_FORMAT, empty: object = "") -> tuple[Markup | str, str]:
    """`(display, raw)` for a date or datetime: readable text plus the ISO value for sorting and export.

    A missing value shows `empty` as muted text (or nothing) with an empty raw value; a string that is not
    a date (fixtures, legacy columns) is passed through unchanged.
    """
    if value in ("", None):
        return (muted(empty) if empty else "", "")
    if isinstance(value, dt.datetime | dt.date):
        return value.strftime(date_format), value.isoformat()
    text = str(value)
    return text, text


@dataclass(frozen=True)
class RowAction:
    """One entry of a row-action menu: a link, or a button that opens a (remote) modal."""

    label: object
    href: str | None = None
    modal_target: str | None = None
    modal_url: str | None = None
    icon: str | None = None
    danger: bool = False
    attrs: Mapping[str, object] | None = None  # extra attributes, e.g. {"data-om-feedback-message": "..."}

    def __post_init__(self) -> None:
        """Refuse an href the menu must not turn into a link.

        Checked at construction rather than in `render()` so an invalid action cannot exist:
        `escape(self.href)` below keeps the value inside its quotes and says nothing about the
        scheme. `modal_url` is deliberately not held to this rule — it is fetched, not navigated
        to, and it is a different sink with a different answer.
        """
        if self.href is not None and not is_safe_link(self.href):
            raise ValueError("href must not use a scheme that executes (javascript:, data:, ...)")

    def render(self) -> Markup:
        icon = Markup('<i class="{}" aria-hidden="true"></i>').format(escape(self.icon)) if self.icon else Markup("")
        classes = "om-dropdown-item om-dropdown-item-danger" if self.danger else "om-dropdown-item"
        extra = Markup("").join(Markup(' {}="{}"').format(escape(name), escape(value)) for name, value in (self.attrs or {}).items())
        if self.href is not None:
            return Markup('<li><a class="{}" href="{}"{}>{}{}</a></li>').format(classes, escape(self.href), extra, icon, escape(self.label))
        attributes = Markup("")
        if self.modal_target is not None:
            attributes += Markup(' data-om-modal-target="{}"').format(escape(self.modal_target))
        if self.modal_url is not None:
            attributes += Markup(' data-om-modal-url="{}"').format(escape(self.modal_url))
        return Markup('<li><button class="{}" type="button"{}{}>{}{}</button></li>').format(classes, attributes, extra, icon, escape(self.label))


def row_actions(actions: Sequence[RowAction], *, label: object | None = None) -> Markup:
    """The row-action menu: a ghost icon toggle and one `om-dropdown-item` per action, aligned to the end."""
    items = Markup("").join(action.render() for action in actions)
    return Markup(
        '<div class="om-dropdown">'
        '<button class="om-button om-button-ghost-secondary om-button-sm om-button-icon" type="button" data-om-dropdown-toggle aria-expanded="false">'
        '<i class="ri-more-fill" aria-hidden="true"></i><span class="sr-only">{}</span>'
        "</button>"
        '<ul class="om-dropdown-menu om-dropdown-menu-end">{}</ul>'
        "</div>"
    ).format(escape(label if label is not None else gettext("Row actions")), items)


__all__ = ["BADGE_TONES", "DEFAULT_DATE_FORMAT", "RowAction", "badge", "date_cell", "link", "muted", "row_actions", "truncated"]


def normalize_raw_value(value: object) -> CellRawValue:
    """Reduce a field value to something a JSON payload and a data-* attribute can carry."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def render_display_value(value: CellDisplayValue) -> Markup:
    """Turn a display value into safe HTML, leaving Markup the caller already escaped."""
    if isinstance(value, Markup):
        return value
    if value is None:
        return Markup("")
    return Markup(escape(value))
