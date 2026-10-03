"""The account pages: sign-in and sign-out, the user's own page and notifications, user management.

These are the framework's flows at the paths `web.account` and `i18n.preference_url` name; their pages are
the framework's `oldman/dashboard/account/*` templates, which a file of the same name under `templates/`
replaces. To let only some accounts sign in, pass `accept_user` to LoginFlow; to add password reset,
register a PasswordResetFlow beside them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from config.settings import settings
from oldman.web.auth import AccountFlow, LoginFlow, UserManagementFlow

if TYPE_CHECKING:
    from oldman.web.messages.notifications import NotificationRoutes
    from oldman.web.routing import WebApp

ACCOUNT_TEMPLATES = "oldman/dashboard/account"


def install_account_pages(app: WebApp, *, notification_routes: NotificationRoutes) -> None:
    """Register the account pages on `app`; the service calls this from init()."""
    account = settings.web.account
    LoginFlow(
        login_path=account.login_url,
        logout_path=account.logout_url,
        home_path=account.login_redirect_url,
        password_reset_path=account.password_reset_url,
    ).register_routes(app, template_prefix=ACCOUNT_TEMPLATES)
    AccountFlow(
        profile_path=account.profile_url,
        login_path=account.login_url,
        logout_path=account.logout_url,
        language_path=settings.i18n.preference_url,
        notification_routes=notification_routes,
        user_events_path=account.user_events_url,
    ).register_routes(app, template_prefix=ACCOUNT_TEMPLATES)
    UserManagementFlow(
        base_path=account.users_url,
        login_path=account.login_url,
    ).register_routes(app, template_prefix=ACCOUNT_TEMPLATES)
