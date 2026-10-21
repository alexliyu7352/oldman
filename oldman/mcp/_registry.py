"""Tools, resources and prompts the installed Apps offer over MCP, declared in each App's ``mcp`` module.

An App writes ``from oldman.mcp import mcp`` and decorates async functions; nothing is built at import.
The service turns the declarations into a catalog once it knows which Apps it installs: only then are
signatures resolved (a type defined further down the module, or imported after the decorator ran, is
fine), argument and output schemas generated, and names checked for clashes.
"""

from __future__ import annotations

import base64
import dataclasses
import inspect
import json
import re
import sys
import typing
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from types import NoneType, UnionType
from typing import Annotated, Any, TypeVar, cast, get_args, get_origin, is_typeddict
from urllib.parse import unquote

import mcp_types as types
import msgspec
from pydantic import BaseModel, ConfigDict, PydanticSchemaGenerationError, TypeAdapter, ValidationError, create_model
from pydantic.fields import FieldInfo

from oldman.auth.permissions import Permission
from oldman.logging import get_logger
from oldman.web.request import Request

logger = get_logger("default.mcp")

_Function = TypeVar("_Function", bound=Callable[..., Awaitable[Any]])
#: spec 2026-07-28 server/tools, "Tool Names": 1 to 128 of these characters.
_TOOL_NAME = re.compile(r"[A-Za-z0-9_.-]{1,128}")
#: The protocol's content blocks: a function annotated to return them answers with content only.
_CONTENT_TYPES: tuple[type, ...] = (types.TextContent, types.ImageContent, types.AudioContent, types.ResourceLink, types.EmbeddedResource)
#: A URI template variable: RFC 6570 level 1 only ({name}); operators such as {+path} or {?query} are refused.
_TEMPLATE_VARIABLE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_RESOURCE_CONTENTS: tuple[type, ...] = (types.TextResourceContents, types.BlobResourceContents)


class ToolError(Exception):
    """A failure the tool reports to its caller: the message becomes the tool's error result.

    Any other exception is logged with its traceback and the caller is only told that the tool failed,
    so that internal details do not reach the model.
    """


@dataclass(frozen=True, slots=True)
class _ToolDeclaration:
    function: Callable[..., Awaitable[Any]]
    module: str
    name: str
    title: str | None
    description: str | None
    annotations: types.ToolAnnotations | None
    permission: Permission | None


@dataclass(frozen=True, slots=True)
class _ResourceDeclaration:
    function: Callable[..., Awaitable[Any]]
    module: str
    uri: str
    name: str
    title: str | None
    description: str | None
    mime_type: str | None
    permission: Permission | None


@dataclass(frozen=True, slots=True)
class _PromptDeclaration:
    function: Callable[..., Awaitable[Any]]
    module: str
    name: str
    title: str | None
    description: str | None
    permission: Permission | None


@dataclass(frozen=True, slots=True)
class _Output:
    """How a declared return type becomes ``structuredContent`` (spec: it MUST match ``outputSchema``).

    ``dump`` checks the value against the declared type before turning it into JSON-ready data, as the
    official SDK does, and raises when it does not match: a client checks ``structuredContent`` against
    the schema, so a mismatch would otherwise fail there, with nothing in this server's log.
    """

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
        try:
            structured = self.output.dump(value)
        except (ValidationError, msgspec.ValidationError) as exc:
            raise TypeError(f"MCP tool {self.name!r} returned a value that does not match its return type: {exc}") from exc
        plain = structured["result"] if self.output.wrapped else structured
        text = plain if isinstance(plain, str) else json.dumps(plain, ensure_ascii=False)
        # spec: "a tool that returns structured content SHOULD also return the serialized JSON in a TextContent block".
        return types.CallToolResult(content=[types.TextContent(text=text)], structured_content=structured)


class _NoSchema(Exception):
    """msgspec cannot describe a return type as JSON Schema; the message says why."""


class ResourceNotFound(Exception):
    """The URI names no resource this service offers (or none this caller may read)."""


