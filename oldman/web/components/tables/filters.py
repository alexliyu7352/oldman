"""Parsers for filter values coming from the query string; invalid input becomes a TableValidationError."""

from __future__ import annotations

import datetime as dt

from oldman.i18n import gettext

from .views import TableValidationError


def parse_boolean_filter(value: object) -> bool:
    """Accept 1/0, true/false, yes/no and on/off in any case."""
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise TableValidationError(gettext("Invalid boolean filter"))


def parse_filter_datetime(value: object) -> dt.datetime | None:
    """Parse an ISO date or datetime; blank means "no bound".

    Columns store naive UTC, so an input carrying a timezone is converted to naive UTC before it is
    compared, instead of failing inside the database driver.
    """
    if value in ("", None):
        return None
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, dt.date):
        parsed = dt.datetime.combine(value, dt.time.min)
    else:
        try:
            parsed = dt.datetime.fromisoformat(str(value))
        except ValueError:
            raise TableValidationError(gettext("Invalid datetime filter")) from None
    if parsed.tzinfo is not None:
        return parsed.astimezone(dt.UTC).replace(tzinfo=None)
    return parsed


def parse_int_filter(value: object, *, label: str, minimum: int | None = None, maximum: int | None = None) -> int:
    """Parse an integer filter (an id, a score) and check it against the optional bounds."""
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        raise TableValidationError(gettext("Invalid %(label)s filter", label=label)) from None
    if (minimum is not None and parsed < minimum) or (maximum is not None and parsed > maximum):
        raise TableValidationError(gettext("Invalid %(label)s filter", label=label))
    return parsed


__all__ = ["parse_boolean_filter", "parse_filter_datetime", "parse_int_filter"]
