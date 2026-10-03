"""The home page."""

from __future__ import annotations

from oldman.web import Request, render_template, router
from oldman.web.auth import login_required


@router.get("/", name="home")
@login_required()
async def home(request: Request):
    """The first page after signing in (`web.account.login_redirect_url`)."""
    return await render_template("home/index.html", context={"request": request})
