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

import oldman.conf as conf
from oldman.conf.schemas import DefaultSettings
from oldman.web.errors import ErrorPageHandler
from oldman.web.exceptions import CSRFFailure
from oldman.web.template import install_template_loaders


class OldmanErrorPagesTest(unittest.IsolatedAsyncioTestCase):
    """Verify HTML pages without changing API error negotiation."""

    def setUp(self) -> None:
        # Error pages name the site (core.site_name), as every page a running service renders does.
        self.enterContext(patch.dict(conf.__dict__, {"settings": DefaultSettings()}))

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

    async def test_error_pages_name_the_site_from_the_settings(self) -> None:
        """The brand is core.site_name (core.app_name when unset), on both the site and the dashboard pages."""
        from jinja2 import Environment

        from oldman.conf.schemas import CoreConfig

        environment = Environment(enable_async=True)
        install_template_loaders(environment)
        request = SimpleNamespace(ctx=SimpleNamespace(locale="en"))
        for core, expected in (
            (CoreConfig(app_name="acme_ops", site_name="Acme Operations"), "Acme Operations"),
            (CoreConfig(app_name="acme_ops"), "acme_ops"),
        ):
            settings = DefaultSettings().model_copy(update={"core": core})
            with patch.dict(conf.__dict__, {"settings": settings}):
                for name in ("oldman/errors/404.html", "oldman/dashboard/errors/404.html"):
                    content = await environment.get_template(name).render_async(request=request, status_code=404)
                    with self.subTest(name=name, expected=expected):
                        self.assertIn(f'aria-label="{expected}"', content)
                        self.assertIn(f"· {expected}</title>", content)
                        self.assertNotIn("Oldman", content)
                footer = await environment.get_template("oldman/dashboard/partials/footer.html").render_async(request=request)
                self.assertIn(expected, footer)

    async def test_the_way_back_is_the_dashboard_home_or_the_site_root(self) -> None:
        """Dashboard error pages lead to where a sign-in lands; the site's own lead to its root."""
        from jinja2 import Environment

        from oldman.conf.schemas import AccountConfig

        environment = Environment(enable_async=True)
        install_template_loaders(environment)
        request = SimpleNamespace(ctx=SimpleNamespace(locale="en"))
        settings = DefaultSettings()
        settings.web.account = AccountConfig(login_redirect_url="/console")
        with patch.dict(conf.__dict__, {"settings": settings}):
            dashboard = await environment.get_template("oldman/dashboard/errors/404.html").render_async(request=request, status_code=404)
            site = await environment.get_template("oldman/errors/404.html").render_async(request=request, status_code=404)

        self.assertIn('<a class="error-action" href="/console">', dashboard)
        self.assertIn('<a class="brand" href="/console"', dashboard)
        self.assertNotIn('href="/"', dashboard)
        self.assertIn('<a class="action" href="/">', site)
        self.assertTrue(dashboard.startswith("<!doctype html>") and site.startswith("<!doctype html>"), "nothing before the doctype")

    async def test_csrf_failure_page_says_how_to_recover(self) -> None:
        """A rejected form is not a permission problem; only the opted-in sentence reaches the page."""
        from jinja2 import Environment

        app = Sanic(f"oldman-csrf-error-page-{uuid4().hex}", error_handler=ErrorPageHandler())
        app.config.FALLBACK_ERROR_FORMAT = "auto"
        app.config.TEMPLATING_ENABLE_ASYNC = True
        Extend(app, config=Config(templating_enable_async=True), extensions=[TemplatingExtension], built_in_extensions=False)
        install_template_loaders(app.ext.environment)

        @app.post("/form")
        async def form(_request):
            raise CSRFFailure("private-csrf-detail", page_description="Reload the page and try again.")

        @app.post("/denied")
        async def denied(_request):
            raise Forbidden("private-forbidden-detail")

        _request, rejected = await app.asgi_client.post("/form", headers={"accept": "text/html"})
        _request, forbidden = await app.asgi_client.post("/denied", headers={"accept": "text/html"})

        self.assertEqual(403, rejected.status)
        self.assertIn("Reload the page and try again.", rejected.text)
        self.assertNotIn("You do not have permission", rejected.text)
        self.assertNotIn("private-csrf-detail", rejected.text)
        self.assertIn("You do not have permission", forbidden.text)
        self.assertNotIn("private-forbidden-detail", forbidden.text)

        environment = Environment(enable_async=True)
        install_template_loaders(environment)
        dashboard = environment.get_template("oldman/dashboard/errors/403.html")
        request = SimpleNamespace(ctx=SimpleNamespace(locale="en"))
        content = await dashboard.render_async(request=request, status_code=403, description="Reload the page and try again.")
        self.assertIn("Reload the page and try again.", content)
        self.assertNotIn("You do not have permission", content)

    async def test_permission_callers_use_html_templates_or_json_by_resolved_mode(self) -> None:
        """Explicit modes survive Accept conflicts; every shared caller awaits rendering."""
        from oldman.apps.admin.table import AdminModelTable
        from oldman.web.auth import staff_required, superuser_required
        from oldman.web.authentication import request_user
        from oldman.web.http import HTTPMethodView, access_denied_response, permission_denied_response, resolve_response_mode
        from oldman.web.session import SessionData

        app = Sanic(f"permission-pages-{uuid4().hex}", error_handler=ErrorPageHandler())
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

        class StaffView(HTTPMethodView):
            async def check_permission(self, request, *, method_name: str, route_kwargs: dict[str, object]):
                return request_user(request).is_staff, None

            async def get(self, request):
                raise AssertionError("denied handler must not execute")

        app.add_route(StaffView.as_view(), "/view")

        @app.get("/admin")
        async def admin(request):
            return await access_denied_response(request, login_url="/admin/login")

        @app.get("/admin-table")
        async def admin_table(request):
            # Exercise the adapter's callback bridge without touching a database.
            table = object.__new__(AdminModelTable)
            table._permission_denied_response = lambda current: access_denied_response(current, login_url="/admin/login")
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
            error_handler=ErrorPageHandler(),
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
