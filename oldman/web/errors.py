"""HTML fallback pages for Oldman Web applications."""

from __future__ import annotations

from inspect import isawaitable
from typing import Any

from sanic.errorpages import HTMLRenderer, exception_response, guess_mime
from sanic.handlers import ErrorHandler
from sanic.response import html

from oldman.logging import logger
from oldman.web.template import install_template_loaders


async def render_html_error_response(request: Any, exception: Exception):
    """Render an explicitly selected HTML error, including project overrides."""
    status = int(getattr(exception, "status_code", 500))
    try:
        environment = request.app.ext.environment
        install_template_loaders(environment)
        template = environment.select_template(
            (
                f"errors/{status}.html",
                f"oldman/errors/{status}.html",
                "errors/default.html",
                "oldman/errors/default.html",
            )
        )
        # Only an exception that opts in by carrying page_description puts text on the page;
        # other messages may hold internal detail and never reach production HTML.
        context = {
            "request": request,
            "status_code": status,
            "description": getattr(exception, "page_description", None),
        }
        content = template.render_async(**context) if environment.is_async else template.render(**context)
        if isawaitable(content):
            content = await content
        return html(content, status=status, headers=getattr(exception, "headers", None))
    except Exception:
        logger.exception("Failed to render Oldman %s error page", status)
        handler = request.app.error_handler
        return exception_response(
            request, exception, debug=handler.debug, fallback="html", base=handler.base,
            renderer=HTMLRenderer,
        )


class ErrorPageHandler(ErrorHandler):
    """Render project-overridable HTML pages without changing API errors."""

    # Asynchronous where Sanic's is synchronous: Sanic awaits whatever the error handler returns.
    async def default(self, request: Any, exception: Exception):  # pyrefly: ignore[bad-override]
        """Use project-overridable templates for production HTML errors."""
        status = int(getattr(exception, "status_code", 500))
        fallback = request.app.config.FALLBACK_ERROR_FORMAT
        if status < 400 or guess_mime(request, fallback) != "text/html" or (status >= 500 and self.debug):
            return super().default(request, exception)

        self.log(request, exception)
        return await render_html_error_response(request, exception)


__all__ = ["ErrorPageHandler", "render_html_error_response"]
