"""MCP tools, resources and prompts of the {{ app_slug }} App.

A Web service offers them once its ``init()`` calls ``install_mcp(app)`` after ``super().init()``::

    from oldman.mcp import install_mcp

    install_mcp(app)

Users connect with a JWT access token; programs with an API key whose name is listed in
``web.mcp.callers``. A tool with ``permission=`` is listed for, and callable by, only the users
who hold it.
"""

from __future__ import annotations

from oldman.mcp import mcp
from oldman.web import Request

from apps.{{ app_slug }}.permissions import {{ app_class }}Permissions


@mcp.tool()
async def {{ app_slug }}_status() -> dict[str, str]:
    """Report that the {{ app_slug }} App is reachable. Every admitted caller sees this tool."""
    return {"app": "{{ app_slug }}", "status": "ok"}


@mcp.tool(permission={{ app_class }}Permissions.use)
async def {{ app_slug }}_whoami(request: Request) -> dict[str, str]:
    """Name the signed-in user. Listed only for users who hold the permission; API keys have none."""
    return {"user": request.ctx.user.username}


@mcp.resource("app://{{ app_slug }}/about", mime_type="text/plain")
async def {{ app_slug }}_about() -> str:
    """What the {{ app_slug }} App offers over MCP."""
    return "Describe what this App's tools do here, for the model to read."


@mcp.prompt()
async def {{ app_slug }}_question(topic: str) -> str:
    """Ask a question about one topic, answered with the {{ app_slug }} tools."""
    return f"Use the {{ app_slug }} tools to answer a question about {topic}."
