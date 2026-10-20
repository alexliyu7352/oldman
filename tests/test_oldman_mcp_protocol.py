"""The MCP wire rules: which era a POST is in, how each check answers, and how results are serialized.

Every row of the decision table in the plan has a case here that builds the offending request by hand:
a lenient client connecting fine proves nothing about what the server refuses.
"""

from __future__ import annotations

import asyncio
import base64
import json
import unittest
from types import SimpleNamespace
from typing import Any

from mcp_types import version as known_versions

from oldman.mcp import McpRegistry
from oldman.mcp._protocol import HANDSHAKE_VERSIONS, MODERN_VERSIONS, VERSION_WITHOUT_HEADER, Reply
from oldman.mcp._server import McpServer

MODERN = "2026-07-28"
META = {"io.modelcontextprotocol/protocolVersion": MODERN, "io.modelcontextprotocol/clientCapabilities": {}}

registry = McpRegistry()


@registry.tool()
async def add(a: int, b: int = 1) -> int:
    """Add two numbers."""
    return a + b


SERVER = McpServer(registry.catalog([__name__]), name="protocol-test", version="1.2.3", instructions="Use add to add.")
REQUEST = SimpleNamespace(ctx=SimpleNamespace(), app=None)


def post(headers: list[tuple[str, str]], body: Any, content_type: str | None = "application/json") -> Reply:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return asyncio.run(SERVER.handle(REQUEST, headers, raw, content_type))


def modern_headers(method: str, name: str | None = None, version: str = MODERN) -> list[tuple[str, str]]:
    headers = [("MCP-Protocol-Version", version), ("Mcp-Method", method)]
    if name is not None:
        headers.append(("Mcp-Name", name))
    return headers


def modern_body(method: str, params: dict[str, Any] | None = None, meta: Any = META, message_id: Any = 1) -> dict[str, Any]:
    body_params = dict(params or {})
    if meta is not None:
        body_params["_meta"] = meta
    return {"jsonrpc": "2.0", "id": message_id, "method": method, "params": body_params}


def error_of(reply: Reply) -> tuple[int, int]:
    assert reply.body is not None
    return reply.status, reply.body["error"]["code"]


class VersionListTest(unittest.TestCase):
    def test_every_implemented_revision_is_one_mcp_types_knows(self) -> None:
        """The server's own list; each entry must have wire models, or requests in it could not be parsed."""
        self.assertLessEqual(set(HANDSHAKE_VERSIONS) | set(MODERN_VERSIONS), set(known_versions.KNOWN_PROTOCOL_VERSIONS))
        self.assertIn(VERSION_WITHOUT_HEADER, HANDSHAKE_VERSIONS)


