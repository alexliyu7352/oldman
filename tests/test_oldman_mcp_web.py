"""``install_mcp``: the MCP endpoint on a real Sanic server, behind Oldman's authentication pipeline.

The official SDK client connects in its three modes; raw HTTP requests cover what a lenient client never
sends — an Origin from elsewhere, a browser credential, an oversized body, the GET stream. Redis is a
test-owned server, never the developer's own.
"""

from __future__ import annotations

import importlib
import json
import socket
import sys
import tempfile
import textwrap
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import httpx2
import mcp_types
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from redis.exceptions import ConnectionError as RedisConnectionError
from sanic import Sanic

import oldman.conf as conf
from oldman.conf.schemas import APIKeyConfig, DefaultSettings
from oldman.mcp import install_mcp
from oldman.providers.redis.client import RedisClientRegistry
from oldman.web.authentication import JWTAuthentication, install_authentication, issue_access_token
from oldman.web.authentication.api_key import APIKeyAuthentication
from oldman.web.authentication.base import Authentication, RequestUser
from tests.redis_support import RedisProcess, owned_redis_config, require_redis_server

ROOT = Path(__file__).resolve().parents[1]
SECRET = "mcp-endpoint-test-secret-0123456789abcdef"
AGENT_KEY = "agent-key-0123456789abcdef0123456789"
MONITOR_KEY = "monitor-key-0123456789abcdef012345678"
MODERN = "2026-07-28"
APP_FILES = {
    "mcp_web_app/__init__.py": "",
    "mcp_web_app/apps.py": """
        from oldman.apps import AppConfig

        class Config(AppConfig):
            label = "mcp_web_app"
            display_name = "MCP endpoint tests"

        app = Config()
    """,
    "mcp_web_app/mcp.py": """
        from oldman.auth.permissions import declare_permission
        from oldman.mcp import mcp
        from oldman.web import Request

        VIEW_SECRET = declare_permission("mcp_web_app", "view_secret", "View the secret")

        @mcp.tool()
        async def whoami(request: Request) -> str:
            '''Name the caller.'''
            return request.ctx.auth.caller or request.ctx.user.username if request.ctx.auth else "anonymous"

        @mcp.tool()
        async def add(a: int, b: int = 1) -> int:
            '''Add two numbers.'''
            return a + b

        @mcp.tool(permission=VIEW_SECRET)
        async def secret() -> str:
            '''Only for users who hold the permission.'''
            return "42"

        @mcp.resource("notes://{note_id}")
        async def note(note_id: int) -> dict:
            '''One note.'''
            return {"id": note_id}

        @mcp.prompt()
        async def summarise(topic: str) -> str:
            '''Ask for a summary.'''
            return f"Summarise {topic}."
    """,
    "uninstalled_mcp_app/__init__.py": "",
    "uninstalled_mcp_app/mcp.py": "raise AssertionError('install_mcp imported an App that is not installed')",
}
SUPERUSER = SimpleNamespace(id=1, username="root", display_name="Root", is_active=True, is_staff=True, is_superuser=True)
PLAIN_USER = SimpleNamespace(id=2, username="plain", display_name="Plain", is_active=True, is_staff=False, is_superuser=False)


class FakeSession:
    """A browser credential as the pipeline records it: ambient, naming a signed-in user."""

    name = "session"

    async def authenticate(self, request: Any) -> Authentication | None:
        if request.headers.get("x-test-session") != "yes":
            return None
        user = RequestUser(id=1, username="root", display_name="Root", is_staff=True, is_superuser=True, role_ids=())
        return Authentication(method="session", user=user, ambient=True)


def settings_for(**mcp: Any) -> DefaultSettings:
    settings = DefaultSettings()
    settings.core.namespace = "mcp_web_test"
    settings.core.app_name = "mcp-web-test"
    settings.web.auth.authenticators = ["jwt", "api_key"]
    settings.web.auth.jwt.secret = SECRET
    settings.web.auth.api_keys = {"agent": APIKeyConfig(secret=AGENT_KEY), "monitor": APIKeyConfig(secret=MONITOR_KEY)}
    settings.web.mcp.enabled = True
    settings.web.mcp.callers = ["agent"]
    for name, value in mcp.items():
        if name == "rate_limit":
            for field, field_value in value.items():
                setattr(settings.web.mcp.rate_limit, field, field_value)
        else:
            setattr(settings.web.mcp, name, value)
    return settings


