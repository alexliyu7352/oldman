"""The signed-in user's own pages: profile, own password, language choice, notifications and user events."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from sanic import Sanic

import oldman.conf as conf
from oldman.auth.settings import AuthSettings
from oldman.db import DatabaseManager
from oldman.web.auth.flows import PageRenderer, resolve_page_renderer
from oldman.web.auth.user_session import (
    authenticated_session,
    render_session_password_modal,
    save_language_preference,
    session_profile,
    update_session_password,
)
from oldman.web.authentication import request_user
from oldman.web.http import access_denied_response
from oldman.web.i18n import language_registry
from oldman.web.routing import Router, router
from oldman.web.security.csrf import add_csrf_token, csrf_protect

if TYPE_CHECKING:
    from oldman.web.messages.notifications import NotificationRoutes
    from oldman.web.sse import SSEStream


def user_is_signed_in(request: Any) -> bool:
    """Whether the request comes from a signed-in user, however it authenticated; AccountFlow's default `allow`."""
    return request_user(request).is_authenticated


@dataclass
class AccountFlow:
    """The pages around one site's signed-in user.

    The profile page sits at `profile_path`, its password change at `/password-modal` and
    `/password` below it. The language choice is posted to `language_path` from any page,
    signed in or not, since the login page switches language too. With `notification_routes`
    (what the host's notifications `init_app` returned) the notification center page is
    installed at their `center_url`; with `user_events_path`, and only while
    `web.sse.enabled`, the user's event stream.

    A dashboard takes the paths from `settings.web.account` and `settings.i18n.preference_url`;
    the built-in Admin passes the ones under its prefix.
    """

    profile_path: str
    login_path: str
    logout_path: str
    language_path: str
    notification_routes: NotificationRoutes | None = None
    user_events_path: str | None = None
    auth_settings: AuthSettings | None = None
    db_manager: DatabaseManager | None = None

    @property
    def password_modal_path(self) -> str:
        """The own-password form, loaded into a modal on the profile page."""
        return f"{self.profile_path}/password-modal"

    @property
    def password_path(self) -> str:
        """Where the own-password form posts."""
        return f"{self.profile_path}/password"

    def register_routes(
        self,
        app: Sanic | Router | None = None,
        *,
        render: PageRenderer | None = None,
        template_prefix: str | None = None,
        allow: Callable[[Any], bool] = user_is_signed_in,
        name_prefix: str = "",
    ) -> str | None:
        """Install the pages; return the user events path when that stream was installed.

        Pages render through `render(request, page, **context)` or `<template_prefix>/<page>.html`:
        `user_session` with `session_profile`, `session_path`, `password_modal_path` and
        `logout_path`; `user_notifications` with `notification_center_content`. A request `allow`
        refuses (by default: one not signed in) gets 403 when signed in and the login protocol
        otherwise. Route names are `<name_prefix>user_session`, `..._user_session_password_modal`,
        `..._user_session_password_submit`, `..._language_preference`, `..._user_notifications`
        and `..._user_events`; `app` omitted, the routes register through `oldman.web.router`.
        """
        render_view = resolve_page_renderer(render, template_prefix)
        target = app if app is not None else router

        async def refuse(request: Any):
            return await access_denied_response(request, login_url=self.login_path)

        @add_csrf_token()
        async def user_session(request: Any):
            if not allow(request):
                return await refuse(request)
            return await render_view(
                request,
                "user_session",
                session_profile=session_profile(authenticated_session(request)),
                session_path=self.profile_path,
                password_modal_path=self.password_modal_path,
                logout_path=self.logout_path,
            )

        @add_csrf_token()
        async def password_modal(request: Any):
            if not allow(request):
                return await refuse(request)
            return await render_session_password_modal(
                request,
                action=self.password_path,
                auth_settings=self.auth_settings,
                db_manager=self.db_manager,
            )

        @csrf_protect()
        async def password_submit(request: Any):
            if not allow(request):
                return await refuse(request)
            # The change signs this browser out, so the answer only says so and sends it to the login page.
            return await update_session_password(
                request,
                login_url=self.login_path,
                auth_settings=self.auth_settings,
                db_manager=self.db_manager,
            )

        @csrf_protect()
        async def language_preference(request: Any):
            # Open to every visitor: the login page has a language switcher as well.
            return save_language_preference(request, registry=language_registry(request))

        target.add_route(cast(Any, user_session), self.profile_path, methods=["GET"], name=f"{name_prefix}user_session")
        target.add_route(cast(Any, password_modal), self.password_modal_path, methods=["GET"], name=f"{name_prefix}user_session_password_modal")
        target.add_route(cast(Any, password_submit), self.password_path, methods=["POST"], name=f"{name_prefix}user_session_password_submit")
        target.add_route(cast(Any, language_preference), self.language_path, methods=["POST"], name=f"{name_prefix}language_preference")

        if self.notification_routes is not None:

            async def user_notifications(request: Any):
                if not allow(request):
                    return await refuse(request)
                from oldman.web.messages.notifications import render_center_content

                content = await render_center_content(request, user_id=cast(int, request_user(request).id))
                return await render_view(request, "user_notifications", notification_center_content=content)

            target.add_route(
                cast(Any, user_notifications),
                self.notification_routes.center_url,
                methods=["GET"],
                name=f"{name_prefix}user_notifications",
            )

        if self.user_events_path is None or not conf.settings.web.sse.enabled:
            return None
        from oldman.web.sse import sse

        @sse.streaming(session_guard=True, login_url=self.login_path)
        async def stream_user_events(request: Any, stream: SSEStream) -> None:
            await stream.subscribe_user(cast(int, request_user(request).id))

        async def user_events(request: Any):
            if not allow(request):
                return await refuse(request)
            return await stream_user_events(request)

        target.add_route(cast(Any, user_events), self.user_events_path, methods=["GET"], name=f"{name_prefix}user_events")
        return self.user_events_path


def account_urls(request: Any = None) -> dict[str, Any]:
    """The site's account addresses for templates (a dashboard's topbar and base), from the settings.

    `user_events` is set only while `web.sse.enabled`; `notifications` holds the `center` and
    `topbar` URLs once the site installed notifications (`init_app` without a prefix).
    """
    account = conf.settings.web.account
    notifications = None
    app = getattr(request, "app", None)
    if app is not None:
        from oldman.web.messages.notifications import installed_routes

        routes = installed_routes(app)
        if routes is not None:
            notifications = {"center": routes.center_url, "topbar": routes.topbar_url}
    return {
        "login": account.login_url,
        "logout": account.logout_url,
        "profile": account.profile_url,
        "password_reset": account.password_reset_url,
        "user_events": account.user_events_url if conf.settings.web.sse.enabled else None,
        "notifications": notifications,
    }


__all__ = ["AccountFlow", "account_urls", "user_is_signed_in"]
