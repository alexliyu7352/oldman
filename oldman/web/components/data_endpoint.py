"""The data endpoint URL a component's shell points its frontend at."""

from __future__ import annotations

from typing import Any


class DataEndpointMixin:
    """Resolve the route a rendered shell fetches its rows or series from.

    Tables and charts both render an empty shell first and let the frontend pull the
    data, so both need the same answer, and both were computing it with the same
    fifteen lines. The declared attributes are what a view must provide; they are
    re-declared by each view class with its own defaults.
    """

    request: Any = None
    route_name: str = ""
    route_path: str = ""

    def build_data_url(self, route_kwargs: dict[str, object]) -> str:
        """Return the data endpoint URL, falling back to the declared static path."""
        if self.request is not None and getattr(self.request, "app", None) is not None and self.route_name:
            try:
                return self.request.app.url_for(self.route_name, **route_kwargs)
            except Exception:
                # Blueprint routes are registered under "<app>.<name>"; the bare name
                # only resolves for app-level routes.
                return self.request.app.url_for(f"{self.request.app.name}.{self.route_name}", **route_kwargs)
        return self.route_path


__all__ = ["DataEndpointMixin"]