class InstalledApps:
    """The two things install_mcp asks of the service's App registry: the packages, and loading their mcp modules.

    A real AppRegistry would check every mapped class in this process belongs to an installed App, and the
    full suite has other modules' test models on the shared metadata. Loading itself is tested on a real
    Registry in test_oldman_app_registry, in its own process.
    """

    packages = ("mcp_web_app",)

    def __init__(self) -> None:
        self.loads = 0

    def load_mcp(self) -> None:
        self.loads += 1
        importlib.import_module("mcp_web_app.mcp")


class _Module:
    """What every test here shares: the App package on disk and a test-owned Redis."""

    temporary_directory: tempfile.TemporaryDirectory[str]
    redis_process: RedisProcess
    app_registry: InstalledApps


def setUpModule() -> None:
    _Module.temporary_directory = tempfile.TemporaryDirectory()
    root = Path(_Module.temporary_directory.name)
    for relative, source in APP_FILES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source), encoding="utf-8")
    sys.path.insert(0, str(root))
    _Module.redis_process = RedisProcess(require_redis_server(), root, "mcp-endpoint")
    _Module.app_registry = InstalledApps()


def tearDownModule() -> None:
    _Module.redis_process.stop()
    sys.path.remove(_Module.temporary_directory.name)
    _Module.temporary_directory.cleanup()


class EndpointTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.app_registry = _Module.app_registry
        self.redis = RedisClientRegistry(owned_redis_config(_Module.redis_process.socket_path, {"SESSION": 5}))
        self.enterContext(patch("oldman.providers.redis.redis_client", self.redis))
        self.servers: list[Any] = []

    async def asyncTearDown(self) -> None:
        for server, app in self.servers:
            server.close()
            await server.wait_closed()
            Sanic.unregister_app(app)
        connection = await self.redis.using("SESSION").async_get_conn()
        await connection.flushdb()
        await self.redis.close()

    async def serve(self, settings: DefaultSettings, *, extra_authenticators: tuple[Any, ...] = (), csrf: bool = False) -> str:
        self.enterContext(patch.dict(conf.__dict__, {"settings": settings}))
        app = Sanic(f"mcp_endpoint_{len(self.servers)}_{id(self)}")
        app.config.TOUCHUP = False
        app.config.AUTO_EXTEND = False
        app.config.ACCESS_LOG = False
        app.ctx.app_registry = self.app_registry
        install_authentication(app, (*extra_authenticators, JWTAuthentication(), APIKeyAuthentication()))
        if csrf:
            from oldman.web.security.csrf import StatelessCSRFManager

            manager = StatelessCSRFManager()
            app.ctx.csrf = manager
            manager.register_enforcement(app)
        install_mcp(app)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        server = await app.create_server(sock=sock, access_log=False, return_asyncio_server=True)
        assert server is not None
        await server.startup()
        serving = server.start_serving()  # Sanic types these as maybe None: it returns None before the server exists.
        assert serving is not None
        await serving
        self.servers.append((server, app))
        return f"http://127.0.0.1:{sock.getsockname()[1]}{settings.web.mcp.path}"

    @staticmethod
    def bearer(user: SimpleNamespace) -> dict[str, str]:
        return {"Authorization": f"Bearer {issue_access_token(user).token}"}

    @staticmethod
    async def post(url: str, body: Any, headers: dict[str, str] | None = None, **kwargs: Any) -> httpx.Response:
        merged = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", **(headers or {})}
        async with httpx.AsyncClient(trust_env=False) as client:
            return await client.post(url, json=body, headers=merged, **kwargs)

    @staticmethod
    async def call_tool(url: str, name: str, arguments: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments,
                "_meta": {"io.modelcontextprotocol/protocolVersion": MODERN, "io.modelcontextprotocol/clientCapabilities": {}},
            },
        }
        protocol = {"MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/call", "Mcp-Name": name}
        response = await EndpointTestCase.post(url, body, {**protocol, **headers})
        assert response.status_code == 200, response.text
        return response.json()["result"]


