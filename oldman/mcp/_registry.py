"""Tools the installed Apps offer over MCP, declared in each App's ``mcp`` module.

An App writes ``from oldman.mcp import mcp`` and decorates async functions; nothing is built at import.
The service turns the declarations into a catalog once it knows which Apps it installs: only then are
signatures resolved (a type defined further down the module, or imported after the decorator ran, is
fine), argument and output schemas generated, and names checked for clashes.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import re
import typing
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from types import NoneType, UnionType
from typing import Annotated, Any, TypeVar, cast, get_args, get_origin, is_typeddict

import mcp_types as types
import msgspec
from pydantic import BaseModel, ConfigDict, TypeAdapter, create_model

from oldman.auth.permissions import Permission
from oldman.logging import get_logger
from oldman.web.request import Request

logger = get_logger("default.mcp")

_Function = TypeVar("_Function", bound=Callable[..., Awaitable[Any]])
#: spec 2026-07-28 server/tools, "Tool Names": 1 to 128 of these characters.
_TOOL_NAME = re.compile(r"[A-Za-z0-9_.-]{1,128}")
#: The protocol's content blocks: a function annotated to return them answers with content only.
_CONTENT_TYPES: tuple[type, ...] = (types.TextContent, types.ImageContent, types.AudioContent, types.ResourceLink, types.EmbeddedResource)


class ToolError(Exception):
    """A failure the tool reports to its caller: the message becomes the tool's error result.

    Any other exception is logged with its traceback and the caller is only told that the tool failed,
    so that internal details do not reach the model.
    """


@dataclass(frozen=True, slots=True)
class _ToolDeclaration:
    function: Callable[..., Awaitable[Any]]
    name: str
    title: str | None
    description: str | None
    annotations: types.ToolAnnotations | None
    permission: Permission | None


@dataclass(frozen=True, slots=True)
class _Output:
    """How a declared return type becomes ``structuredContent`` (spec: it MUST match ``outputSchema``)."""

    schema: dict[str, Any]
    dump: Callable[[Any], Any]
    wrapped: bool


@dataclass(frozen=True, slots=True)
class Tool:
    """One tool of a catalog: the function, how to call it, and what ``tools/list`` shows for it."""

    name: str
    function: Callable[..., Awaitable[Any]]
    permission: Permission | None
    takes_request: bool
    arguments: type[BaseModel]
    output: _Output | None
    wire: types.Tool

    def result(self, value: Any) -> types.CallToolResult:
        """The tool's return value as a result: structured when its return type has a schema."""
        if self.output is None:
            return types.CallToolResult(content=_content(value))
        structured = self.output.dump(value)
        plain = structured["result"] if self.output.wrapped else structured
        text = plain if isinstance(plain, str) else json.dumps(plain, ensure_ascii=False)
        # spec: "a tool that returns structured content SHOULD also return the serialized JSON in a TextContent block".
        return types.CallToolResult(content=[types.TextContent(text=text)], structured_content=structured)


@dataclass(frozen=True, slots=True)
class McpCatalog:
    """What one service offers: the tools in declaration order (spec: ``tools/list`` SHOULD be deterministic)."""

    tools: dict[str, Tool]


class McpRegistry:
    """Where Apps declare what they offer. The process-wide instance is ``oldman.mcp.mcp``."""

    __slots__ = ("_tools",)

    def __init__(self) -> None:
        self._tools: list[_ToolDeclaration] = []

    def tool(
        self,
        name: str | None = None,
        *,
        title: str | None = None,
        description: str | None = None,
        annotations: types.ToolAnnotations | None = None,
        permission: Permission | None = None,
    ) -> Callable[[_Function], _Function]:
        """Offer an async function as a tool; the function is returned unchanged.

        The name defaults to the function's, the description to its docstring. Its parameters and their
        annotations become the input schema; a first parameter annotated ``oldman.web.Request`` receives
        the current request and is left out. With ``permission`` the tool is listed for, and callable by,
        only the signed-in users who hold it.
        """

        def decorator(function: _Function) -> _Function:
            # Checked through Any: iscoroutinefunction narrows its argument, which would no longer be _Function.
            if not inspect.iscoroutinefunction(cast("Any", function)):
                raise TypeError(f"MCP tool {function.__qualname__!r} must be an async function: a sync one would block the worker's event loop")
            tool_name = function.__name__ if name is None else name
            if _TOOL_NAME.fullmatch(tool_name) is None:
                raise ValueError(f"MCP tool name {tool_name!r} must be 1 to 128 of A-Z, a-z, 0-9, '_', '-' and '.'")
            if permission is not None and not isinstance(permission, Permission):
                raise TypeError("permission takes a declared Permission, not a name")
            self._tools.append(
                _ToolDeclaration(
                    function=function,
                    name=tool_name,
                    title=title,
                    description=inspect.getdoc(function) if description is None else description,
                    annotations=annotations,
                    permission=permission,
                )
            )
            return function

        return decorator

    def catalog(self, packages: Sequence[str]) -> McpCatalog:
        """Build what a service installing ``packages`` offers.

        A declaration whose function lives outside those packages is left out with a WARNING: an App
        that is not installed here must not have its tools offered because some other module imported it.
        """
        tools: dict[str, Tool] = {}
        for declaration in self._tools:
            module = declaration.function.__module__
            if not any(module == package or module.startswith(f"{package}.") for package in packages):
                logger.warning(f"MCP tool {declaration.name!r} in {module!r} is not offered: its module belongs to no installed App")
                continue
            existing = tools.get(declaration.name)
            if existing is not None:
                raise ValueError(f"MCP tool {declaration.name!r} is declared twice: in {existing.function.__module__!r} and in {module!r}")
            tools[declaration.name] = _build_tool(declaration)
        return McpCatalog(tools=tools)


