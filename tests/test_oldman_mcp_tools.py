"""MCP tools: declaring them, the schemas they publish, calling them, and who may see them.

Also the import boundary: Oldman's own entry points never load ``oldman.mcp``, and ``oldman.mcp`` never
loads the ``mcp`` SDK (installed in the dev environment only, as the tests' client).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import subprocess
import sys
import textwrap
import types as pytypes
import unittest
from pathlib import Path
from typing import Any, TypedDict
from unittest.mock import AsyncMock, patch

import mcp_types as types
import msgspec
from pydantic import BaseModel
from sanic.exceptions import Forbidden, ServiceUnavailable

from oldman.auth.permissions import declare_permission
from oldman.mcp import McpRegistry, ToolAnnotations, ToolError
from oldman.mcp._server import McpServer
from oldman.web import Request
from oldman.web.authentication.base import Authentication, RequestUser, record_authentication

ROOT = Path(__file__).resolve().parents[1]
MODERN = "2026-07-28"
META = {"io.modelcontextprotocol/protocolVersion": MODERN, "io.modelcontextprotocol/clientCapabilities": {}}
VIEW_REPORTS = declare_permission("mcp_tests", "view_reports", "View reports")


class Point(BaseModel):
    x: int
    y: int


class Counts(TypedDict):
    total: int


@dataclasses.dataclass
class Pair:
    left: int
    right: int


class Size(msgspec.Struct):
    width: int
    height: int


def a_request(user: RequestUser | None = None, *, method: str = "jwt", caller: str | None = None) -> Any:
    request = pytypes.SimpleNamespace(ctx=pytypes.SimpleNamespace(), app=None)
    authentication = None
    if user is not None or caller is not None:
        authentication = (
            Authentication(method=method, user=user, caller=caller, ambient=False)
            if user
            else Authentication(method=method, caller=caller, ambient=False)
        )
    record_authentication(request, authentication)
    return request


SUPERUSER = RequestUser(id=1, username="root", display_name="Root", is_staff=True, is_superuser=True, role_ids=())
STAFF = RequestUser(id=2, username="ops", display_name="Ops", is_staff=True, is_superuser=False, role_ids=())


def call(server: McpServer, request: Any, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments or {}, "_meta": META}}
    headers = [("MCP-Protocol-Version", MODERN), ("Mcp-Method", "tools/call"), ("Mcp-Name", name)]
    reply = asyncio.run(server.handle(request, headers, json.dumps(body).encode(), "application/json"))
    assert reply.body is not None
    return reply.body


def listed(server: McpServer, request: Any) -> dict[str, dict[str, Any]]:
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": META}}
    headers = [("MCP-Protocol-Version", MODERN), ("Mcp-Method", "tools/list")]
    reply = asyncio.run(server.handle(request, headers, json.dumps(body).encode(), "application/json"))
    assert reply.body is not None
    return {tool["name"]: tool for tool in reply.body["result"]["tools"]}


def serve(registry: McpRegistry) -> McpServer:
    return McpServer(registry.catalog([__name__]), name="tools-test", version="0")


class SchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        registry = McpRegistry()

        @registry.tool(title="Adder", annotations=ToolAnnotations(read_only_hint=True))
        async def add(request: Request, a: int, b: int = 1) -> int:
            """Add two numbers."""
            return a + b

        @registry.tool()
        async def clock() -> str:
            """The time."""
            return "noon"

        self.tools = listed(serve(registry), a_request())

    def test_parameters_and_defaults_become_the_input_schema_and_the_request_is_left_out(self) -> None:
        schema = self.tools["add"]["inputSchema"]
        self.assertEqual({"a", "b"}, set(schema["properties"]))
        self.assertEqual(["a"], schema["required"])
        self.assertEqual(1, schema["properties"]["b"]["default"])
        self.assertIs(False, schema["additionalProperties"])

    def test_a_tool_without_parameters_takes_only_an_empty_object(self) -> None:
        """The schema the spec recommends for it: {"type": "object", "additionalProperties": false}."""
        schema = self.tools["clock"]["inputSchema"]
        self.assertEqual(("object", False, {}), (schema["type"], schema["additionalProperties"], schema.get("properties", {})))

    def test_docstring_title_and_annotations_are_published(self) -> None:
        self.assertEqual(
            ("Add two numbers.", "Adder", {"readOnlyHint": True}),
            (self.tools["add"]["description"], self.tools["add"]["title"], self.tools["add"]["annotations"]),
        )

    def test_tools_are_listed_in_declaration_order(self) -> None:
        self.assertEqual(["add", "clock"], list(self.tools))


class OutputTest(unittest.TestCase):
    """Return types publish the output schema the official SDK would, and results match it."""

    def setUp(self) -> None:
        registry = McpRegistry()

        @registry.tool()
        async def number() -> int:
            """An int."""
            return 3

        @registry.tool()
        async def word() -> str:
            """A str."""
            return "hi"

        @registry.tool()
        async def numbers() -> list[int]:
            """A list."""
            return [1, 2]

        @registry.tool()
        async def point() -> Point:
            """A pydantic model."""
            return Point(x=1, y=2)

        @registry.tool()
        async def counts() -> Counts:
            """A TypedDict."""
            return {"total": 4}

        @registry.tool()
        async def pair() -> Pair:
            """A dataclass."""
            return Pair(left=1, right=2)

        @registry.tool()
        async def size() -> Size:
            """A msgspec Struct."""
            return Size(width=3, height=4)

        @registry.tool()
        async def mapping() -> dict[str, int]:
            """A str-keyed dict."""
            return {"a": 1}

        @registry.tool()
        async def untyped():
            """No return annotation."""
            return {"free": True}

        @registry.tool()
        async def picture() -> types.TextContent:
            """A content block."""
            return types.TextContent(text="drawn")

        self.server = serve(registry)
        self.tools = listed(self.server, a_request())

    def result(self, name: str) -> dict[str, Any]:
        return call(self.server, a_request(), name)["result"]

    def test_primitives_and_generics_are_wrapped_in_result(self) -> None:
        for name, value in (("number", 3), ("word", "hi"), ("numbers", [1, 2])):
            with self.subTest(name=name):
                self.assertEqual(["result"], list(self.tools[name]["outputSchema"]["properties"]))
                self.assertEqual({"result": value}, self.result(name)["structuredContent"])
        self.assertEqual("hi", self.result("word")["content"][0]["text"])

    def test_objects_are_their_own_structured_content_with_the_same_json_as_text(self) -> None:
        expected = {
            "point": {"x": 1, "y": 2},
            "counts": {"total": 4},
            "pair": {"left": 1, "right": 2},
            "size": {"width": 3, "height": 4},
            "mapping": {"a": 1},
        }
        for name, value in expected.items():
            with self.subTest(name=name):
                self.assertIn("outputSchema", self.tools[name])
                result = self.result(name)
                self.assertEqual(value, result["structuredContent"])
                self.assertEqual(value, json.loads(result["content"][0]["text"]))

    def test_without_a_return_annotation_or_for_content_blocks_there_is_no_structured_output(self) -> None:
        for name, text in (("untyped", '{"free": true}'), ("picture", "drawn")):
            with self.subTest(name=name):
                self.assertNotIn("outputSchema", self.tools[name])
                result = self.result(name)
                self.assertNotIn("structuredContent", result)
                self.assertEqual(text, result["content"][0]["text"])


class CallTest(unittest.TestCase):
    def setUp(self) -> None:
        registry = McpRegistry()

        @registry.tool()
        async def whoami(request: Request) -> str:
            """The caller."""
            return request.ctx.user.username

        @registry.tool()
        async def add(a: int, b: int = 1) -> int:
            """Add."""
            return a + b

        @registry.tool()
        async def refuse() -> str:
            """Refuses."""
            raise ToolError("Not on Sundays")

        @registry.tool()
        async def forbidden() -> str:
            """Raises what a view would."""
            raise Forbidden("Permission denied")

        @registry.tool()
        async def broken() -> str:
            """Breaks."""
            raise RuntimeError("database password is hunter2")

        self.server = serve(registry)

    def test_the_request_reaches_a_tool_that_asks_for_it(self) -> None:
        self.assertEqual({"result": "ops"}, call(self.server, a_request(STAFF), "whoami")["result"]["structuredContent"])

    def test_bad_or_extra_arguments_are_a_tool_error_the_model_can_correct(self) -> None:
        for arguments, field in (({"a": "x"}, "a:"), ({"a": 1, "c": 2}, "c:"), ({}, "a:")):
            with self.subTest(arguments=arguments):
                result = call(self.server, a_request(), "add", arguments)["result"]
                self.assertTrue(result["isError"])
                self.assertIn(field, result["content"][0]["text"])

    def test_a_tool_error_and_a_web_exception_show_their_message(self) -> None:
        self.assertEqual("Not on Sundays", call(self.server, a_request(), "refuse")["result"]["content"][0]["text"])
        self.assertEqual("Permission denied", call(self.server, a_request(), "forbidden")["result"]["content"][0]["text"])

    def test_any_other_exception_is_logged_and_not_shown(self) -> None:
        with self.assertLogs("default.mcp", level="ERROR") as logs:
            result = call(self.server, a_request(), "broken")["result"]
        self.assertEqual((True, "The tool failed"), (result["isError"], result["content"][0]["text"]))
        self.assertIn("'broken'", logs.output[0])
        self.assertNotIn("hunter2", json.dumps(result))

    def test_an_unknown_tool_is_a_protocol_error(self) -> None:
        self.assertEqual(-32602, call(self.server, a_request(), "missing")["error"]["code"])


class PermissionTest(unittest.TestCase):
    """A tool with a permission is for the signed-in users who hold it; others neither see nor call it."""

    def setUp(self) -> None:
        registry = McpRegistry()

        @registry.tool(permission=VIEW_REPORTS)
        async def reports() -> str:
            """Reports."""
            return "all of them"

        @registry.tool()
        async def public() -> str:
            """For anyone admitted."""
            return "hello"

        self.server = serve(registry)

    def test_who_sees_which_tool(self) -> None:
        cases = {
            "superuser": (a_request(SUPERUSER), {"reports", "public"}),
            "user without the permission": (a_request(STAFF), {"public"}),
            "api key caller": (a_request(method="api_key", caller="monitor"), {"public"}),
            "anonymous": (a_request(), {"public"}),
        }
        for label, (request, names) in cases.items():
            with self.subTest(caller=label):
                self.assertEqual(names, set(listed(self.server, request)))

    def test_a_hidden_tool_is_answered_as_unknown(self) -> None:
        self.assertEqual("all of them", call(self.server, a_request(SUPERUSER), "reports")["result"]["content"][0]["text"])
        for request in (a_request(STAFF), a_request(method="api_key", caller="monitor"), a_request()):
            with self.subTest(request=request.ctx.auth):
                self.assertEqual(-32602, call(self.server, request, "reports")["error"]["code"])

    def test_an_unreachable_permission_store_is_reported_not_read_as_denied(self) -> None:
        with patch("oldman.mcp._server.has_perm", AsyncMock(side_effect=ServiceUnavailable("The permission store is unavailable"))):
            listing = asyncio.run(
                self.server.handle(
                    a_request(STAFF),
                    [("MCP-Protocol-Version", MODERN), ("Mcp-Method", "tools/list")],
                    json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": META}}).encode(),
                    "application/json",
                )
            )
            called = call(self.server, a_request(STAFF), "reports")
        assert listing.body is not None
        self.assertEqual(-32603, listing.body["error"]["code"])
        self.assertTrue(called["result"]["isError"])
        self.assertIn("unavailable", called["result"]["content"][0]["text"])


class DeclarationTest(unittest.TestCase):
    def test_only_async_functions_with_valid_names_are_accepted(self) -> None:
        registry = McpRegistry()

        def sync_tool() -> None:
            """Sync."""

        with self.assertRaisesRegex(TypeError, "async"):
            registry.tool()(sync_tool)  # type: ignore[arg-type]

        async def fine() -> None:
            """Fine."""

        for name in ("", "has space", "x" * 129, "名字"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                registry.tool(name)(fine)
        with self.assertRaisesRegex(TypeError, "Permission"):
            registry.tool(permission="mcp_tests.view_reports")(fine)  # type: ignore[arg-type]

    def test_two_tools_with_one_name_stop_the_catalog_and_both_modules_are_named(self) -> None:
        registry = McpRegistry()

        async def first() -> None:
            """One."""

        async def second() -> None:
            """Two."""

        second.__module__ = f"{__name__}.other"
        registry.tool("same")(first)
        registry.tool("same")(second)
        with self.assertRaisesRegex(ValueError, f"'{__name__}'.*'{__name__}.other'"):
            registry.catalog([__name__])

    def test_tools_outside_the_installed_apps_are_not_offered(self) -> None:
        registry = McpRegistry()

        async def foreign() -> None:
            """From an App this service does not install."""

        async def ours() -> None:
            """From an installed App."""

        foreign.__module__ = "apps.not_installed.mcp"
        registry.tool()(foreign)
        registry.tool()(ours)
        with self.assertLogs("default.mcp", level="WARNING") as logs:
            catalog = registry.catalog([__name__])
        self.assertEqual(["ours"], list(catalog.tools))
        self.assertIn("apps.not_installed.mcp", logs.output[0])

    def test_annotations_resolve_when_the_catalog_is_built_and_a_type_checking_import_is_reported(self) -> None:
        registry = McpRegistry()
        later = pytypes.ModuleType(f"{__name__}_later")
        later.__dict__["registry"] = registry
        exec(
            compile(
                textwrap.dedent(
                    """
                    from __future__ import annotations
                    from typing import TYPE_CHECKING
                    from pydantic import BaseModel

                    if TYPE_CHECKING:
                        from oldman.web import Request

                    @registry.tool()
                    async def forward(item: Item) -> Item:
                        '''Uses a model defined below the tool.'''
                        return item

                    class Item(BaseModel):
                        name: str

                    @registry.tool()
                    async def checked(request: Request) -> str:
                        '''Imports Request only for the type checker.'''
                        return ""
                    """
                ),
                "later.py",
                "exec",
            ),
            later.__dict__,
        )
        with self.assertRaisesRegex(TypeError, "cannot resolve the annotation 'Request'.*TYPE_CHECKING"):
            registry.catalog([later.__name__])


class ImportBoundaryTest(unittest.TestCase):
    """Adding MCP must not change what Oldman loads for services that do not use it."""

    def run_python(self, code: str) -> str:
        completed = subprocess.run([sys.executable, "-c", textwrap.dedent(code)], cwd=ROOT, capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(0, completed.returncode, completed.stderr)
        return completed.stdout.strip()

    def test_oldman_entry_points_do_not_load_mcp(self) -> None:
        loaded = self.run_python(
            """
            import sys
            import oldman, oldman.web, oldman.runtime, oldman.conf, oldman.apps, oldman.auth, oldman.cli
            print(sorted(name for name in ("oldman.mcp", "mcp_types", "mcp") if name in sys.modules))
            """
        )
        self.assertEqual("[]", loaded)

    def test_oldman_mcp_never_imports_the_sdk(self) -> None:
        loaded = self.run_python(
            """
            import asyncio, json, sys, types
            from oldman.mcp import McpRegistry
            from oldman.mcp._server import McpServer

            registry = McpRegistry()

            @registry.tool()
            async def ping() -> str:
                '''Pong.'''
                return "pong"

            server = McpServer(registry.catalog(["__main__"]), name="boundary", version="0")
            meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}
            body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "ping", "arguments": {}, "_meta": meta}}
            headers = [("MCP-Protocol-Version", "2026-07-28"), ("Mcp-Method", "tools/call"), ("Mcp-Name", "ping")]
            request = types.SimpleNamespace(ctx=types.SimpleNamespace(), app=None)
            reply = asyncio.run(server.handle(request, headers, json.dumps(body).encode(), "application/json"))
            assert reply.status == 200, reply
            print("mcp" in sys.modules, any(name == "mcp" or name.startswith("mcp.") for name in sys.modules))
            """
        )
        self.assertEqual("False False", loaded)


if __name__ == "__main__":
    unittest.main()
