"""Web views for {{ app_slug }}."""

from __future__ import annotations

from oldman.web import Request, get_app, render_template

app = get_app()


@app.get("/{{ app_slug }}", name="{{ app_slug }}_index")
async def {{ app_slug }}_index(request: Request):
    """Render the app index page."""
    return await render_template("{{ app_slug }}/index.html", context={"request": request})
