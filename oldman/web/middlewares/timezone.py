"""Per-request timezone resolution, installed by the application when it wants it."""

from __future__ import annotations

from typing import Any

from oldman.db.schemas import tz_manager
from oldman.web.request import Request

TIMEZONE_HEADER = "X-Timezone"
TIMEZONE_COOKIE = "timezone"


async def add_timezone_info(request: Request) -> None:
    """Resolve the caller's timezone onto `request.ctx.timezone`.

    Reads the `X-Timezone` header first, then the `timezone` cookie. When the caller
    offers neither, it passes None so that `TimezoneManager` applies the deployment's
    configured `core.time_zone`; hardcoding UTC here would silently override that.

    The value is caller-controlled but bounded: `get_timezone` resolves an unknown name
    to the same configured default instead of raising, and only names that actually parse
    enter its cache, so a hostile header cannot grow it.
    """
    tz_name = request.headers.get(TIMEZONE_HEADER) or request.cookies.get(TIMEZONE_COOKIE) or None
    request.ctx.timezone = tz_manager.get_timezone(tz_name)


def install_timezone(app: Any) -> None:
    """Register the timezone middleware on one application.

    Not installed by default, and deliberately so: most services never read
    `request.ctx.timezone`, and a framework should not spend a header lookup and a
    timezone resolution on every request for a feature the application did not ask for.
    Call this from the service's setup when the application needs it.
    """
    from sanic.middleware import MiddlewareLocation

    app.register_middleware(add_timezone_info, MiddlewareLocation.REQUEST.name)


__all__ = ["TIMEZONE_COOKIE", "TIMEZONE_HEADER", "add_timezone_info", "install_timezone"]
