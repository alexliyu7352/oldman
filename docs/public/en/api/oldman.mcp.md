# `oldman.mcp`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Offer the installed Apps' tools to agents over the Model Context Protocol.

Import with `from oldman.mcp import <name>`.

## `mcp`

value · defined in `oldman.mcp`

```python
mcp = McpRegistry()
```

Where Apps declare their tools: ``from oldman.mcp import mcp``.

## `McpRegistry`

class · defined in `oldman.mcp._registry`

```python
class McpRegistry
```

Where Apps declare what they offer. The process-wide instance is ``oldman.mcp.mcp``.

Constructor:

```python
McpRegistry() -> None
```

Members:

- `def tool(name: str | None=None, *, title: str | None=None, description: str | None=None, annotations: types.ToolAnnotations | None=None, permission: Permission | None=None) -> Callable[[_Function], _Function]` — Offer an async function as a tool; the function is returned unchanged.
- `def catalog(packages: Sequence[str]) -> McpCatalog` — Build what a service installing ``packages`` offers.

## `ToolAnnotations`

re-export · defined in `mcp_types`

```python
from mcp_types import ToolAnnotations
```

Re-exported unchanged from `mcp_types`; see that library's documentation.

## `ToolError`

class · defined in `oldman.mcp._registry`

```python
class ToolError(Exception)
```

A failure the tool reports to its caller: the message becomes the tool's error result.
