"""The welcome page."""

from __future__ import annotations

from oldman.web import Request, render_template, router


@router.get("/", name="home")
async def home(request: Request):
    """The site's first page: what to do next with this project."""
    return await render_template("home/index.html", context={"request": request})
