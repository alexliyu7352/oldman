"""Offer the installed Apps' tools to agents over the Model Context Protocol.

A Web service calls ``install_mcp(app)`` in its ``init()``; an App declares tools in its ``mcp`` module
with the process-wide registry::

    from oldman.mcp import mcp

    @mcp.tool()
    async def count_projects(status: str) -> int:
        \"\"\"Count projects in one status.\"\"\"

Only ``mcp-types`` (the protocol's wire models) is used, never the ``mcp`` SDK, and nothing else in
Oldman imports this package, so a service that offers no MCP loads none of it.
"""

from mcp_types import ToolAnnotations

from oldman.mcp._registry import McpRegistry, ToolError
from oldman.mcp._web import install_mcp

#: Where Apps declare their tools: ``from oldman.mcp import mcp``.
mcp = McpRegistry()

__all__ = ["McpRegistry", "ToolAnnotations", "ToolError", "install_mcp", "mcp"]
