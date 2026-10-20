"""MCP resources and prompts: declaring them, matching URIs, reading, getting, and who may see them."""

from __future__ import annotations

import asyncio
import base64
import json
import textwrap
import types as pytypes
import unittest
from typing import Annotated, Any

from pydantic import BaseModel, Field
from sanic.exceptions import Forbidden, NotFound, ServiceUnavailable

from oldman.auth.permissions import declare_permission
from oldman.mcp import McpRegistry, PromptMessage, TextContent
from oldman.mcp._server import McpServer
from oldman.web import Request
from oldman.web.authentication.base import Authentication, RequestUser, record_authentication

MODERN = "2026-07-28"
META = {"io.modelcontextprotocol/protocolVersion": MODERN, "io.modelcontextprotocol/clientCapabilities": {}}
READ_FILES = declare_permission("mcp_resource_tests", "read_files", "Read files")
SUPERUSER = RequestUser(id=1, username="root", display_name="Root", is_staff=True, is_superuser=True, role_ids=())
STAFF = RequestUser(id=2, username="ops", display_name="Ops", is_staff=True, is_superuser=False, role_ids=())


class Item(BaseModel):
    id: int
    name: str


def a_request(user: RequestUser | None = None) -> Any:
    request = pytypes.SimpleNamespace(ctx=pytypes.SimpleNamespace(), app=None)
    record_authentication(request, None if user is None else Authentication(method="jwt", user=user, ambient=False))
    return request


def rpc(server: McpServer, request: Any, method: str, params: dict[str, Any] | None = None, *, name: str | None = None) -> dict[str, Any]:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": {**(params or {}), "_meta": META}}
    headers = [("MCP-Protocol-Version", MODERN), ("Mcp-Method", method)]
    if name is not None:
        headers.append(("Mcp-Name", name))
    reply = asyncio.run(server.handle(request, headers, json.dumps(body).encode(), "application/json"))
    assert reply.body is not None
    return {"status": reply.status, **reply.body}


def read(server: McpServer, request: Any, uri: str) -> dict[str, Any]:
    return rpc(server, request, "resources/read", {"uri": uri}, name=uri)


def get_prompt(server: McpServer, request: Any, name: str, arguments: dict[str, str] | None = None) -> dict[str, Any]:
    return rpc(server, request, "prompts/get", {"name": name, "arguments": arguments or {}}, name=name)


def serve(registry: McpRegistry) -> McpServer:
    return McpServer(registry.catalog([__name__]), name="resources-test", version="0")