class ModernLadderTest(unittest.TestCase):
    """2026-07-28: the checks after the transport's own, in order."""

    def test_a_body_that_is_not_json_is_a_parse_error_with_no_id(self) -> None:
        reply = post(modern_headers("tools/list"), b"{not json")
        self.assertEqual((400, -32700), error_of(reply))
        self.assertIsNone(reply.body and reply.body["id"])

    def test_a_notification_is_accepted_with_no_body_unless_its_version_is_unknown(self) -> None:
        notification = {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}}
        self.assertEqual(Reply(202), post(modern_headers("notifications/cancelled"), notification))
        unknown = post(modern_headers("notifications/cancelled", version="2099-01-01"), notification)
        self.assertEqual((400, -32022), error_of(unknown))

    def test_a_batch_or_a_posted_response_is_an_invalid_request(self) -> None:
        self.assertEqual((400, -32600), error_of(post(modern_headers("tools/list"), [modern_body("tools/list")])))
        self.assertEqual((400, -32600), error_of(post(modern_headers("tools/list"), {"jsonrpc": "2.0", "id": 1, "result": {}})))

    def test_a_repeated_routing_header_is_a_mismatch(self) -> None:
        headers = [*modern_headers("tools/list"), ("Mcp-Method", "tools/list")]
        self.assertEqual((400, -32020), error_of(post(headers, modern_body("tools/list"))))

    def test_meta_must_carry_the_version_and_the_client_capabilities(self) -> None:
        version_only = {"io.modelcontextprotocol/protocolVersion": MODERN}
        self.assertEqual((400, -32602), error_of(post(modern_headers("tools/list"), modern_body("tools/list", meta=None))))
        self.assertEqual((400, -32602), error_of(post(modern_headers("tools/list"), modern_body("tools/list", meta=version_only))))

    def test_the_version_header_must_equal_the_version_in_the_body(self) -> None:
        other = {**META, "io.modelcontextprotocol/protocolVersion": "2099-01-01"}
        reply = post(modern_headers("tools/list"), modern_body("tools/list", meta=other))
        # The mismatch is reported before the unsupported version, so the client learns it disagrees with itself.
        self.assertEqual((400, -32020), error_of(reply))

    def test_a_handshake_version_header_with_a_modern_body_is_a_mismatch(self) -> None:
        """The body's _meta makes it a 2026-07-28 request (spec versioning), and then the header disagrees."""
        reply = post(modern_headers("tools/list", version="2025-11-25"), modern_body("tools/list"))
        self.assertEqual((400, -32020), error_of(reply))

    def test_mcp_method_must_be_present_and_equal_to_the_method(self) -> None:
        missing = [("MCP-Protocol-Version", MODERN)]
        self.assertEqual((400, -32020), error_of(post(missing, modern_body("tools/list"))))
        self.assertEqual((400, -32020), error_of(post(modern_headers("tools/call"), modern_body("tools/list"))))

    def test_mcp_name_must_be_present_and_equal_to_the_named_parameter(self) -> None:
        call = modern_body("tools/call", {"name": "add", "arguments": {"a": 1}})
        self.assertEqual((400, -32020), error_of(post(modern_headers("tools/call"), call)))
        self.assertEqual((400, -32020), error_of(post(modern_headers("tools/call", name="other"), call)))
        self.assertEqual(200, post(modern_headers("tools/call", name="add"), call).status)

    def test_mcp_name_is_decoded_from_its_base64_sentinel_and_unsafe_values_never_match(self) -> None:
        call = modern_body("tools/call", {"name": "add", "arguments": {"a": 1}})
        encoded = "=?base64?" + base64.b64encode(b"add").decode() + "?="
        self.assertEqual(200, post(modern_headers("tools/call", name=encoded), call).status)
        self.assertEqual((400, -32020), error_of(post(modern_headers("tools/call", name="=?base64?@@@?="), call)))
        self.assertEqual((400, -32020), error_of(post(modern_headers("tools/call", name="add\x01"), call)))

    def test_an_unsupported_version_lists_the_supported_ones(self) -> None:
        unknown = {**META, "io.modelcontextprotocol/protocolVersion": "2099-01-01"}
        reply = post(modern_headers("tools/list", version="2099-01-01"), modern_body("tools/list", meta=unknown))
        self.assertEqual((400, -32022), error_of(reply))
        assert reply.body is not None
        self.assertEqual({"supported": list(MODERN_VERSIONS), "requested": "2099-01-01"}, reply.body["error"]["data"])

    def test_an_unknown_method_is_404_and_ping_does_not_exist_in_2026(self) -> None:
        self.assertEqual((404, -32601), error_of(post(modern_headers("nope/nope"), modern_body("nope/nope"))))
        self.assertEqual((404, -32601), error_of(post(modern_headers("ping"), modern_body("ping"))))

    def test_invalid_params_are_400(self) -> None:
        reply = post(modern_headers("tools/call"), modern_body("tools/call", {"arguments": {}}))
        self.assertEqual((400, -32602), error_of(reply))

    def test_discover_reports_the_versions_capabilities_and_server_info(self) -> None:
        reply = post(modern_headers("server/discover"), modern_body("server/discover"))
        self.assertEqual(200, reply.status)
        assert reply.body is not None
        result = reply.body["result"]
        self.assertEqual(list(MODERN_VERSIONS), result["supportedVersions"])
        self.assertEqual({"tools": {}}, result["capabilities"])
        self.assertEqual({"name": "protocol-test", "version": "1.2.3"}, result["_meta"]["io.modelcontextprotocol/serverInfo"])
        self.assertEqual("Use add to add.", result["instructions"])
        self.assertEqual("complete", result["resultType"])

    def test_lists_carry_the_2026_fields_and_may_only_be_cached_per_caller(self) -> None:
        reply = post(modern_headers("tools/list"), modern_body("tools/list"))
        assert reply.body is not None
        result = reply.body["result"]
        self.assertEqual(("complete", "private", 0), (result["resultType"], result["cacheScope"], result["ttlMs"]))
        self.assertEqual(["add"], [tool["name"] for tool in result["tools"]])

    def test_session_and_resumption_headers_from_older_clients_are_ignored(self) -> None:
        headers = [*modern_headers("tools/list"), ("Mcp-Session-Id", "abc"), ("Last-Event-ID", "7")]
        self.assertEqual(200, post(headers, modern_body("tools/list")).status)


