"""HTTP runtime contracts for persistent user notifications."""

from __future__ import annotations

import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

from markupsafe import Markup
from sanic import Request, Sanic
from sanic_ext import Config, Extend
from sanic_ext.extensions.templating.extension import TemplatingExtension

import oldman.conf as conf
from oldman.conf.schemas import DefaultSettings
from oldman.web.messages.notifications.payloads import NotificationPayload
from oldman.web.messages.notifications.runtime import NotificationRoutes, init_app
from oldman.web.messages.notifications.service import notifications
from oldman.web.session import SessionData


class _InstalledApps:
    """Expose the one App lookup required by the notification installer."""

    def get_by_package(self, package: str) -> object:
        if package != "oldman.web.messages.notifications":
            raise LookupError(package)
        return object()


class _MissingApps:
    """Reject every package as not installed."""

    def get_by_package(self, package: str) -> object:
        raise LookupError(package)


class _AcceptingCSRF:
    """Keep route tests focused on decorator placement and request shape."""

    @staticmethod
    def get_token_from_request(request: Request) -> str | None:
        return request.headers.get("x-csrftoken")

    @staticmethod
    def validate_token(request: Request, token: str) -> tuple[bool, str]:
        del request, token
        return True, "Valid"


class NotificationRuntimeTest(unittest.IsolatedAsyncioTestCase):
    """Exercise real Sanic routes without replacing their auth decorators."""

    def setUp(self) -> None:
        self.settings = DefaultSettings.model_validate(
            {"web": {"session": {"enabled": True}}}
        )
        self.settings_patch = patch.dict(conf.__dict__, {"settings": self.settings})
        self.settings_patch.start()
        self.app = self._new_app("runtime")
        self.app.ctx.oldman_app_registry = _InstalledApps()
        self.app.ctx.csrf = _AcceptingCSRF()

        @self.app.on_request
        async def add_session(request: Request) -> None:
            anonymous = request.headers.get("x-test-anonymous") == "1"
            request.ctx.session = SessionData(
                user_id=None if anonymous else 17,
                is_active=not anonymous,
            )

        self.root_routes = init_app(self.app)
        self.admin_routes = init_app(self.app, url_prefix="/admin")

    def tearDown(self) -> None:
        Sanic.unregister_app(self.app)
        self.settings_patch.stop()

    @staticmethod
    def _new_app(suffix: str, *, templating: bool = True) -> Sanic:
        app = Sanic(
            f"oldman-notification-{suffix}-{time.time_ns()}",
            configure_logging=False,
        )
        if templating:
            Extend(
                app,
                config=Config(
                    LOGGING=False,
                    OAS=False,
                    OAS_AUTODOC=False,
                    TEMPLATING_ENABLE_ASYNC=True,
                ),
                extensions=[TemplatingExtension],
                built_in_extensions=False,
            )
        return app

    async def test_prefixes_install_once_and_keep_independent_routes(self) -> None:
        """Root and Admin hosts may share one app without duplicate routes."""
        repeated = init_app(self.app, url_prefix="/admin/")

        self.assertIs(self.admin_routes, repeated)
        self.assertEqual(
            NotificationRoutes(
                topbar_url="/user-notifications/topbar",
                read_url="/user-notifications/read",
                delete_url="/user-notifications/delete",
                center_url="/user-notifications",
            ),
            self.root_routes,
        )
        self.assertEqual("/admin/user-notifications/topbar", self.admin_routes.topbar_url)

        fragment = Markup('<div data-om-user-notification-fragment data-om-unread-count="0"></div>')
        with patch(
            "oldman.web.messages.notifications.runtime.render_topbar_fragment",
            AsyncMock(return_value=fragment),
        ):
            _request, root_response = await self.app.asgi_client.get(
                self.root_routes.topbar_url
            )
            _request, admin_response = await self.app.asgi_client.get(
                self.admin_routes.topbar_url
            )

        self.assertEqual(200, root_response.status)
        self.assertEqual(200, admin_response.status)
        self.assertEqual("text/html; charset=utf-8", root_response.content_type)
        _request, center_response = await self.app.asgi_client.get(
            self.root_routes.center_url
        )
        self.assertEqual(404, center_response.status)

    def test_invalid_prefixes_and_missing_dependencies_fail_before_routes(self) -> None:
        """Installer errors must be explicit and must not partially register routes."""
        for prefix in ("admin", "//admin", "/admin\\nested", "/admin\nnext"):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                init_app(self.app, url_prefix=prefix)

        cases: list[tuple[str, Sanic, str, int]] = []
        no_registry = self._new_app("no-registry")
        no_registry.ctx.csrf = _AcceptingCSRF()
        cases.append(
            ("registry", no_registry, "[Rr]egistry", len(no_registry.router.routes))
        )

        missing_app = self._new_app("missing-app")
        missing_app.ctx.oldman_app_registry = _MissingApps()
        missing_app.ctx.csrf = _AcceptingCSRF()
        cases.append(
            ("app", missing_app, "notifications", len(missing_app.router.routes))
        )

        no_templates = self._new_app("no-templates", templating=False)
        no_templates.ctx.oldman_app_registry = _InstalledApps()
        no_templates.ctx.csrf = _AcceptingCSRF()
        no_templates.ext.environment = None
        cases.append(
            (
                "templates",
                no_templates,
                "template",
                len(no_templates.router.routes),
            )
        )

        no_csrf = self._new_app("no-csrf")
        no_csrf.ctx.oldman_app_registry = _InstalledApps()
        cases.append(("csrf", no_csrf, "CSRF", len(no_csrf.router.routes)))

        for label, app, message, original_route_count in cases:
            with self.subTest(label=label), self.assertRaisesRegex(
                (RuntimeError, LookupError), message
            ):
                init_app(app)
            self.assertEqual(original_route_count, len(app.router.routes))
            Sanic.unregister_app(app)

        disabled = self._new_app("session-disabled")
        disabled.ctx.oldman_app_registry = _InstalledApps()
        disabled.ctx.csrf = _AcceptingCSRF()
        disabled_route_count = len(disabled.router.routes)
        with patch.dict(
            conf.__dict__,
            {"settings": DefaultSettings()},
        ), self.assertRaisesRegex(RuntimeError, "Session"):
            init_app(disabled)
        self.assertEqual(disabled_route_count, len(disabled.router.routes))
        Sanic.unregister_app(disabled)

    async def test_authentication_uses_typed_session_identity(self) -> None:
        """HTML and JSON routes retain the shared login decorator protocols."""
        _request, topbar = await self.app.asgi_client.get(
            self.root_routes.topbar_url,
            headers={"x-test-anonymous": "1"},
        )
        _request, read = await self.app.asgi_client.post(
            self.root_routes.read_url,
            json={"all": True},
            headers={"x-test-anonymous": "1", "x-csrftoken": "token"},
        )

        self.assertEqual(302, topbar.status)
        self.assertTrue(topbar.headers["location"].startswith("/login?next="))
        self.assertEqual(401, read.status)
        self.assertEqual(1401, read.json["error_code"])

    async def test_read_and_delete_accept_only_exact_json_shapes(self) -> None:
        """Body IDs are deduplicated and a caller can never select a user ID."""
        with patch.object(
            notifications,
            "mark_read",
            AsyncMock(return_value=2),
        ) as mark_read, patch.object(
            notifications,
            "mark_all_read",
            AsyncMock(return_value=4),
        ) as mark_all_read, patch.object(
            notifications,
            "delete",
            AsyncMock(return_value=1),
        ) as delete:
            _request, selected = await self.app.asgi_client.post(
                self.root_routes.read_url,
                json={"ids": [3, 3, 5]},
                headers={"x-csrftoken": "token"},
            )
            _request, all_response = await self.app.asgi_client.post(
                self.root_routes.read_url,
                json={"all": True},
                headers={"x-csrftoken": "token"},
            )
            _request, deleted = await self.app.asgi_client.post(
                self.root_routes.delete_url,
                json={"ids": [8, 8]},
                headers={"x-csrftoken": "token"},
            )

        self.assertEqual({"changed": 2}, selected.json["data"])
        self.assertEqual({"changed": 4}, all_response.json["data"])
        self.assertEqual({"changed": 1}, deleted.json["data"])
        mark_read.assert_awaited_once_with(17, (3, 5))
        mark_all_read.assert_awaited_once_with(17)
        delete.assert_awaited_once_with(17, (8,))

        invalid_read = (
            [],
            {"ids": []},
            {"ids": [True]},
            {"ids": [0]},
            {"all": False},
            {"all": True, "ids": [1]},
            {"ids": [1], "user_id": 99},
        )
        for body in invalid_read:
            with self.subTest(body=body):
                _request, response = await self.app.asgi_client.post(
                    self.root_routes.read_url,
                    json=body,
                    headers={"x-csrftoken": "token"},
                )
                self.assertEqual(400, response.status)
                self.assertEqual(1000, response.json["error_code"])

        _request, malformed = await self.app.asgi_client.post(
            self.root_routes.read_url,
            data="{",
            headers={
                "content-type": "application/json",
                "x-csrftoken": "token",
            },
        )
        self.assertEqual(400, malformed.status)
        self.assertEqual(1000, malformed.json["error_code"])

        for body in ({"ids": []}, {"all": True}, {"ids": [1], "extra": 1}):
            with self.subTest(delete_body=body):
                _request, response = await self.app.asgi_client.post(
                    self.root_routes.delete_url,
                    json=body,
                    headers={"x-csrftoken": "token"},
                )
                self.assertEqual(400, response.status)
                self.assertEqual(1000, response.json["error_code"])

    async def test_open_marks_only_owned_rows_and_redirects_safely(self) -> None:
        """Open uses the authenticated recipient for both lookup and mutation."""
        linked = SimpleNamespace(
            id=7,
            payload=NotificationPayload(
                title=__import__("oldman.i18n", fromlist=["gettext_lazy"]).gettext_lazy(
                    "Linked"
                ),
                href="/reports/7",
            ).to_msgpack(),
        )
        unlinked = SimpleNamespace(
            id=8,
            payload=NotificationPayload(
                title=__import__("oldman.i18n", fromlist=["gettext_lazy"]).gettext_lazy(
                    "Unlinked"
                )
            ).to_msgpack(),
        )
        unsafe = SimpleNamespace(
            id=9,
            payload=NotificationPayload(
                title=__import__("oldman.i18n", fromlist=["gettext_lazy"]).gettext_lazy(
                    "Unsafe"
                ),
                href="//outside.example/path",
            ).to_msgpack(),
        )
        rows = {7: linked, 8: unlinked, 9: unsafe}

        async def get_for_user(user_id: int, notification_id: int) -> object | None:
            self.assertEqual(17, user_id)
            return rows.get(notification_id)

        with patch.object(
            notifications,
            "get_for_user",
            AsyncMock(side_effect=get_for_user),
        ), patch.object(
            notifications,
            "mark_read",
            AsyncMock(return_value=1),
        ) as mark_read:
            _request, linked_response = await self.app.asgi_client.get(
                "/user-notifications/7/open"
            )
            _request, unlinked_response = await self.app.asgi_client.get(
                "/user-notifications/8/open"
            )
            _request, missing_response = await self.app.asgi_client.get(
                "/user-notifications/404/open"
            )
            _request, unsafe_response = await self.app.asgi_client.get(
                "/user-notifications/9/open"
            )

        self.assertEqual(303, linked_response.status)
        self.assertEqual("/reports/7", linked_response.headers["location"])
        self.assertEqual(303, unlinked_response.status)
        self.assertEqual(
            self.root_routes.center_url,
            unlinked_response.headers["location"],
        )
        self.assertEqual(404, missing_response.status)
        self.assertEqual(404, unsafe_response.status)
        self.assertEqual(
            [call(17, (7,)), call(17, (8,))],
            mark_read.await_args_list,
        )


if __name__ == "__main__":
    unittest.main()