class OfficialClientTest(EndpointTestCase):
    async def connect(self, url: str, headers: dict[str, str], mode: str) -> tuple[list[str], Any, Any]:
        async with httpx2.AsyncClient(headers=headers, trust_env=False) as http:
            async with Client(streamable_http_client(url, http_client=http), mode=mode) as client:
                names = [tool.name for tool in (await client.list_tools()).tools]
                added = await client.call_tool("add", {"a": 2, "b": 3})
                who = await client.call_tool("whoami", {})
                return names, added.structured_content, who.structured_content

    async def test_a_user_and_a_named_api_key_connect_in_every_mode(self) -> None:
        url = await self.serve(settings_for())
        for mode in ("auto", "legacy", MODERN):
            with self.subTest(mode=mode, caller="jwt superuser"):
                names, added, who = await self.connect(url, self.bearer(SUPERUSER), mode)
                self.assertEqual((["whoami", "add", "secret"], {"result": 5}, {"result": "root"}), (names, added, who))
            with self.subTest(mode=mode, caller="api key"):
                names, added, who = await self.connect(url, {"X-API-Key": AGENT_KEY}, mode)
                self.assertEqual((["whoami", "add"], {"result": 5}, {"result": "agent"}), (names, added, who))

    async def test_resources_and_prompts_through_the_client_in_every_mode(self) -> None:
        url = await self.serve(settings_for())
        for mode in ("auto", "legacy", MODERN):
            with self.subTest(mode=mode):
                async with httpx2.AsyncClient(headers={"X-API-Key": AGENT_KEY}, trust_env=False) as http:
                    async with Client(streamable_http_client(url, http_client=http), mode=mode) as client:
                        templates = [template.uri_template for template in (await client.list_resource_templates()).resource_templates]
                        contents = (await client.read_resource("notes://7")).contents
                        prompts = [prompt.name for prompt in (await client.list_prompts()).prompts]
                        messages = (await client.get_prompt("summarise", {"topic": "the week"})).messages
                self.assertEqual(["notes://{note_id}"], templates)
                assert isinstance(contents[0], mcp_types.TextResourceContents)
                self.assertEqual({"id": 7}, json.loads(contents[0].text))
                self.assertEqual(["summarise"], prompts)
                assert isinstance(messages[0].content, mcp_types.TextContent)
                self.assertEqual("Summarise the week.", messages[0].content.text)


class CallerTest(EndpointTestCase):
    async def test_who_may_call(self) -> None:
        url = await self.serve(settings_for(), extra_authenticators=(FakeSession(),))
        cases = {
            "no credential": ({}, 401),
            "api key not in web.mcp.callers": ({"X-API-Key": MONITOR_KEY}, 403),
            "browser session": ({"X-Test-Session": "yes"}, 403),
            "user token": (self.bearer(PLAIN_USER), 200),
            "named api key": ({"X-API-Key": AGENT_KEY}, 200),
        }
        body = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        for label, (headers, status) in cases.items():
            with self.subTest(caller=label):
                response = await self.post(url, body, {"MCP-Protocol-Version": "2025-11-25", **headers})
                self.assertEqual(status, response.status_code, response.text)
        unauthenticated = await self.post(url, body)
        self.assertTrue(unauthenticated.headers["WWW-Authenticate"].startswith("Bearer"))

    async def test_anonymous_calls_reach_only_the_tools_without_a_permission_and_sessions_stay_refused(self) -> None:
        url = await self.serve(settings_for(allow_anonymous=True), extra_authenticators=(FakeSession(),))
        self.assertEqual({"result": "anonymous"}, (await self.call_tool(url, "whoami", {}, {}))["structuredContent"])
        hidden = await self.post(
            url,
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "secret", "arguments": {}}},
            {"MCP-Protocol-Version": "2025-11-25"},
        )
        self.assertEqual(-32602, hidden.json()["error"]["code"])
        session = await self.post(url, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"X-Test-Session": "yes"})
        self.assertEqual(403, session.status_code)

    async def test_a_user_without_the_permission_does_not_see_the_tool(self) -> None:
        url = await self.serve(settings_for())
        listing = await self.post(
            url, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, {"MCP-Protocol-Version": "2025-11-25", **self.bearer(PLAIN_USER)}
        )
        self.assertEqual(["whoami", "add"], [tool["name"] for tool in listing.json()["result"]["tools"]])

    async def test_global_csrf_enforcement_does_not_block_token_or_key_calls(self) -> None:
        url = await self.serve(settings_for(), csrf=True)
        for headers in (self.bearer(SUPERUSER), {"X-API-Key": AGENT_KEY}):
            with self.subTest(headers=list(headers)):
                self.assertEqual({"result": 3}, (await self.call_tool(url, "add", {"a": 2}, headers))["structuredContent"])

    async def test_global_csrf_enforcement_does_not_block_anonymous_calls_when_they_are_allowed(self) -> None:
        """Token and key requests are CSRF-exempt by their credential; an anonymous one only by the route."""
        url = await self.serve(settings_for(allow_anonymous=True), csrf=True)
        self.assertEqual({"result": 3}, (await self.call_tool(url, "add", {"a": 2}, {}))["structuredContent"])


