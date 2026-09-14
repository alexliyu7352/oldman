"""Oldman HTML fallback error page contracts."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from sanic import Sanic
from sanic.exceptions import Forbidden, SanicException, Unauthorized
from sanic_ext import Config, Extend
from sanic_ext.extensions.templating.extension import TemplatingExtension

from oldman.web.errors import OldmanErrorHandler
from oldman.web.template import install_template_loaders


class OldmanErrorPagesTest(unittest.IsolatedAsyncioTestCase):
    """Verify HTML pages without changing API error negotiation."""

    async def test_dashboard_errors_are_static_documents(self) -> None:
        """Inherited error pages need no JS Page registration to display or leave."""
        from jinja2 import Environment

        environment = Environment(enable_async=True)
        install_template_loaders(environment)
        request = SimpleNamespace(ctx=SimpleNamespace(locale="en"))
        for status in (403, 404, 500, 418):
            template_name = str(status) if status != 418 else "default"
            template = environment.get_template(f"oldman/dashboard/errors/{template_name}.html")
            content = await template.render_async(request=request, status_code=status)
            with self.subTest(status=status):
                self.assertIn(str(status), content)
                self.assertIn('href="/"', content)
                self.assertNotIn("data-om-page=", content)

    async def test_permission_callers_use_html_templates_or_json_by_resolved_mode(self) -> None:
        """Explicit modes survive Accept conflicts; every shared caller awaits rendering."""
        from oldman.apps.admin.site import admin_access_denied_response
        from oldman.apps.admin.table import AdminModelTable
        from oldman.web.auth import staff_required, superuser_required
        from oldman.web.http import OldmanHTTPMethodView, permission_denied_response, resolve_response_mode
        from oldman.web.session import SessionData

        app = Sanic(f"permission-pages-{uuid4().hex}", error_handler=OldmanErrorHandler())
        app.config.FALLBACK_ERROR_FORMAT = "auto"
        Extend(app, config=Config(templating_enable_async=True), extensions=[TemplatingExtension], built_in_extensions=False)
        temporary_directory = self.enterContext(TemporaryDirectory())
        error_templates = Path(temporary_directory) / "errors"
        error_templates.mkdir()
        (error_templates / "403.html").write_text("CUSTOM DENIED {{ status_code }}", encoding="utf-8")
        install_template_loaders(app.ext.environment, temporary_directory)

        @app.on_request
        async def logged_in(request):
            request.ctx.session = SessionData(user_id=7, is_active=True)

        @app.get("/permission")
        async def permission(request):
            return await permission_denied_response(request, resolve_response_mode(request))

        @app.get("/staff")
        @staff_required()
        async def staff(request):
            raise AssertionError("denied handler must not execute")

        @app.get("/superuser")
        @superuser_required()
        async def superuser(request):
            raise AssertionError("denied handler must not execute")

        class StaffView(OldmanHTTPMethodView):
            require_staff = True

            async def get(self, request):
                raise AssertionError("denied handler must not execute")

        app.add_route(StaffView.as_view(), "/view")

        @app.get("/admin")
        async def admin(request):
            return await admin_access_denied_response(request, "/admin/login")

        @app.get("/admin-table")
        async def admin_table(request):
            # Exercise the adapter's callback bridge without touching a database.
            table = object.__new__(AdminModelTable)
            table._permission_denied_response = lambda current: admin_access_denied_response(current, "/admin/login")
            return await table.render_permission_denied_response(request)

        for path in ("/permission", "/staff", "/superuser", "/view", "/admin", "/admin-table"):
            with self.subTest(path=path):
                _, response = await app.asgi_client.get(f"{path}?response_mode=html", headers={"accept": "application/json"})
                self.assertEqual(response.status, 403)
                self.assertEqual(response.content_type, "text/html; charset=utf-8")
                self.assertEqual(response.text, "CUSTOM DENIED 403")
                _, response = await app.asgi_client.get(f"{path}?response_mode=json", headers={"accept": "text/html"})
                self.assertEqual(response.status, 403)
                self.assertEqual(response.content_type, "application/json")
                self.assertEqual(response.json["actions"], [])

        # A broken project template must not turn a denied request into a 500/JSON.
        with patch.object(app.ext.environment, "select_template", side_effect=RuntimeError("broken template")):
            for accept in ("text/html", "application/json"):
                _, response = await app.asgi_client.get("/permission?response_mode=html", headers={"accept": accept})
                self.assertEqual(response.status, 403)
                self.assertEqual(response.content_type, "text/html; charset=utf-8")
                self.assertNotIn("broken template", response.text)

    async def test_html_errors_use_template_chain_but_json_stays_json(self) -> None:
        """The fallback must remain safe for both browser and API consumers."""
        app = Sanic(
            f"oldman-error-pages-{uuid4().hex}",
            error_handler=OldmanErrorHandler(),
        )
        app.config.FALLBACK_ERROR_FORMAT = "auto"
        app.config.TEMPLATING_ENABLE_ASYNC = True
        Extend(
            app,
            config=Config(templating_enable_async=True),
            extensions=[TemplatingExtension],
            built_in_extensions=False,
        )

        temporary_directory = self.enterContext(TemporaryDirectory())
        error_templates = Path(temporary_directory) / "errors"
        error_templates.mkdir()
        (error_templates / "401.html").write_text("CUSTOM 401", encoding="utf-8")
        (error_templates / "default.html").write_text(
            "CUSTOM DEFAULT {{ status_code }}",
            encoding="utf-8",
        )
        install_template_loaders(app.ext.environment, temporary_directory)

        @app.get("/boom")
        async def boom(_request):
            raise RuntimeError("private-error-detail")

        @app.get("/forbidden")
        async def forbidden(_request):
            raise Forbidden("private-forbidden-detail")

        @app.get("/unauthorized")
        async def unauthorized(_request):
            raise Unauthorized("private-unauthorized-detail")

        @app.get("/teapot")
        async def teapot(_request):
            raise SanicException("private-teapot-detail", status_code=418)

        _request, missing = await app.asgi_client.get(
            "/missing",
            headers={"accept": "text/html"},
        )
        _request, api_missing = await app.asgi_client.get(
            "/missing",
            headers={"accept": "application/json"},
        )
        _request, failed = await app.asgi_client.get(
            "/boom",
            headers={"accept": "text/html"},
        )
        _request, denied = await app.asgi_client.get(
            "/forbidden",
            headers={"accept": "text/html"},
        )
        _request, custom = await app.asgi_client.get(
            "/unauthorized",
            headers={"accept": "text/html"},
        )
        _request, generic = await app.asgi_client.get(
            "/teapot",
            headers={"accept": "text/html"},
        )

        self.assertEqual((404, "text/html; charset=utf-8"), (missing.status, missing.content_type))
        self.assertIn("Page not found", missing.text)
        self.assertEqual("application/json", api_missing.content_type)
        self.assertEqual(404, api_missing.json["status"])
        self.assertEqual(500, failed.status)
        self.assertIn("Server error", failed.text)
        self.assertNotIn("private-error-detail", failed.text)
        self.assertEqual(403, denied.status)
        self.assertIn("Access denied", denied.text)
        self.assertNotIn("private-forbidden-detail", denied.text)
        self.assertEqual((401, "CUSTOM 401"), (custom.status, custom.text))
        self.assertEqual((418, "CUSTOM DEFAULT 418"), (generic.status, generic.text))


if __name__ == "__main__":
    unittest.main()