class HandshakeEraTest(unittest.TestCase):
    """2024-11-05 … 2025-11-25: initialize first, no session kept."""

    def handshake(self, method: str, params: dict[str, Any] | None = None, version: str | None = "2025-11-25", **kwargs: Any) -> Reply:
        headers = [] if version is None else [("MCP-Protocol-Version", version)]
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": 9, "method": method}
        if params is not None:
            body["params"] = params
        return post(headers, body, **kwargs)

    def test_initialize_answers_the_offered_version_or_the_latest_one(self) -> None:
        offer = {"capabilities": {}, "clientInfo": {"name": "client", "version": "1"}}
        accepted = self.handshake("initialize", {**offer, "protocolVersion": "2025-06-18"}, version=None)
        countered = self.handshake("initialize", {**offer, "protocolVersion": "1999-01-01"}, version=None)
        assert accepted.body is not None and countered.body is not None
        self.assertEqual("2025-06-18", accepted.body["result"]["protocolVersion"])
        self.assertEqual(HANDSHAKE_VERSIONS[-1], countered.body["result"]["protocolVersion"])
        self.assertEqual({"name": "protocol-test", "version": "1.2.3"}, accepted.body["result"]["serverInfo"])

    def test_notifications_and_posted_responses_are_accepted_with_no_body(self) -> None:
        self.assertEqual(Reply(202), post([], {"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(Reply(202), post([("MCP-Protocol-Version", "2025-11-25")], {"jsonrpc": "2.0", "id": 3, "result": {}}))

    def test_a_request_without_the_version_header_is_2025_03_26(self) -> None:
        reply = self.handshake("tools/list", version=None)
        assert reply.body is not None
        self.assertEqual(200, reply.status)
        self.assertNotIn("resultType", reply.body["result"])

    def test_results_leave_out_the_2026_fields(self) -> None:
        reply = self.handshake("tools/call", {"name": "add", "arguments": {"a": 2}})
        assert reply.body is not None
        self.assertEqual({"result": 3}, reply.body["result"]["structuredContent"])
        self.assertTrue({"resultType", "ttlMs", "cacheScope"}.isdisjoint(reply.body["result"]))

    def test_the_body_must_be_json(self) -> None:
        reply = self.handshake("ping", content_type="text/plain")
        self.assertEqual((415, -32600), error_of(reply))

    def test_a_batch_is_refused(self) -> None:
        reply = post([("MCP-Protocol-Version", "2025-03-26")], [{"jsonrpc": "2.0", "id": 1, "method": "ping"}])
        self.assertEqual((400, -32600), error_of(reply))

    def test_method_errors_come_in_a_200(self) -> None:
        self.assertEqual((200, -32601), error_of(self.handshake("nope/nope")))
        self.assertEqual((200, -32602), error_of(self.handshake("tools/call", {"arguments": {}})))

    def test_ping_answers_an_empty_result(self) -> None:
        reply = self.handshake("ping")
        assert reply.body is not None
        self.assertEqual({}, reply.body["result"])


if __name__ == "__main__":
    unittest.main()