class TransportTest(EndpointTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.url = await self.serve(settings_for(allowed_origins=["https://console.example.com"], max_request_body_size=2048))
        self.auth = {"X-API-Key": AGENT_KEY, "MCP-Protocol-Version": "2025-11-25"}
        self.ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}

    async def test_an_origin_from_elsewhere_is_403_and_a_listed_one_passes(self) -> None:
        self.assertEqual(403, (await self.post(self.url, self.ping, {**self.auth, "Origin": "https://evil.example"})).status_code)
        self.assertEqual(200, (await self.post(self.url, self.ping, {**self.auth, "Origin": "https://console.example.com"})).status_code)

    async def test_accept_must_allow_json(self) -> None:
        self.assertEqual(406, (await self.post(self.url, self.ping, {**self.auth, "Accept": "text/html"})).status_code)
        self.assertEqual(200, (await self.post(self.url, self.ping, {**self.auth, "Accept": "*/*"})).status_code)

    async def test_an_oversized_body_is_413_whether_declared_or_streamed(self) -> None:
        large = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"padding": "x" * 4096}}
        self.assertEqual(413, (await self.post(self.url, large, self.auth)).status_code)

        async def chunks():
            yield b'{"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"padding": "'
            for _ in range(8):
                yield b"x" * 512
            yield b'"}}'

        headers = {"Accept": "application/json", "Content-Type": "application/json", **self.auth}
        async with httpx.AsyncClient(trust_env=False) as client:
            streamed = await client.post(self.url, content=chunks(), headers=headers)
        self.assertEqual(413, streamed.status_code)

    async def test_the_get_stream_and_session_delete_are_not_offered(self) -> None:
        async with httpx.AsyncClient(trust_env=False) as client:
            for method in ("GET", "DELETE"):
                with self.subTest(method=method):
                    response = await client.request(method, self.url, headers=self.auth)
                    self.assertEqual((405, "POST"), (response.status_code, response.headers.get("Allow")))

    async def test_no_session_id_is_ever_sent_back(self) -> None:
        response = await self.post(self.url, self.ping, {**self.auth, "Mcp-Session-Id": "from-an-old-client"})
        self.assertEqual(200, response.status_code)
        self.assertNotIn("mcp-session-id", {name.lower() for name in response.headers})

    async def test_discover_reports_the_project_version(self) -> None:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "server/discover",
            "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": MODERN, "io.modelcontextprotocol/clientCapabilities": {}}},
        }
        response = await self.post(self.url, body, {"X-API-Key": AGENT_KEY, "MCP-Protocol-Version": MODERN, "Mcp-Method": "server/discover"})
        expected = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        self.assertEqual({"name": "mcp-web-test", "version": expected}, response.json()["result"]["_meta"]["io.modelcontextprotocol/serverInfo"])


