"""Dashboard views for {{ app_slug }}."""

from __future__ import annotations

from oldman.web import Request, get_app, render_template

app = get_app()


@app.get("/{{ app_slug }}", name="{{ app_slug }}_index")
async def {{ app_slug }}_index(request: Request):
    """Render the dashboard page."""
    context = {
        "dashboard_home_href": "/{{ app_slug }}",
        "dashboard_menu_items": (
            {
                "active": True,
                "href": "/{{ app_slug }}",
                "icon": "ri-dashboard-2-line",
                "label": "{{ app_class }}",
            },
        ),
        "dashboard_activity_notifications": (
            {
                "description": "Dashboard application ready.",
                "href": "/{{ app_slug }}",
                "icon": "ri-notification-3-line",
                "time": "Just now",
                "title": "{{ app_class }}",
                "tone": "primary",
            },
        ),
        "page_entry": "{{ app_slug }}",
        "request": request,
    }
    return await render_template("{{ app_slug }}/index.html", context=context)
