"""Web views for {{ app_slug }}."""

from __future__ import annotations

from oldman.web import Request, router, render_template


@router.get("/{{ app_slug }}", name="{{ app_slug }}_index")
async def {{ app_slug }}_index(request: Request):
    """Render the app index page."""
    return await render_template("{{ app_slug }}/index.html", context={"request": request})
