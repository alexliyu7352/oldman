"""Dashboard views for {{ app_slug }}."""

from __future__ import annotations

from oldman.web import Request, render_template, router
from oldman.web.auth import login_required


@router.get("/{{ app_slug }}", name="{{ app_slug }}_index")
@login_required()
async def {{ app_slug }}_index(request: Request):
    """Render the page for any signed-in user; check a permission here (require_perm) when it needs one.

    Its menu entry goes in templates/partials/sidebar.html, where the whole menu is listed.
    """
    return await render_template(
        "{{ app_slug }}/index.html",
        context={"page_entry": "{{ app_slug }}", "request": request},
    )