def _build_tool(declaration: _ToolDeclaration) -> Tool:
    function = declaration.function
    hints = _type_hints(function)
    parameters = list(inspect.signature(function).parameters.values())
    takes_request = bool(parameters) and _bare(hints.get(parameters[0].name)) is Request
    fields: dict[str, Any] = {}
    for parameter in parameters[1:] if takes_request else parameters:
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD, inspect.Parameter.POSITIONAL_ONLY):
            raise TypeError(
                f"MCP tool {function.__qualname__!r}: parameter {parameter.name!r} must be a named parameter, not *args, **kwargs or positional-only"
            )
        annotation = hints.get(parameter.name, Any)
        default = ... if parameter.default is inspect.Parameter.empty else parameter.default
        fields[parameter.name] = (annotation, default)
    # Extra arguments are refused, not dropped: the model learns from the error what the tool takes.
    # For a tool without parameters this gives the schema the spec recommends ("additionalProperties": false).
    arguments = create_model(f"{declaration.name}_arguments", __config__=ConfigDict(extra="forbid"), **fields)
    output = _output(function, hints)
    wire = types.Tool(
        name=declaration.name,
        title=declaration.title,
        description=declaration.description,
        input_schema=arguments.model_json_schema(),
        output_schema=None if output is None else output.schema,
        annotations=declaration.annotations,
    )
    return Tool(
        name=declaration.name,
        function=function,
        permission=declaration.permission,
        takes_request=takes_request,
        arguments=arguments,
        output=output,
        wire=wire,
    )


def _type_hints(function: Callable[..., Any]) -> dict[str, Any]:
    try:
        return typing.get_type_hints(function, include_extras=True)
    except NameError as exc:
        raise TypeError(
            f"MCP tool {function.__qualname__!r} in {function.__module__!r}: cannot resolve the annotation {exc.name!r}. "
            "Types in a tool's signature become its schema, so they must be importable at run time, not only under TYPE_CHECKING."
        ) from exc


def _output(function: Callable[..., Any], hints: dict[str, Any]) -> _Output | None:
    """The output schema the official SDK would publish for this return type (its func_metadata rules).

    No return annotation, or content blocks: content only. Pydantic models, TypedDicts, dataclasses,
    msgspec Structs and ``dict[str, …]`` are objects as they are. Everything else, ``str`` and ``None``
    included, is wrapped as ``{"result": …}``.
    """
    if "return" not in hints:
        return None
    annotation = hints["return"]
    bare = _bare(annotation)
    if _is_content(bare):
        return None
    if isinstance(bare, type) and issubclass(bare, msgspec.Struct):
        return _Output(schema=msgspec.json.schema(bare), dump=msgspec.to_builtins, wrapped=False)
    if _is_object(bare):
        adapter = TypeAdapter(annotation)
        return _Output(schema=adapter.json_schema(), dump=lambda value: adapter.dump_python(value, mode="json"), wrapped=False)
    wrapper = create_model(f"{function.__name__}_output", result=(annotation, ...))
    adapter = TypeAdapter(annotation)
    return _Output(schema=wrapper.model_json_schema(), dump=lambda value: {"result": adapter.dump_python(value, mode="json")}, wrapped=True)


def _is_object(annotation: Any) -> bool:
    if get_origin(annotation) is dict:
        arguments = get_args(annotation)
        return len(arguments) == 2 and arguments[0] is str
    if not isinstance(annotation, type):
        return False
    return issubclass(annotation, BaseModel) or is_typeddict(annotation) or dataclasses.is_dataclass(annotation)


def _is_content(annotation: Any) -> bool:
    """A content block, or a list, tuple or union of them."""
    if isinstance(annotation, type):
        return issubclass(annotation, _CONTENT_TYPES)
    origin = get_origin(annotation)
    if origin in (list, tuple, UnionType, typing.Union):
        arguments = [argument for argument in get_args(annotation) if argument is not Ellipsis and argument is not NoneType]
        return bool(arguments) and all(_is_content(argument) for argument in arguments)
    return False


def _bare(annotation: Any) -> Any:
    """The annotation without ``Annotated[...]`` metadata."""
    while get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    return annotation


def _content(value: Any) -> list[types.ContentBlock]:
    """An unstructured return value as content blocks."""
    if value is None:
        return []
    if isinstance(value, _CONTENT_TYPES):
        return [value]  # type: ignore[list-item]
    if isinstance(value, list | tuple) and all(isinstance(item, _CONTENT_TYPES) for item in value):
        return list(value)
    if isinstance(value, str):
        return [types.TextContent(text=value)]
    return [types.TextContent(text=json.dumps(msgspec.to_builtins(value), ensure_ascii=False))]


__all__ = ["McpCatalog", "McpRegistry", "Tool", "ToolError"]
