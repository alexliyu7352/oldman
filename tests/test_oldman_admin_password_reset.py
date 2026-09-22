"""Admin password reset flow: request, mail, confirm and complete."""

from __future__ import annotations

import asyncio
import re
import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import ANY, AsyncMock, patch

import oldman.conf as conf
from oldman import mail
from oldman.apps.admin import AdminSite, install_admin
from oldman.apps.admin.settings import AdminSettings
from oldman.auth import AuthSettings, PasswordResetTokenGenerator, encode_user_id
from oldman.conf.schemas import MailConfig
from oldman.mail import use_mail_config
from oldman.tasks import BackgroundTaskManager
from oldman.web.auth.forms import LoginForm
from oldman.web.session import Session
from tests.test_oldman_admin_runtime import (
    FakeApp,
    FakeSession,
    make_admin_user,
    make_post_request,
    make_request,
    render_with_request_environment,
    runtime_settings,
)

LOCMEM = "oldman.mail.backends.locmem.LocmemEmailBackend"
FLOW = "oldman.web.auth.password_reset"


class FakeRateLimiter:
    """Records every limiter call and answers from a script keyed by subject prefix."""

    def __init__(self, limited: set[str] | None = None) -> None:
        self.limited = limited or set()
        self.calls: list[tuple[str, str, int, int]] = []

    async def is_rate_limited(self, subject: int | str, path: str, limit: int, period: int) -> bool:
        self.calls.append((str(subject), path, limit, period))
        return any(str(subject).startswith(prefix) for prefix in self.limited)


class AdminPasswordResetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = runtime_settings()
        self.settings.web.domain = "https://admin.example.test"
        self.enterContext(patch.dict(conf.__dict__, {"settings": self.settings}))
        # Sanic-Ext's render needs a registered Sanic app; render straight from the fake app's environment.
        self.enterContext(patch("oldman.apps.admin.site.render_template", side_effect=render_with_request_environment))
        self.enterContext(use_mail_config(MailConfig(backend=LOCMEM, default_from_email="noreply@example.test")))
        mail.outbox.clear()
        self.addCleanup(mail.outbox.clear)
        self.limiter = FakeRateLimiter()
        self.app = FakeApp()
        # A private manager: the real one is a process singleton shared with every other test.
        self.app.ctx.tasks = cast(Any, BackgroundTaskManager).__wrapped__()
        self.auth_settings = AuthSettings()
        self.user = make_admin_user()
        install_admin(
            self.app,
            db_manager=object(),  # type: ignore[arg-type]
            admin_site=AdminSite("runtime_password_reset_admin"),
            prefix="/control",
            auth_settings=self.auth_settings,
            admin_settings=AdminSettings(),
            password_reset_rate_limiter=self.limiter,
        )
        self.generator = PasswordResetTokenGenerator(self.settings.web.security.secret_key, expiry=self.auth_settings.password_reset.expiry)

    def handler(self, path: str, method: str):
        return self.app.route_handlers[(path, (method,))]

    def get(self, path: str, **kwargs):
        request = make_request(self.app, path=path, session=FakeSession())
        request.ctx.csrf_token = "test-token"
        request.ip = "203.0.113.9"
        request.client_ip = None
        return request

    def post(self, path: str, form: dict[str, str]):
        request = make_post_request(self.app, path=path, session=FakeSession(), accept="text/html", form=form)
        request.ip = "203.0.113.9"
        request.client_ip = None
        return request

    def submit_request(self, form: dict[str, str]):
        """POST the request form and let the spawned mail task finish inside the same loop."""
        handler = self.handler("/control/password-reset", "POST")

        async def run():
            response = await handler(self.post("/control/password-reset", form))  # type: ignore[operator]
            pending = [info.task for info in self.app.ctx.tasks.tasks.values() if info.task is not None]
            await asyncio.gather(*pending, return_exceptions=True)
            await asyncio.sleep(0)
            return response

        return asyncio.run(run())

    def test_routes_and_login_link_are_installed(self) -> None:
        routes = dict(self.app.routes)
        for path in (
            "/control/password-reset",
            "/control/password-reset/sent",
            "/control/password-reset/done",
            "/control/password-reset/<uidb64:str>/<token:str>",
        ):
            self.assertIn(path, routes)
        request = self.get("/control/login")
        login_html = self.app.ext.environment.get_template("admin/login.html").render(
            admin_prefix="/control",
            admin_bundle_name="oldman:admin",
            admin_is_authenticated=False,
            admin_extension_bundle_name=None,
            admin_i18n={},
            dashboard_body_classes=" oldman-auth-page",
            page_entry="admin",
            request=request,
            menu_items=[],
            login_error="",
            next_url="/control",
            login_form=LoginForm(request=request),
        )
        self.assertIn('href="/control/password-reset"', login_html)
        self.assertIn("Forgot password?", login_html)

    def test_request_page_renders_the_email_form_with_no_referrer(self) -> None:
        response = asyncio.run(self.handler("/control/password-reset", "GET")(self.get("/control/password-reset")))  # type: ignore[operator]
        body = response.body.decode("utf-8")

        self.assertEqual(200, response.status)
        self.assertEqual("no-referrer", response.headers["Referrer-Policy"])
        self.assertEqual("no-store", response.headers["Cache-Control"])
        self.assertIn('name="email"', body)
        self.assertIn('action="/control/password-reset"', body)
        self.assertIn('href="/control/login"', body)

    def test_unknown_and_known_addresses_get_the_same_redirect_but_only_one_mail(self) -> None:
        with patch(f"{FLOW}.get_user_by_email", AsyncMock(return_value=None)):
            unknown = self.submit_request({"email": "nobody@example.test"})
        self.assertEqual(303, unknown.status)
        self.assertEqual("/control/password-reset/sent", unknown.headers["Location"])
        self.assertEqual([], mail.outbox)

        with patch(f"{FLOW}.get_user_by_email", AsyncMock(return_value=self.user)) as lookup:
            known = self.submit_request({"email": " Alice@Example.test "})
        self.assertEqual(303, known.status)
        self.assertEqual("/control/password-reset/sent", known.headers["Location"])
        lookup.assert_awaited_once()
        assert lookup.await_args is not None
        self.assertEqual("alice@example.test", lookup.await_args.args[0])
        self.assertEqual(1, len(mail.outbox))
        message = mail.outbox[0]
        self.assertEqual(["alice@example.test"], message.to)
        self.assertEqual("Reset your Oldman Admin password", message.subject)
        match = re.search(r"https://admin\.example\.test/control/password-reset/([A-Za-z0-9_-]+)/([0-9a-z]+-[0-9a-f]{32})", message.body)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(encode_user_id(self.user.id), match.group(1))
        self.assertTrue(self.generator.check_token(self.user, match.group(2)))
        # Both limits were consulted: the IP first, then the normalised address.
        self.assertEqual(
            [("ip:203.0.113.9", "password-reset", 5, 900), ("email:nobody@example.test", "password-reset", 3, 3600)], self.limiter.calls[:2]
        )
        # The mail went out from a background task that is gone once delivered.
        self.assertEqual({}, self.app.ctx.tasks.get_all_status())

    def test_a_mail_failure_is_logged_and_the_page_still_says_sent(self) -> None:
        with (
            patch(f"{FLOW}.get_user_by_email", AsyncMock(return_value=self.user)),
            patch(f"{FLOW}.send_templated_mail", AsyncMock(side_effect=OSError("smtp down"))),
            self.assertLogs("default.web.auth.password_reset", level="ERROR") as logs,
        ):
            response = self.submit_request({"email": "alice@example.test"})

        self.assertEqual(303, response.status)
        self.assertEqual("/control/password-reset/sent", response.headers["Location"])
        self.assertTrue(any(f"user {self.user.id} could not be sent" in line for line in logs.output))
        self.assertEqual([], mail.outbox)
        self.assertEqual({}, self.app.ctx.tasks.get_all_status())

    def test_the_ip_limit_keys_on_the_proxy_aware_client_address(self) -> None:
        handler = self.handler("/control/password-reset", "POST")
        request = self.post("/control/password-reset", {"email": "alice@example.test"})
        request.client_ip = "198.51.100.7"  # what Sanic derives from X-Forwarded-For behind a trusted proxy
        request.ip = "10.0.0.1"  # the proxy itself; every visitor would share this bucket
        with patch(f"{FLOW}.get_user_by_email", AsyncMock(return_value=None)):
            asyncio.run(handler(request))  # type: ignore[operator]
        self.assertEqual(("ip:198.51.100.7", "password-reset", 5, 900), self.limiter.calls[0])

    def test_limits_answer_429_for_the_ip_and_a_silent_skip_for_the_address(self) -> None:
        with patch(f"{FLOW}.get_user_by_email", AsyncMock(return_value=self.user)):
            self.limiter.limited = {"email:"}
            skipped = self.submit_request({"email": "alice@example.test"})
            self.assertEqual(303, skipped.status)
            self.assertEqual([], mail.outbox)

            self.limiter.limited = {"ip:"}
            blocked = self.submit_request({"email": "alice@example.test"})
        self.assertEqual(429, blocked.status)
        self.assertEqual("900", blocked.headers["Retry-After"])
        self.assertIn("Too many requests", blocked.body.decode("utf-8"))
        self.assertEqual([], mail.outbox)

    def test_invalid_email_input_rerenders_the_form_with_a_fresh_csrf_token(self) -> None:
        response = asyncio.run(self.handler("/control/password-reset", "POST")(self.post("/control/password-reset", {"email": "not-an-email"})))  # type: ignore[operator]
        body = response.body.decode("utf-8")
        self.assertEqual(200, response.status)
        self.assertIn("Enter a valid email address", body)
        # The POST re-render must carry a usable token, or the corrected resubmit is rejected with 403.
        self.assertRegex(body, r'name="csrfmiddlewaretoken" value="[^"]+"')
        self.assertEqual([], self.limiter.calls)

    def test_confirm_page_accepts_a_live_token_and_rejects_a_dead_one(self) -> None:
        uid = encode_user_id(self.user.id)
        token = self.generator.make_token(self.user)
        page = self.handler("/control/password-reset/<uidb64:str>/<token:str>", "GET")
        with patch(f"{FLOW}.get_user_by_id", AsyncMock(return_value=self.user)):
            valid = asyncio.run(page(self.get(f"/control/password-reset/{uid}/{token}"), uid, token))  # type: ignore[operator]
            stale = asyncio.run(page(self.get(f"/control/password-reset/{uid}/{token}x"), uid, token + "x"))  # type: ignore[operator]
        with patch(f"{FLOW}.get_user_by_id", AsyncMock(return_value=None)):
            missing = asyncio.run(page(self.get("/control/password-reset/nope/x-y"), "nope", "x-y"))  # type: ignore[operator]

        self.assertEqual(200, valid.status)
        body = valid.body.decode("utf-8")
        self.assertIn('name="password"', body)
        self.assertIn('name="confirm_password"', body)
        self.assertIn(f'action="/control/password-reset/{uid}/{token}"', body)
        self.assertEqual("no-referrer", valid.headers["Referrer-Policy"])
        for response in (stale, missing):
            self.assertEqual(200, response.status)
            self.assertIn("This link is no longer valid", response.body.decode("utf-8"))
            self.assertIn('href="/control/password-reset"', response.body.decode("utf-8"))

    def test_completing_the_reset_changes_the_password_and_ends_other_sessions(self) -> None:
        uid = encode_user_id(self.user.id)
        token = self.generator.make_token(self.user)
        submit = self.handler("/control/password-reset/<uidb64:str>/<token:str>", "POST")
        # The flow reaches the store through the installed extension, so the double is its interface.
        session_interface = SimpleNamespace(force_logout_user=AsyncMock(return_value=("s1",)), _logout_request=AsyncMock())
        session_manager = Session()
        session_manager.interface = cast(Any, session_interface)
        self.app.ctx.session = session_manager
        path = f"/control/password-reset/{uid}/{token}"

        with patch(f"{FLOW}.get_user_by_id", AsyncMock(return_value=self.user)):
            mismatch = asyncio.run(submit(self.post(path, {"password": "NewPass!2026", "confirm_password": "Other!2026"}), uid, token))  # type: ignore[operator]
            self.assertEqual(200, mismatch.status)
            self.assertIn("Passwords do not match", mismatch.body.decode("utf-8"))
            self.assertRegex(mismatch.body.decode("utf-8"), r'name="csrfmiddlewaretoken" value="[^"]+"')

            with patch(f"{FLOW}.change_user_password", AsyncMock(return_value=self.user)) as change:
                done = asyncio.run(submit(self.post(path, {"password": "NewPass!2026", "confirm_password": "NewPass!2026"}), uid, token))  # type: ignore[operator]

        self.assertEqual(303, done.status)
        self.assertEqual("/control/password-reset/done", done.headers["Location"])
        change.assert_awaited_once_with(self.user.id, "NewPass!2026", auth_settings=self.auth_settings, db_manager=ANY)
        session_interface.force_logout_user.assert_awaited_once_with(self.user.id)

        # After a real password change the same link no longer verifies.
        self.user.set_password("NewPass!2026")
        self.assertFalse(self.generator.check_token(self.user, token))

    def test_sent_and_done_pages_render(self) -> None:
        sent = asyncio.run(self.handler("/control/password-reset/sent", "GET")(self.get("/control/password-reset/sent")))  # type: ignore[operator]
        done = asyncio.run(self.handler("/control/password-reset/done", "GET")(self.get("/control/password-reset/done")))  # type: ignore[operator]
        self.assertIn("24 hours", sent.body.decode("utf-8"))
        self.assertIn('href="/control/login"', done.body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