@dataclass(frozen=True, slots=True)
class Resource:
    """A fixed resource (its URI has no variables) or a template (``{name}`` variables become arguments)."""

    function: Callable[..., Awaitable[Any]]
    permission: Permission | None
    takes_request: bool
    mime_type: str | None
    pattern: re.Pattern[str] | None
    variables: dict[str, TypeAdapter[Any]]
    wire: types.Resource | types.ResourceTemplate

    def match(self, uri: str) -> dict[str, Any] | None:
        """The arguments this URI gives the function, or None when the URI is not this resource's."""
        if self.pattern is None:
            return {} if isinstance(self.wire, types.Resource) and uri == self.wire.uri else None
        found = self.pattern.fullmatch(uri)
        if found is None:
            return None
        try:
            return {name: adapter.validate_python(unquote(found[name])) for name, adapter in self.variables.items()}
        except ValidationError:
            return None  # A variable of the wrong type names no resource: answered as not found.

    def contents(self, uri: str, value: Any) -> list[types.TextResourceContents | types.BlobResourceContents]:
        """The function's return value as resource contents; None means the resource does not exist."""
        if value is None:
            # spec server/resources: servers MUST NOT return an empty contents array for a non-existent resource.
            raise ResourceNotFound(uri)
        if isinstance(value, _RESOURCE_CONTENTS):
            return [value]
        if isinstance(value, list | tuple) and value and all(isinstance(item, _RESOURCE_CONTENTS) for item in value):
            return list(value)
        if isinstance(value, bytes):
            return [
                types.BlobResourceContents(
                    uri=uri, mime_type=self.mime_type or "application/octet-stream", blob=base64.b64encode(value).decode("ascii")
                )
            ]
        if isinstance(value, str):
            return [types.TextResourceContents(uri=uri, mime_type=self.mime_type or "text/plain", text=value)]
        plain = value.model_dump(mode="json") if isinstance(value, BaseModel) else msgspec.to_builtins(value)
        return [types.TextResourceContents(uri=uri, mime_type=self.mime_type or "application/json", text=json.dumps(plain, ensure_ascii=False))]


@dataclass(frozen=True, slots=True)
class Prompt:
    """A prompt: string arguments in, messages out."""

    name: str
    function: Callable[..., Awaitable[Any]]
    permission: Permission | None
    takes_request: bool
    arguments: type[BaseModel]
    wire: types.Prompt

    def result(self, value: Any) -> types.GetPromptResult:
        """A ``str`` is one user message; a list of ``PromptMessage`` is used as it is."""
        if isinstance(value, str):
            messages = [types.PromptMessage(role="user", content=types.TextContent(text=value))]
        elif isinstance(value, list | tuple) and all(isinstance(message, types.PromptMessage) for message in value):
            messages = list(value)
        else:
            raise TypeError(f"MCP prompt {self.name!r} returned {type(value).__name__}; return a str or a list of PromptMessage")
        return types.GetPromptResult(description=self.wire.description, messages=messages)


@dataclass(frozen=True, slots=True)
class McpCatalog:
    """What one service offers, each kind in declaration order (spec: lists SHOULD be deterministic)."""

    tools: dict[str, Tool]
    resources: tuple[Resource, ...] = ()
    prompts: dict[str, Prompt] = dataclasses.field(default_factory=dict)


