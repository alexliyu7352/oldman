"""Shared Web account template behavior tests."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from oldman.web.auth import UserPasswordForm, UserSessionProfile
from oldman.web.template import default_template_environment, render_component_template


class SharedUserSessionTemplateTest(unittest.IsolatedAsyncioTestCase):
    """Render the package templates consumed by Admin and Dashboard shells."""

    async def test_account_controls_use_caller_paths_and_identity(self) -> None:
        """The shared menu should not hard-code either application prefix."""
        environment = default_template_environment()
        template = environment.from_string(
            """
            {% from "oldman/auth/partials/account_controls.html" import user_account_controls with context %}
            {{ user_account_controls(
              display_name="Alice",
              session_path="/control/user-session",
              logout_path="/control/sign-out",
              subtitle="Admin"
            ) }}
            """
        )

        html = await template.render_async()

        self.assertIn("Alice", html)
        self.assertIn("Admin", html)
        self.assertIn('href="/control/user-session"', html)
        self.assertIn('href="/control/sign-out"', html)
        self.assertIn('data-om-component="dropdown"', html)

    async def test_session_content_preserves_source_page_and_modal_contract(self) -> None:
        """Both shells should receive one source-compatible session page body."""
        environment = default_template_environment()
        template = environment.from_string(
            '{% include "oldman/auth/user_session_content.html" %}'
        )
        profile = UserSessionProfile(
            username="alice",
            display_name="Alice",
            login_ip="127.0.0.1",
            login_time="2023-11-14 22:13 UTC",
            is_active=True,
            is_staff=True,
            is_superuser=False,
        )

        html = await template.render_async(
            session_profile=profile,
            session_path="/control/user-session",
            password_modal_path="/control/user-session/password-modal",
            logout_path="/control/sign-out",
        )

        for value in ("alice", "Alice", "127.0.0.1", "2023-11-14 22:13 UTC"):
            self.assertIn(value, html)
        self.assertIn('id="user-session-feedback"', html)
        self.assertIn('id="user-session-permissions-modal"', html)
        self.assertIn('id="user-session-password-modal"', html)
        self.assertIn(
            'data-om-modal-url="/control/user-session/password-modal"',
            html,
        )
        self.assertIn('href="/control/sign-out"', html)

    async def test_password_fragment_uses_shared_form_renderer_and_clean_identity_layout(self) -> None:
        """The current-user Modal should retain password toggles without badge styling."""
        form = UserPasswordForm(
            request=SimpleNamespace(ctx=SimpleNamespace(csrf_token="csrf-token"))
        )
        user = SimpleNamespace(
            username="very_long_account_name",
            email="alice@example.test",
        )

        html = str(
            await render_component_template(
                form,
                "oldman/auth/partials/password_form.html",
                {
                    "action": "/control/user-session/password",
                    "form": form,
                    "user": user,
                },
            )
        )

        self.assertIn('action="/control/user-session/password"', html)
        self.assertIn("very_long_account_name", html)
        self.assertIn("alice@example.test", html)
        self.assertIn('data-om-password-toggle', html)
        self.assertNotIn("om-badge", html)

    def test_admin_does_not_keep_private_password_fragment_copy(self) -> None:
        """Admin 的用户密码 Modal 只能指向框架共享片段。"""
        root = Path(__file__).resolve().parents[1]

        self.assertFalse(
            (
                root
                / "oldman"
                / "apps"
                / "admin"
                / "templates"
                / "admin"
                / "model"
                / "password_modal_form.html"
            ).exists()
        )
        self.assertIn(
            '"oldman/auth/partials/password_form.html"',
            (root / "oldman" / "apps" / "admin" / "site.py").read_text(
                encoding="utf-8"
            ),
        )


if __name__ == "__main__":
    unittest.main()
