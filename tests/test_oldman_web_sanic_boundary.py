"""Public Oldman aliases for the single supported Sanic runtime."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from types import MappingProxyType, ModuleType
from unittest.mock import Mock, patch

from sanic import Request, Sanic
from sanic.blueprints import Blueprint
from sanic.exceptions import BadRequest, Forbidden, NotFound, Unauthorized
from sanic.response import BaseHTTPResponse, ResponseStream
from sanic.views import HTTPMethodView
from sanic_ext import render

import oldman.web as web
from oldman.web.exceptions import TooManyRequests
from oldman.web.routing import Router

ROOT = Path(__file__).resolve().parents[1]


class OldmanWebSanicBoundaryTest(unittest.TestCase):
    """Verify public names hide imports without duplicating Sanic objects."""

    def test_public_types_are_canonical_sanic_objects(self) -> None:
        """Common framework types are aliases instead of handwritten Protocols."""
        self.assertIs(web.Request, Request)
        self.assertIs(web.WebApp, Sanic)
        self.assertIs(web.Response, BaseHTTPResponse)
        self.assertIs(web.StreamingResponse, ResponseStream)
        self.assertIs(web.StreamWriter, ResponseStream)
        # The one class view name is the framework's own: Sanic's class plus the login and
        # staff protocol, both off by default. Exporting Sanic's under the same name beside
        # it forced an Oldman prefix on ours.
        self.assertIsNot(web.HTTPMethodView, HTTPMethodView)
        self.assertTrue(issubclass(web.HTTPMethodView, HTTPMethodView))
        self.assertFalse(hasattr(web, "OldmanHTTPMethodView"))
        self.assertIs(web.Forbidden, Forbidden)
        self.assertIs(web.NotFound, NotFound)
        # 应用要抛的 HTTP 异常都从 oldman.web 拿,不必绕去 sanic.exceptions——
        # 那会让将来替换上游时应用代码跟着改。BadRequest 在代码里被抛 10 次,
        # 此前却没导出,EPG 只好直接 from sanic.exceptions import BadRequest。
        self.assertIs(web.BadRequest, BadRequest)
        self.assertIs(web.Unauthorized, Unauthorized)
        self.assertIs(web.TooManyRequests, TooManyRequests)
        self.assertEqual(429, web.TooManyRequests.status_code)
        self.assertIs(web.render_template, render)
        self.assertIs(web.get_current_request.__self__, Request)

    def test_route_registration_does_not_expose_the_server(self) -> None:
        """router 是框架自己的边界,不是底层服务器的别名。

        它取代的 get_app() 把整个 Sanic 实例交给了应用;实测那些调用**全部**只是
        注册路由,没有一处需要 app.ctx 或 app.config。把入口收窄成路由注册之后,
        底层服务器不再出现在公开 API 里——将来替换上游时应用不受影响。
        """
        self.assertNotIn("get_app", web.__all__)
        self.assertFalse(hasattr(web, "get_app"))
        self.assertIsInstance(web.router, Router)
        self.assertNotIsInstance(web.router, Sanic)
        for name in ("add_route", "route", "websocket", "get", "post", "put", "patch", "delete", "head", "options"):
            self.assertTrue(callable(getattr(web.router, name)), name)
        # 路由之外的服务器能力不在这一层暴露。
        for name in ("ctx", "config", "static", "listener", "middleware", "blueprint"):
            self.assertFalse(hasattr(web.router, name), name)

    def test_registrations_wait_for_a_server_and_land_once(self) -> None:
        """Importing views where no Web server runs — a shell, a script, an App command — must not fail."""
        from sanic.response import text

        from oldman.runtime import base
        from oldman.web import routing

        async def listing(request: Request) -> BaseHTTPResponse:
            return text("list")

        async def detail(request: Request) -> BaseHTTPResponse:
            return text("detail")

        with patch.object(base, "_current_service", None), patch.object(routing, "_pending_registrations", []):
            self.assertIs(listing, web.router.get("/pending/list", name="pending_list")(listing))
            self.assertIs(detail, web.router.add_route(detail, "/pending/detail", name="pending_detail"))

            first = Sanic("pending_routes_first")
            later = Sanic("pending_routes_later")
            try:
                routing._register_pending_routes(first)
                routing._register_pending_routes(later)
                names = {route.name for route in first.router.routes}
                self.assertIn("pending_routes_first.pending_list", names)
                self.assertIn("pending_routes_first.pending_detail", names)
                self.assertEqual([], list(later.router.routes), "recorded routes land on one application, once")
            finally:
                Sanic.unregister_app(first)
                Sanic.unregister_app(later)

    def test_registrations_go_straight_to_the_running_server(self) -> None:
        """Once the service has its application, registering is immediate, as before."""
        from sanic.response import text

        from oldman.runtime import BaseApplication, base
        from oldman.web import routing

        async def now(request: Request) -> BaseHTTPResponse:
            return text("now")

        app = Sanic("immediate_routes")
        running = Mock(spec=BaseApplication)
        running.runtime_app = app
        try:
            with patch.object(base, "_current_service", running), patch.object(routing, "_pending_registrations", []) as pending:
                web.router.get("/now", name="now")(now)
                self.assertEqual([], pending)
            self.assertIn("immediate_routes.now", {route.name for route in app.router.routes})
        finally:
            Sanic.unregister_app(app)

    def test_response_helpers_call_sanic_without_an_adapter(self) -> None:
        """Oldman response names preserve their small public conveniences."""
        headers = MappingProxyType({"X-Test": "value"})

        response = web.json_response({"ok": True}, headers=headers, status=201)
        no_content_type = web.text_response("", content_type=None)

        self.assertIsInstance(response, BaseHTTPResponse)
        self.assertEqual(201, response.status)
        self.assertEqual("value", response.headers["x-test"])
        self.assertIsNone(no_content_type.content_type)

    def test_lightweight_aggregate_does_not_import_db_components(self) -> None:
        """Importing common Web primitives cannot initialize component DB modules."""
        probe = (
            "import sys\n"
            "import oldman.web\n"
            "loaded = sorted(name for name in sys.modules "
            "if name.startswith('oldman.web.components'))\n"
            "if loaded:\n"
            "    raise SystemExit(','.join(loaded))\n"
        )

        completed = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)

    def test_autodiscover_retains_oldman_blueprint_discovery(self) -> None:
        """The one custom routing helper remains owned by Oldman."""
        module = ModuleType("sample_views")
        module.__file__ = None
        blueprint = Blueprint("sample")
        module.__dict__["sample"] = blueprint
        app = Mock()
        app.__module__ = "sample"

        web.autodiscover(app, module)

        app.blueprint.assert_called_once_with(blueprint)

    def test_production_code_has_no_runtime_adapter_reference(self) -> None:
        """The deleted adapter cannot survive through a deferred production import."""
        references = []
        for path in (ROOT / "oldman").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if "oldman.web.runtime" in source or "WebRuntimeAdapter" in source:
                references.append(path.relative_to(ROOT).as_posix())

        self.assertEqual([], references)


if __name__ == "__main__":
    unittest.main()