class McpRegistry:
    """Where Apps declare what they offer. The process-wide instance is ``oldman.mcp.mcp``."""

    __slots__ = ("_prompts", "_resources", "_tools")

    def __init__(self) -> None:
        self._tools: list[_ToolDeclaration] = []
        self._resources: list[_ResourceDeclaration] = []
        self._prompts: list[_PromptDeclaration] = []

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
            _check_declaration("tool", function, permission)
            tool_name = function.__name__ if name is None else name
            if _TOOL_NAME.fullmatch(tool_name) is None:
                raise ValueError(f"MCP tool name {tool_name!r} must be 1 to 128 of A-Z, a-z, 0-9, '_', '-' and '.'")
            self._tools.append(
                _ToolDeclaration(
                    function=function,
                    module=_declaring_module(),
                    name=tool_name,
                    title=title,
                    description=inspect.getdoc(function) if description is None else description,
                    annotations=annotations,
                    permission=permission,
                )
            )
            return function

        return decorator

    def resource(
        self,
        uri: str,
        *,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        mime_type: str | None = None,
        permission: Permission | None = None,
    ) -> Callable[[_Function], _Function]:
        """Offer an async function as a resource; the function is returned unchanged.

        A URI with ``{name}`` variables is a template (``resources/templates/list``): each variable is a
        parameter of the function, converted by its annotation. Without variables the URI is one fixed
        resource (``resources/list``). Return ``str`` for text, ``bytes`` for binary, a model or a dict for
        JSON, or None when the record does not exist. ``permission`` works as for tools.
        """

        def decorator(function: _Function) -> _Function:
            _check_declaration("resource", function, permission)
            _template_variables(uri)  # refuses what this server cannot match before anything is built
            self._resources.append(
                _ResourceDeclaration(
                    function=function,
                    module=_declaring_module(),
                    uri=uri,
                    name=function.__name__ if name is None else name,
                    title=title,
                    description=inspect.getdoc(function) if description is None else description,
                    mime_type=mime_type,
                    permission=permission,
                )
            )
            return function

        return decorator

    def prompt(
        self,
        name: str | None = None,
        *,
        title: str | None = None,
        description: str | None = None,
        permission: Permission | None = None,
    ) -> Callable[[_Function], _Function]:
        """Offer an async function as a prompt; the function is returned unchanged.

        Its parameters are the prompt's arguments and must be ``str`` (the protocol passes strings); one
        with a default is optional. Return a ``str`` (one user message) or a list of ``PromptMessage``.
        """

        def decorator(function: _Function) -> _Function:
            _check_declaration("prompt", function, permission)
            prompt_name = function.__name__ if name is None else name
            if not prompt_name:
                raise ValueError("An MCP prompt needs a name")
            self._prompts.append(
                _PromptDeclaration(
                    function=function,
                    module=_declaring_module(),
                    name=prompt_name,
                    title=title,
                    description=inspect.getdoc(function) if description is None else description,
                    permission=permission,
                )
            )
            return function

        return decorator

    def catalog(self, packages: Sequence[str]) -> McpCatalog:
        """Build what a service installing ``packages`` offers.

        A declaration made outside those packages is left out with a WARNING: an App that is not
        installed here must not have what it declares offered because some other module imported it.
        Either the module that declared it (that called ``mcp.tool()`` and the like) or the module that
        defines the function may belong to an installed App: an App may offer a function it imports, and
        a helper outside the Apps may declare an App's function for it. Two tools or prompts with one
        name, two resources with one URI, or two templates of the same shape stop here, naming both modules.
        """
        tools: dict[str, Tool] = {}
        tool_modules: dict[str, str] = {}
        for declaration in self._tools:
            if not _installed("tool", declaration.name, declaration.module, declaration.function, packages):
                continue
            if declaration.name in tools:
                raise ValueError(_twice("tool", declaration.name, tool_modules[declaration.name], declaration.module))
            tools[declaration.name] = _build_tool(declaration)
            tool_modules[declaration.name] = declaration.module

        resources: list[Resource] = []
        resource_modules: dict[str, str] = {}
        for declaration in self._resources:
            if not _installed("resource", declaration.uri, declaration.module, declaration.function, packages):
                continue
            # A fixed URI is its own key; templates that differ only in their variable names match the same URIs.
            key = _TEMPLATE_VARIABLE.sub("{}", declaration.uri)
            if key in resource_modules:
                raise ValueError(_twice("resource", declaration.uri, resource_modules[key], declaration.module))
            resources.append(_build_resource(declaration))
            resource_modules[key] = declaration.module
        # Fixed resources first: a URI that is fixed and also matches a template is the fixed one.
        resources.sort(key=lambda resource: resource.pattern is not None)

        prompts: dict[str, Prompt] = {}
        prompt_modules: dict[str, str] = {}
        for declaration in self._prompts:
            if not _installed("prompt", declaration.name, declaration.module, declaration.function, packages):
                continue
            if declaration.name in prompts:
                raise ValueError(_twice("prompt", declaration.name, prompt_modules[declaration.name], declaration.module))
            prompts[declaration.name] = _build_prompt(declaration)
            prompt_modules[declaration.name] = declaration.module
        return McpCatalog(tools=tools, resources=tuple(resources), prompts=prompts)


def _check_declaration(kind: str, function: Callable[..., Any], permission: Permission | None) -> None:
    # Checked through Any: iscoroutinefunction narrows its argument's type.
    if not inspect.iscoroutinefunction(cast("Any", function)):
        raise TypeError(f"MCP {kind} {function.__qualname__!r} must be an async function: a sync one would block the worker's event loop")
    if permission is not None and not isinstance(permission, Permission):
        raise TypeError("permission takes a declared Permission, not a name")