class ResourceTest(unittest.TestCase):
    def setUp(self) -> None:
        registry = McpRegistry()

        @registry.resource("notes://readme")
        async def readme() -> str:
            """The readme."""
            return "hello"

        @registry.resource("items://all", mime_type="application/x-ndjson")
        async def all_items() -> str:
            """Every item, one per line."""
            return '{"id": 1}\n{"id": 2}'

        @registry.resource("items://{item_id}")
        async def item(request: Request, item_id: int) -> Item | None:
            """One item."""
            return None if item_id == 404 else Item(id=item_id, name=request.ctx.user.username or "anyone")

        @registry.resource("items://special")
        async def special() -> dict[str, str]:
            """A fixed URI that a template would also match."""
            return {"kind": "special"}

        # Declared before the fixed page below, and its str variable matches "about" too.
        @registry.resource("pages://{slug}")
        async def page(slug: str) -> str:
            """Any page."""
            return f"page {slug}"

        @registry.resource("pages://about")
        async def about() -> str:
            """The about page, fixed."""
            return "about us"

        @registry.resource("files://{name}", permission=READ_FILES)
        async def file(name: str) -> bytes:
            """A file's bytes."""
            if name == "secret.txt":
                raise Forbidden("Permission denied")
            if name == "gone.txt":
                raise NotFound("No such file")
            return name.encode()

        @registry.resource("broken://{part}")
        async def broken(part: str) -> str:
            """Fails in the ways a store can."""
            if part == "down":
                raise ServiceUnavailable("The file store is unavailable")
            raise RuntimeError("disk path /srv/secret leaked")

        self.server = serve(registry)

    def test_fixed_resources_and_templates_are_listed_apart(self) -> None:
        fixed = rpc(self.server, a_request(SUPERUSER), "resources/list")["result"]["resources"]
        templates = rpc(self.server, a_request(SUPERUSER), "resources/templates/list")["result"]["resourceTemplates"]
        self.assertEqual(["notes://readme", "items://all", "items://special", "pages://about"], [resource["uri"] for resource in fixed])
        self.assertEqual(
            ["items://{item_id}", "pages://{slug}", "files://{name}", "broken://{part}"], [template["uriTemplate"] for template in templates]
        )
        self.assertEqual(("readme", "The readme.", "application/x-ndjson"), (fixed[0]["name"], fixed[0]["description"], fixed[1]["mimeType"]))

    def test_contents_follow_the_return_value(self) -> None:
        text = read(self.server, a_request(), "notes://readme")["result"]["contents"][0]
        self.assertEqual({"uri": "notes://readme", "mimeType": "text/plain", "text": "hello"}, text)
        declared = read(self.server, a_request(), "items://all")["result"]["contents"][0]
        self.assertEqual("application/x-ndjson", declared["mimeType"])
        model = read(self.server, a_request(STAFF), "items://7")["result"]["contents"][0]
        self.assertEqual(("application/json", {"id": 7, "name": "ops"}), (model["mimeType"], json.loads(model["text"])))
        blob = read(self.server, a_request(SUPERUSER), "files://a%20b.txt")["result"]["contents"][0]
        self.assertEqual(("application/octet-stream", b"a b.txt"), (blob["mimeType"], base64.b64decode(blob["blob"])))

    def test_a_fixed_uri_wins_over_a_template_that_also_matches(self) -> None:
        contents = read(self.server, a_request(), "items://special")["result"]["contents"][0]
        self.assertEqual({"kind": "special"}, json.loads(contents["text"]))
        # The template is declared first and its str variable would take "about": the fixed page still wins.
        self.assertEqual("about us", read(self.server, a_request(), "pages://about")["result"]["contents"][0]["text"])
        self.assertEqual("page contact", read(self.server, a_request(), "pages://contact")["result"]["contents"][0]["text"])

    def test_missing_resources_are_invalid_params_with_the_uri_and_never_empty_contents(self) -> None:
        for uri in ("nowhere://x", "items://404", "items://not-a-number", "files://gone.txt"):
            with self.subTest(uri=uri):
                reply = read(self.server, a_request(SUPERUSER), uri)
                self.assertEqual(
                    (400, -32602, "Resource not found", {"uri": uri}),
                    (reply["status"], reply["error"]["code"], reply["error"]["message"], reply["error"]["data"]),
                )

    def test_a_resource_with_a_permission_is_for_its_holders_only(self) -> None:
        self.assertNotIn(
            "files://{name}",
            [t["uriTemplate"] for t in rpc(self.server, a_request(STAFF), "resources/templates/list")["result"]["resourceTemplates"]],
        )
        self.assertEqual(-32602, read(self.server, a_request(STAFF), "files://a.txt")["error"]["code"])
        # A record the function itself refuses reads the same as one that does not exist.
        self.assertEqual(-32602, read(self.server, a_request(SUPERUSER), "files://secret.txt")["error"]["code"])

    def test_failures_are_internal_errors_and_unexpected_ones_are_logged_not_shown(self) -> None:
        down = read(self.server, a_request(), "broken://down")
        self.assertEqual((-32603, "The file store is unavailable"), (down["error"]["code"], down["error"]["message"]))
        with self.assertLogs("default.mcp", level="ERROR") as logs:
            crashed = read(self.server, a_request(), "broken://other")
        self.assertEqual((-32603, "Internal error"), (crashed["error"]["code"], crashed["error"]["message"]))
        self.assertNotIn("/srv/secret", json.dumps(crashed))
        self.assertIn("broken://other", logs.output[0])


class PromptTest(unittest.TestCase):
    def setUp(self) -> None:
        registry = McpRegistry()

        @registry.prompt(title="Weekly report")
        async def weekly_report(week: Annotated[str, Field(description="ISO week, e.g. 2026-W43")], tone: str = "plain") -> str:
            """Ask for a weekly report."""
            return f"Summarise week {week} in a {tone} tone."

        @registry.prompt()
        async def conversation(request: Request) -> list[PromptMessage]:
            """Two turns."""
            return [
                PromptMessage(role="user", content=TextContent(text=f"I am {request.ctx.user.username}.")),
                PromptMessage(role="assistant", content=TextContent(text="Noted.")),
            ]

        @registry.prompt(permission=READ_FILES)
        async def file_review() -> str:
            """For holders only."""
            return "Review the files."

        @registry.prompt()
        async def wrong() -> str:
            """Returns something a prompt cannot be."""
            return 42  # type: ignore[return-value]

        self.server = serve(registry)

    def test_prompts_are_listed_with_their_arguments(self) -> None:
        prompts = {prompt["name"]: prompt for prompt in rpc(self.server, a_request(STAFF), "prompts/list")["result"]["prompts"]}
        self.assertEqual({"weekly_report", "conversation", "wrong"}, set(prompts))
        self.assertEqual(
            [{"name": "week", "description": "ISO week, e.g. 2026-W43", "required": True}, {"name": "tone", "required": False}],
            prompts["weekly_report"]["arguments"],
        )
        self.assertEqual(("Weekly report", "Ask for a weekly report."), (prompts["weekly_report"]["title"], prompts["weekly_report"]["description"]))
        self.assertNotIn("arguments", prompts["conversation"])

    def test_a_str_is_one_user_message_and_a_list_is_used_as_it_is(self) -> None:
        single = get_prompt(self.server, a_request(), "weekly_report", {"week": "2026-W43"})["result"]
        self.assertEqual([{"role": "user", "content": {"type": "text", "text": "Summarise week 2026-W43 in a plain tone."}}], single["messages"])
        turns = get_prompt(self.server, a_request(STAFF), "conversation")["result"]["messages"]
        self.assertEqual([("user", "I am ops."), ("assistant", "Noted.")], [(message["role"], message["content"]["text"]) for message in turns])

    def test_unknown_hidden_or_badly_called_prompts_are_invalid_params(self) -> None:
        cases = {
            "unknown": ("missing", {}, a_request(SUPERUSER)),
            "hidden": ("file_review", {}, a_request(STAFF)),
            "required argument missing": ("weekly_report", {}, a_request()),
            "unknown argument": ("weekly_report", {"week": "1", "colour": "red"}, a_request()),
        }
        for label, (name, arguments, request) in cases.items():
            with self.subTest(case=label):
                self.assertEqual(-32602, get_prompt(self.server, request, name, arguments)["error"]["code"])
        self.assertIn("Review", get_prompt(self.server, a_request(SUPERUSER), "file_review")["result"]["messages"][0]["content"]["text"])

    def test_a_prompt_that_returns_something_else_is_an_internal_error(self) -> None:
        with self.assertLogs("default.mcp", level="ERROR"):
            self.assertEqual(-32603, get_prompt(self.server, a_request(), "wrong")["error"]["code"])