class RateLimitTest(EndpointTestCase):
    async def test_each_caller_has_its_own_budget_and_learns_how_long_to_wait(self) -> None:
        url = await self.serve(settings_for(rate_limit={"limit": 2, "period": 60}))
        agent = {"X-API-Key": AGENT_KEY}
        for _ in range(2):
            self.assertFalse((await self.call_tool(url, "add", {"a": 1}, agent))["isError"])
        refused = await self.call_tool(url, "add", {"a": 1}, agent)
        self.assertTrue(refused["isError"])
        self.assertRegex(refused["content"][0]["text"], r"Rate limit exceeded: at most 2 tool calls per 60 seconds\. Try again in \d+ seconds\.")
        self.assertFalse((await self.call_tool(url, "add", {"a": 1}, self.bearer(SUPERUSER)))["isError"])

    async def test_a_store_that_cannot_count_refuses_the_call(self) -> None:
        url = await self.serve(settings_for())
        failing = AsyncMock(side_effect=RedisConnectionError("down"))
        with (
            patch("oldman.web.security.rate_limiter.fixed_window.RedisFixedWindowRateLimiter.is_rate_limited", failing),
            self.assertLogs("default.mcp", "ERROR"),
        ):
            refused = await self.call_tool(url, "add", {"a": 1}, {"X-API-Key": AGENT_KEY})
        self.assertEqual((True, "The rate limit store is unavailable. Try again later."), (refused["isError"], refused["content"][0]["text"]))

    async def test_it_can_be_turned_off(self) -> None:
        url = await self.serve(settings_for(rate_limit={"enabled": False, "limit": 1}))
        for _ in range(3):
            self.assertFalse((await self.call_tool(url, "add", {"a": 1}, {"X-API-Key": AGENT_KEY}))["isError"])


class StartupCheckTest(EndpointTestCase):
    """Settings under which nobody, or not what was named, could call stop install_mcp."""

    async def test_settings_that_admit_nobody_or_name_unknown_keys_are_refused(self) -> None:
        nobody = settings_for(callers=[])
        nobody.web.auth.authenticators = ["api_key"]
        no_api_key_method = settings_for()
        no_api_key_method.web.auth.authenticators = ["jwt"]
        unknown = settings_for(callers=["agent", "ghost"])
        cases = {
            "no jwt, no callers, no anonymous": (nobody, "Nobody could call"),
            "callers without api_key": (no_api_key_method, "does not list 'api_key'"),
            "unknown caller": (unknown, "ghost"),
        }
        for label, (settings, message) in cases.items():
            with self.subTest(case=label), patch.dict(conf.__dict__, {"settings": settings}):
                app = Sanic(f"mcp_startup_{abs(hash(label))}")
                app.ctx.app_registry = self.app_registry
                try:
                    with self.assertRaisesRegex(ValueError, message):
                        install_mcp(app)
                finally:
                    Sanic.unregister_app(app)

    async def test_while_disabled_nothing_is_loaded_checked_or_routed(self) -> None:
        """The default: a service may call install_mcp with settings that would otherwise stop it."""
        nobody = settings_for(enabled=False, callers=[])
        nobody.web.auth.authenticators = ["session"]
        app = Sanic("mcp_disabled")
        apps = InstalledApps()
        app.ctx.app_registry = apps
        try:
            with patch.dict(conf.__dict__, {"settings": nobody}), self.assertLogs("default.mcp", "INFO") as logs:
                self.assertIsNone(install_mcp(app))
            self.assertEqual(0, apps.loads)
            self.assertNotIn("mcp_endpoint", {route.name.rsplit(".", 1)[-1] for route in app.router.routes})
            self.assertIn("web.mcp.enabled is false", logs.output[0])
        finally:
            Sanic.unregister_app(app)
        self.assertFalse(DefaultSettings().web.mcp.enabled)

    async def test_it_needs_the_service_app_registry(self) -> None:
        app = Sanic("mcp_startup_without_registry")
        try:
            with patch.dict(conf.__dict__, {"settings": settings_for()}), self.assertRaisesRegex(RuntimeError, "App registry"):
                install_mcp(app)
        finally:
            Sanic.unregister_app(app)


if __name__ == "__main__":
    unittest.main()