def _declaring_module() -> str:
    """The module whose code called the decorator: frame 0 is this function, 1 the decorator, 2 its caller.

    The function's own ``__module__`` names where it is defined, which differs when an App offers a
    function it imports; only the calling frame knows which module declared it. Neither alone is
    enough: a helper outside the Apps may be the one that calls the decorator, for an App's function.
    """
    return sys._getframe(2).f_globals.get("__name__", "")


def _installed(kind: str, name: str, module: str, function: Callable[..., Any], packages: Sequence[str]) -> bool:
    """Whether the declaring module or the function's own module belongs to one of the installed Apps."""
    defined_in = function.__module__
    if any(candidate == package or candidate.startswith(f"{package}.") for candidate in (module, defined_in) for package in packages):
        return True
    if defined_in == module:
        logger.warning(f"MCP {kind} {name!r} declared in {module!r} is not offered: that module belongs to no installed App")
    else:
        logger.warning(
            f"MCP {kind} {name!r} declared in {module!r} and defined in {defined_in!r} is not offered: neither module belongs to an installed App"
        )
    return False


def _twice(kind: str, name: str, first: str, second: str) -> str:
    return f"MCP {kind} {name!r} is declared twice: in {first!r} and in {second!r}"


def _parameters(kind: str, function: Callable[..., Any], hints: dict[str, Any]) -> tuple[bool, list[inspect.Parameter]]:
    """Whether the function takes the request first, and its other parameters (which must be named ones)."""
    parameters = list(inspect.signature(function).parameters.values())
    takes_request = bool(parameters) and _bare(hints.get(parameters[0].name)) is Request
    rest = parameters[1:] if takes_request else parameters
    for parameter in rest:
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD, inspect.Parameter.POSITIONAL_ONLY):
            raise TypeError(
                f"MCP {kind} {function.__qualname__!r}: parameter {parameter.name!r} must be a named parameter, not *args, **kwargs or positional-only"
            )
    return takes_request, rest