class CapabilityTest(unittest.TestCase):
    def test_resources_and_prompts_are_declared_and_served_only_when_there_are_some(self) -> None:
        registry = McpRegistry()

        @registry.tool()
        async def only_a_tool() -> str:
            """The service offers nothing else."""
            return "ok"

        server = serve(registry)
        capabilities = rpc(server, a_request(), "server/discover")["result"]["capabilities"]
        self.assertEqual({"tools": {}}, capabilities)
        for method in ("resources/list", "resources/templates/list", "prompts/list"):
            with self.subTest(method=method):
                self.assertEqual((404, -32601), (rpc(server, a_request(), method)["status"], rpc(server, a_request(), method)["error"]["code"]))

        registry.resource("x://y")(_async_text)
        registry.prompt()(_async_text)
        self.assertEqual(
            {"tools": {}, "resources": {}, "prompts": {}}, rpc(serve(registry), a_request(), "server/discover")["result"]["capabilities"]
        )


async def _async_text() -> str:
    """Text."""
    return "text"


class DeclarationTest(unittest.TestCase):
    def test_uri_templates_take_only_simple_variables_that_match_the_parameters(self) -> None:
        registry = McpRegistry()
        for uri in ("files://{+path}", "files://{name}/{name}", "files://{name", "files://name}"):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                registry.resource(uri)(_async_text)

        async def two(a: str, b: str) -> str:
            """Takes a variable the URI does not have."""
            return a + b

        registry.resource("pairs://{a}")(two)
        with self.assertRaisesRegex(TypeError, "each variable must be one parameter"):
            registry.catalog([__name__])

    def test_resources_with_one_uri_or_one_shape_and_prompts_with_one_name_stop_the_catalog(self) -> None:
        async def first(x: str) -> str:
            """One."""
            return x

        async def second(y: str) -> str:
            """Two."""
            return y

        cases = {
            "same fixed URI": ("resource", "a://b", _async_text, "a://b", _async_text),
            "templates of one shape": ("resource", "a://{x}", first, "a://{y}", second),
            "same prompt name": ("prompt", "p", _async_text, "p", _async_text),
        }
        for label, (kind, key, function, other_key, other_function) in cases.items():
            with self.subTest(case=label):
                registry = McpRegistry()
                getattr(registry, kind)(key)(function)
                # The second one is declared by another App's module: the message names both declaring modules.
                namespace = {"__name__": f"{__name__}.other", "registry": registry, "function": other_function}
                exec(textwrap.dedent(f"registry.{kind}({other_key!r})(function)"), namespace)
                with self.assertRaisesRegex(ValueError, f"declared twice: in '{__name__}' and in '{__name__}.other'"):
                    registry.catalog([__name__])

    def test_prompt_arguments_must_be_strings(self) -> None:
        registry = McpRegistry()

        async def numbered(count: int) -> str:
            """Takes an int."""
            return str(count)

        registry.prompt()(numbered)
        with self.assertRaisesRegex(TypeError, "must be a str"):
            registry.catalog([__name__])

    def test_resources_and_prompts_must_be_async(self) -> None:
        def sync() -> str:
            return ""

        registry = McpRegistry()
        with self.assertRaisesRegex(TypeError, "async"):
            registry.resource("a://b")(sync)  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, "async"):
            registry.prompt()(sync)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
