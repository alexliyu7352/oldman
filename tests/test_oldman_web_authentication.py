"""The request authentication pipeline and the permission checks that read it."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

from sanic import Sanic
from sanic.response import json, text

import oldman.conf as conf
from oldman.conf.schemas import DefaultSettings
from oldman.web.authentication import (
    ANONYMOUS_USER,
    Authentication,
    RequestUser,
    SessionAuthentication,
    exempt_from_csrf,
    install_authentication,
    record_authentication,
    request_user,
    resolve_authenticators,
    user_from_session,
)
from oldman.web.session import SessionData
from tests.test_backend_http_view import make_request as view_request
from tests.test_oldman_web_auth_decorators import make_request as decorator_request
from tests.test_oldman_web_auth_decorators import run_async

STAFF = RequestUser(id=7, username="ops", is_staff=True)


class HeaderAuthentication:
    """A non-session method standing in for a bearer token: not ambient, recognized by a header."""

    name = "header"

    def __init__(self, user: RequestUser = STAFF, header: str = "x-test-user") -> None:
        self.user = user
        self.header = header

    async def authenticate(self, request: Any) -> Authentication | None:
        if request.headers.get(self.header) is None:
            return None
        return Authentication(method=self.name, user=self.user, ambient=False)


class NeverAuthentication:
    name = "never"

    async def authenticate(self, request: Any) -> Authentication | None:
        del request
        return None


def signed_in_session(*, is_staff: bool = False) -> SessionData:
    return SessionData(user_id=3, username="alice", is_active=True, is_staff=is_staff)


def authenticated_by_header(request: Any, user: RequestUser = STAFF) -> Any:
    """Record what the pipeline would for a header credential, beside an anonymous session."""
    request.ctx.session = SessionData()
    record_authentication(request, Authentication(method="header", user=user, ambient=False))
    return request


class RequestUserTest(unittest.TestCase):
    def test_anonymous_has_no_permission_at_all(self) -> None:
        self.assertEqual(
            (None, False, True, False, False, False),
            (
                ANONYMOUS_USER.id,
                ANONYMOUS_USER.is_authenticated,
                ANONYMOUS_USER.is_anonymous,
                ANONYMOUS_USER.is_active,
                ANONYMOUS_USER.is_staff,
                ANONYMOUS_USER.is_superuser,
            ),
        )

    def test_a_signed_in_user_needs_an_integer_id(self) -> None:
        with self.assertRaises(TypeError):
            RequestUser(id="7", username="ops")  # type: ignore[arg-type]

    def test_a_session_signs_in_only_an_active_user(self) -> None:
        self.assertIs(ANONYMOUS_USER, user_from_session(SessionData()))
        self.assertIs(ANONYMOUS_USER, user_from_session(SessionData(user_id=3, is_active=False, is_staff=True)))
        self.assertIs(ANONYMOUS_USER, user_from_session({"user_id": 3}))

        user = user_from_session(SessionData(user_id=3, username="alice", display_name="", is_active=True, is_staff=True))
        self.assertEqual(RequestUser(id=3, username="alice", display_name="alice", is_staff=True), user)

    def test_without_a_pipeline_the_session_answers(self) -> None:
        """Bare Sanic applications and hand-built test requests keep their old behavior."""
        bare = SimpleNamespace(ctx=SimpleNamespace(session=signed_in_session()))
        self.assertEqual(3, request_user(bare).id)
        self.assertIs(ANONYMOUS_USER, request_user(SimpleNamespace(ctx=SimpleNamespace())))


class ResolveAuthenticatorsTest(unittest.TestCase):
    def test_unset_means_the_session_when_sessions_are_on_and_nothing_otherwise(self) -> None:
        (only,) = resolve_authenticators(None, session_enabled=True)
        self.assertIsInstance(only, SessionAuthentication)
        self.assertEqual((), resolve_authenticators(None, session_enabled=False))

    def test_a_project_method_is_named_by_import_path(self) -> None:
        (method,) = resolve_authenticators([f"{__name__}.NeverAuthentication"], session_enabled=False)
        self.assertIsInstance(method, NeverAuthentication)

    def test_configuration_mistakes_are_refused_at_startup(self) -> None:
        cases = (
            (["session"], False, "web.session.enabled"),
            (["session", "session"], True, "twice"),
            (["sesion"], True, "unknown 'sesion'"),
        )
        for names, session_enabled, message in cases:
            with self.subTest(names=names), self.assertRaisesRegex(ValueError, message):
                resolve_authenticators(names, session_enabled=session_enabled)
        with self.assertRaisesRegex(TypeError, "authenticate"):
            resolve_authenticators([f"{__name__}.signed_in_session"], session_enabled=False)


class PipelineTest(unittest.TestCase):
    def test_the_first_method_to_recognize_a_credential_decides(self) -> None:
        other = RequestUser(id=99, username="other")
        app = Sanic("authentication_pipeline_order")
        try:
            install_authentication(app, (NeverAuthentication(), HeaderAuthentication(), HeaderAuthentication(user=other)))

            @app.get("/who")
            async def who(request):
                auth = request.ctx.auth
                return json({"id": request.ctx.user.id, "method": auth.method if auth else None})

            _, recognized = app.test_client.get("/who", headers={"x-test-user": "1"})
            _, anonymous = app.test_client.get("/who")
        finally:
            Sanic.unregister_app(app)

        self.assertEqual({"id": 7, "method": "header"}, recognized.json)
        self.assertEqual({"id": None, "method": None}, anonymous.json)


class PermissionsReadTheRequestUserTest(unittest.TestCase):
    """Every check answers for whatever the pipeline recorded, not only for a session."""

    def setUp(self) -> None:
        # A refusal names the site's login page, read from the settings.
        self.enterContext(patch.dict(conf.__dict__, {"settings": DefaultSettings()}))

    def test_decorators_accept_a_user_from_any_method(self) -> None:
        from oldman.web.auth import login_required, staff_required, superuser_required

        @login_required(response_mode="json", user_keyword="user_id")
        async def mine(request, user_id: int | None = None):
            return text(str(user_id))

        @staff_required(response_mode="json")
        async def staff_only(request):
            return text("staff")

        @superuser_required(response_mode="json")
        async def superuser_only(request):
            return text("superuser")

        request = authenticated_by_header(decorator_request())
        self.assertEqual(b"7", run_async(mine(request)).body)
        self.assertEqual(b"staff", run_async(staff_only(request)).body)
        self.assertEqual(403, run_async(superuser_only(request)).status)

        anonymous = decorator_request(session=SessionData())
        record_authentication(anonymous, None)
        self.assertEqual(401, run_async(mine(anonymous)).status)

    def test_http_method_view_gates_read_the_request_user(self) -> None:
        from oldman.web.http import HTTPMethodView

        class StaffView(HTTPMethodView):
            require_authenticated = True
            require_staff = True

            async def get(self, request):
                return text("ok")

        request = authenticated_by_header(view_request(headers={"accept": "application/json"}))
        self.assertEqual(b"ok", asyncio.run(StaffView().dispatch_request(request)).body)

    def test_admin_permission_and_self_protection_read_the_request_user(self) -> None:
        from oldman.apps.admin.model_admin import request_user_id
        from oldman.apps.admin.permissions import has_admin_permission

        request = authenticated_by_header(decorator_request())
        self.assertTrue(has_admin_permission(request))
        self.assertFalse(has_admin_permission(request, require_superuser=True))
        # Self-protection compares against this id; None would switch it off for token callers.
        self.assertEqual(7, request_user_id(request))

    def test_pages_about_this_browser_session_refuse_other_callers(self) -> None:
        from oldman.web.auth import authenticated_session
        from oldman.web.exceptions import Unauthorized

        with self.assertRaises(Unauthorized):
            authenticated_session(authenticated_by_header(decorator_request()))
        self.assertEqual(3, authenticated_session(decorator_request(session=signed_in_session())).user_id)
        with self.assertRaisesRegex(RuntimeError, "Session middleware"):
            authenticated_session(decorator_request(session=None))


class CsrfFollowsTheCredentialTest(unittest.TestCase):
    def test_only_a_non_ambient_credential_without_a_signed_in_session_is_exempt(self) -> None:
        header = Authentication(method="header", user=STAFF, ambient=False)
        cookie = Authentication(method="session", user=STAFF, ambient=True)
        cases = (
            (header, SessionData(), True),
            (header, signed_in_session(), False),
            (cookie, signed_in_session(), False),
            (None, SessionData(), False),
        )
        for auth, session, exempt in cases:
            with self.subTest(method=auth and auth.method, session=session.user_id):
                request = SimpleNamespace(ctx=SimpleNamespace(session=session))
                record_authentication(request, auth)
                self.assertIs(exempt, exempt_from_csrf(request))

    def test_enforce_csrf_skips_exempt_requests_and_checks_the_rest(self) -> None:
        from oldman.web.exceptions import CSRFFailure, Forbidden
        from oldman.web.security.csrf.decorators import enforce_csrf

        manager = Mock()
        manager.get_token_from_request.return_value = None

        enforce_csrf(manager, authenticated_by_header(decorator_request()))
        manager.get_token_from_request.assert_not_called()

        session_request = decorator_request(session=signed_in_session())
        record_authentication(session_request, Authentication(method="session", user=STAFF))
        with self.assertRaisesRegex(CSRFFailure, "CSRF token missing") as refused:
            enforce_csrf(manager, session_request)
        # Still a Forbidden for handlers; the page tells the visitor to reload instead of "no permission".
        self.assertTrue(issubclass(CSRFFailure, Forbidden))
        self.assertIn("Reload the page and try again.", refused.exception.page_description)


if __name__ == "__main__":
    unittest.main()