def _build_tool(declaration: _ToolDeclaration) -> Tool:
    function = declaration.function
    hints = _type_hints("tool", function)
    takes_request, parameters = _parameters("tool", function, hints)
    fields: dict[str, Any] = {}
    for parameter in parameters:
        annotation = hints.get(parameter.name, Any)
        default = ... if parameter.default is inspect.Parameter.empty else parameter.default
        fields[parameter.name] = (annotation, default)
    # Extra arguments are refused, not dropped: the model learns from the error what the tool takes.
    # For a tool without parameters this gives the schema the spec recommends ("additionalProperties": false).
    try:
        arguments = _arguments("tool", declaration.name, function, f"{declaration.name}_arguments", fields)
        input_schema = arguments.model_json_schema()
        output = _output(function, hints)
    except (PydanticSchemaGenerationError, _NoSchema) as exc:
        raise TypeError(
            f"MCP tool {declaration.name!r} in {function.__module__!r}: a type in its signature has no JSON schema "
            f"({str(exc).splitlines()[0]}). Parameters take types pydantic knows; a return type is described by pydantic, "
            "or by msgspec when it contains a msgspec Struct, and one return type cannot mix pydantic models with Structs."
        ) from exc
    wire = types.Tool(
        name=declaration.name,
        title=declaration.title,
        description=declaration.description,
        input_schema=input_schema,
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


def _build_resource(declaration: _ResourceDeclaration) -> Resource:
    function = declaration.function
    hints = _type_hints("resource", function)
    takes_request, parameters = _parameters("resource", function, hints)
    variables = _template_variables(declaration.uri)
    names = [parameter.name for parameter in parameters]
    if sorted(names) != sorted(variables):
        raise TypeError(
            f"MCP resource {declaration.uri!r}: {function.__qualname__!r} takes {names or 'no parameters'} "
            f"but the URI has the variables {variables or 'none'}; each variable must be one parameter"
        )
    common = {"name": declaration.name, "title": declaration.title, "description": declaration.description, "mime_type": declaration.mime_type}
    if not variables:
        return Resource(
            function=function,
            permission=declaration.permission,
            takes_request=takes_request,
            mime_type=declaration.mime_type,
            pattern=None,
            variables={},
            wire=types.Resource(uri=declaration.uri, **common),
        )
    # Each variable matches one path segment: simple RFC 6570 expansion percent-encodes "/" inside a value.
    pieces = re.split(r"(\{[A-Za-z_][A-Za-z0-9_]*\})", declaration.uri)
    pattern = "".join(f"(?P<{piece[1:-1]}>[^/]+)" if _TEMPLATE_VARIABLE.fullmatch(piece) else re.escape(piece) for piece in pieces)
    return Resource(
        function=function,
        permission=declaration.permission,
        takes_request=takes_request,
        mime_type=declaration.mime_type,
        pattern=re.compile(pattern),
        variables={name: _variable(declaration.uri, function, name, hints.get(name, str)) for name in variables},
        wire=types.ResourceTemplate(uri_template=declaration.uri, **common),
    )


def _arguments(kind: str, name: str, function: Callable[..., Any], model_name: str, fields: dict[str, Any]) -> type[BaseModel]:
    """The model a tool's or prompt's arguments are checked with; every parameter must be one of its fields.

    pydantic takes no field named with a leading ``_`` or ``model_config`` (it drops them without a word)
    and refuses a name a BaseModel member has, such as ``model_dump``. Dropped, a parameter would vanish
    from the schema, every call passing it would be refused, and a required one would fail every call.
    """
    try:
        model = create_model(model_name, __config__=ConfigDict(extra="forbid"), **fields)
    except ValueError as exc:  # pydantic: "Field 'model_dump' conflicts with member ..."
        raise TypeError(f"MCP {kind} {name!r} in {function.__module__!r}: {str(exc).splitlines()[0]}; rename that parameter") from exc
    dropped = sorted(set(fields) - set(model.model_fields))
    if dropped:
        raise TypeError(
            f"MCP {kind} {name!r} in {function.__module__!r}: parameter(s) {', '.join(map(repr, dropped))} cannot be arguments, since "
            "pydantic takes no field whose name starts with '_' or is 'model_config'; rename them"
        )
    return model


def _variable(uri: str, function: Callable[..., Any], name: str, annotation: Any) -> TypeAdapter[Any]:
    """How a URI variable is converted to its parameter's annotation."""
    try:
        return TypeAdapter(annotation)
    except PydanticSchemaGenerationError as exc:
        raise TypeError(
            f"MCP resource {uri!r} in {function.__module__!r}: the variable {name!r} has a type pydantic cannot convert a URI part to "
            f"({str(exc).splitlines()[0]})"
        ) from exc


def _template_variables(uri: str) -> list[str]:
    """The ``{name}`` variables of a URI, refusing any other use of braces."""
    if not uri:
        raise ValueError("An MCP resource needs a URI")
    variables = _TEMPLATE_VARIABLE.findall(uri)
    if "{" in _TEMPLATE_VARIABLE.sub("", uri) or "}" in _TEMPLATE_VARIABLE.sub("", uri):
        raise ValueError(f"MCP resource URI {uri!r}: only simple {{name}} variables are supported, not RFC 6570 operators such as {{+path}}")
    if len(set(variables)) != len(variables):
        raise ValueError(f"MCP resource URI {uri!r} repeats a variable")
    return variables


def _build_prompt(declaration: _PromptDeclaration) -> Prompt:
    function = declaration.function
    hints = _type_hints("prompt", function)
    takes_request, parameters = _parameters("prompt", function, hints)
    fields: dict[str, Any] = {}
    arguments: list[types.PromptArgument] = []
    for parameter in parameters:
        annotation = hints.get(parameter.name, str)
        if _bare(annotation) not in (str, str | None):
            raise TypeError(
                f"MCP prompt {declaration.name!r}: argument {parameter.name!r} must be a str, since the protocol passes prompt arguments as strings"
            )
        required = parameter.default is inspect.Parameter.empty
        fields[parameter.name] = (annotation, ... if required else parameter.default)
        arguments.append(types.PromptArgument(name=parameter.name, description=_description(annotation), required=required))
    return Prompt(
        name=declaration.name,
        function=function,
        permission=declaration.permission,
        takes_request=takes_request,
        arguments=_arguments("prompt", declaration.name, function, f"{declaration.name}_prompt_arguments", fields),
        wire=types.Prompt(name=declaration.name, title=declaration.title, description=declaration.description, arguments=arguments or None),
    )


def _description(annotation: Any) -> str | None:
    """The description an ``Annotated[str, Field(description=...)]`` argument carries."""
    if get_origin(annotation) is Annotated:
        for metadata in get_args(annotation)[1:]:
            if isinstance(metadata, FieldInfo) and metadata.description:
                return metadata.description
    return None


def _type_hints(kind: str, function: Callable[..., Any]) -> dict[str, Any]:
    try:
        return typing.get_type_hints(function, include_extras=True)
    except NameError as exc:
        raise TypeError(
            f"MCP {kind} {function.__qualname__!r} in {function.__module__!r}: cannot resolve the annotation {exc.name!r}. "
            f"Types in a {kind}'s signature become its schema, so they must be importable at run time, not only under TYPE_CHECKING."
        ) from exc


def _output(function: Callable[..., Any], hints: dict[str, Any]) -> _Output | None:
    """The output schema the official SDK would publish for this return type (its func_metadata rules).

    No return annotation, or content blocks: content only. Pydantic models, TypedDicts, dataclasses,
    msgspec Structs and ``dict[str, …]`` are objects as they are. Everything else, ``str`` and ``None``
    included, is wrapped as ``{"result": …}``. A return type that contains a msgspec Struct anywhere
    (``Struct | None``, ``list[Struct]``) is described and checked by msgspec, since pydantic has no
    schema for a Struct; the same rules decide what is wrapped.
    """
    if "return" not in hints:
        return None
    annotation = hints["return"]
    bare = _bare(annotation)
    if _is_content(bare):
        return None
    if _has_struct(bare):
        return _msgspec_output(function, annotation)
    if _is_object(bare):
        adapter = TypeAdapter(annotation)
        return _Output(
            schema=adapter.json_schema(), dump=lambda value: adapter.dump_python(adapter.validate_python(value), mode="json"), wrapped=False
        )
    wrapper = create_model(f"{function.__name__}_output", result=(annotation, ...))
    adapter = TypeAdapter(annotation)
    return _Output(
        schema=wrapper.model_json_schema(),
        dump=lambda value: {"result": adapter.dump_python(adapter.validate_python(value), mode="json")},
        wrapped=True,
    )


def _msgspec_output(function: Callable[..., Any], annotation: Any) -> _Output:
    """A return type with a msgspec Struct in it, described and checked by msgspec.

    msgspec answers a Struct (or a dataclass, a TypedDict) with ``{"$ref": "#/$defs/Name", "$defs": ...}``;
    the handshake revisions require an object schema (``"type": "object"``) at the root of
    ``outputSchema``, so the definition the root refers to is put at the root. ``$defs`` stays whole at
    the root, wrapped or not, so nested and recursive references still resolve.
    """
    try:
        schema = msgspec.json.schema(annotation)
    except TypeError as exc:  # a type msgspec does not know, such as a pydantic model beside a Struct
        raise _NoSchema(str(exc)) from exc
    definitions = schema.pop("$defs", None)
    reference = schema.pop("$ref", None)
    if isinstance(reference, str) and definitions is not None:
        schema.update(definitions[reference.rsplit("/", 1)[1]])

    def checked(value: Any) -> Any:
        return msgspec.to_builtins(msgspec.convert(value, annotation))

    bare = _bare(annotation)
    if (isinstance(bare, type) and issubclass(bare, msgspec.Struct)) or _is_object(bare):
        root, dump, wrapped = schema, checked, False
    else:
        root = {
            "title": f"{function.__name__}_output",
            "type": "object",
            "properties": {"result": {**schema, "title": "Result"}},
            "required": ["result"],
        }
        dump, wrapped = (lambda value: {"result": checked(value)}), True
    if definitions:
        root["$defs"] = definitions
    return _Output(schema=root, dump=dump, wrapped=wrapped)


def _has_struct(annotation: Any) -> bool:
    """Whether a msgspec Struct appears anywhere in the annotation."""
    annotation = _bare(annotation)
    if isinstance(annotation, type) and issubclass(annotation, msgspec.Struct):
        return True
    return any(_has_struct(argument) for argument in get_args(annotation))


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
        return [value]
    if isinstance(value, list | tuple) and all(isinstance(item, _CONTENT_TYPES) for item in value):
        return list(value)
    if isinstance(value, str):
        return [types.TextContent(text=value)]
    return [types.TextContent(text=json.dumps(msgspec.to_builtins(value), ensure_ascii=False))]


__all__ = ["McpCatalog", "McpRegistry", "Prompt", "Resource", "ResourceNotFound", "Tool", "ToolError"]
