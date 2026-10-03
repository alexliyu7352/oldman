"""The login and logout steps every site shares: form values, error redirects and opening the session."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlencode

from sanic import Sanic
from sanic.response import HTTPResponse

import oldman.conf as conf
from oldman.auth import AbstractUser, touch_last_login, user_identity
from oldman.auth.backends import authenticate_with, resolve_login_backends
from oldman.auth.settings import AuthSettings, LoginSettings
from oldman.db import DatabaseManager
from oldman.i18n import gettext
from oldman.providers.redis import redis_key
from oldman.web.auth.flows import PageRenderer, resolve_page_renderer, session_is_authenticated
from oldman.web.auth.forms import LoginForm
from oldman.web.auth.permissions import role_ids_for_login
from oldman.web.auth.redirects import safe_next_url
from oldman.web.auth.session import session_data_for_user
from oldman.web.authentication import forget_session_authentication, record_authentication, session_authentication
from oldman.web.request import client_ip, get_arg
from oldman.web.response import redirect_response
from oldman.web.routing import Router, router
from oldman.web.security.csrf import add_csrf_token, csrf_protect
from oldman.web.security.rate_limiter import WindowCounter, redis_rate_limiter, window_retry_after
from oldman.web.session import Session, SessionData

INVALID_CREDENTIALS = "invalid_credentials"
RATE_LIMITED = "rate_limited"
LOGIN_RATE_LIMIT_PATH = "login"


def login_settings(auth_settings: AuthSettings | None = None) -> LoginSettings:
    """The sign-in limits of the given or the installed Auth app."""
    if auth_settings is not None:
        return auth_settings.login

    from oldman.auth.apps import app as auth_app

    return auth_app.settings.login


@dataclass
class LoginRateLimit:
    """Fixed windows over failed sign-ins, counted per client address and per username.

    Only failures count. Someone who signs in on the first try never touches a counter, so
    the limits can sit low enough to matter without getting in an ordinary visitor's way.

    Both counters are read before the password is checked, so a caller that has already
    spent its budget is turned away without costing the server a PBKDF2 round — which is
    the expensive half of a sign-in, and the half an attacker would otherwise get for free.
    """

    auth_settings: AuthSettings | None = None
    counter: WindowCounter | None = None

    def window_counter(self) -> WindowCounter:
        """The Redis fixed window, under this service's own sign-in namespace."""
        if self.counter is None:
            self.counter = redis_rate_limiter(namespace=redis_key("ratelimit", LOGIN_RATE_LIMIT_PATH))
        return self.counter

    async def retry_after(self, request: Any, username: str) -> int | None:
        """Seconds this caller must wait, or None when the attempt may go ahead."""
        settings = login_settings(self.auth_settings)
        counter = self.window_counter()
        address = client_ip(request)
        if settings.ip_limit and address:
            spent = await counter.count(f"ip:{address}", LOGIN_RATE_LIMIT_PATH, settings.ip_window)
            if spent >= settings.ip_limit:
                return window_retry_after(settings.ip_window)
        subject = _username_subject(username)
        if settings.username_limit and subject:
            spent = await counter.count(subject, LOGIN_RATE_LIMIT_PATH, settings.username_window)
            if spent >= settings.username_limit:
                return window_retry_after(settings.username_window)
        return None

    async def record_failure(self, request: Any, username: str) -> None:
        """Charge one failed attempt to both the client address and the username."""
        settings = login_settings(self.auth_settings)
        counter = self.window_counter()
        address = client_ip(request)
        if settings.ip_limit and address:
            await counter.record(f"ip:{address}", LOGIN_RATE_LIMIT_PATH, settings.ip_window)
        subject = _username_subject(username)
        if settings.username_limit and subject:
            await counter.record(subject, LOGIN_RATE_LIMIT_PATH, settings.username_window)


def _username_subject(username: str) -> str:
    """The counter subject for one attempted username, or empty when there is nothing to count.

    Case is folded even though the lookup itself is case-sensitive: otherwise "alex",
    "Alex" and "ALEX" would each get their own budget for attacking the same account.
    """
    normalized = username.strip().casefold()
    return f"user:{normalized}" if normalized else ""


def form_value(request: Any, key: str, default: str = "") -> str:
    """One scalar form field as text (Sanic form values arrive as lists).

    提交上来的空串就是空串，不回退到 `default`：`default` 回答的是"表单里没有这个字段"，把两者混成
    一件事的话，用户清空一个字段等于恢复默认值。
    """
    value = get_arg(getattr(request, "form", None) or {}, key, default)
    return default if value is None else str(value)


def remember_me_requested(request: Any) -> bool:
    """Whether the login form asked for the long session lifetime."""
    return form_value(request, "remember_me").strip().lower() not in {"", "0", "false", "off", "n", "no"}


def login_error_url(login_path: str, next_url: str, error_code: str) -> str:
    """Back to the login page with the error code and the pending next URL (the page re-issues its CSRF token)."""
    return f"{login_path}?{urlencode({'next': next_url, 'error': error_code})}"


def login_error_message(error_code: object) -> str:
    """The safe message for an error code from the URL; unknown codes show nothing."""
    code = error_code[0] if isinstance(error_code, list | tuple) and error_code else error_code
    messages = {
        INVALID_CREDENTIALS: gettext("Invalid username or password."),
        RATE_LIMITED: gettext("Too many sign-in attempts. Please try again later."),
    }
    return messages.get(str(code or ""), "")


async def authenticate_credentials(request: Any, **credentials: Any) -> AbstractUser | None:
    """Return the User a sign-in credential belongs to, asking the configured login backends.

    The backends named in ``web.auth.login_backends`` are tried in order and the first to
    accept the credential decides. Pass the credential as keyword arguments —
    ``username=`` and ``password=`` for the built-in ``users`` backend.

    A disabled account never signs in, whichever backend vouched for it: that is the floor
    every login stands on (the built-in Admin's staff rule and a dashboard's "any active
    user" both build on it), and a request user is taken to be active from then on.
    """
    backends = resolve_login_backends(tuple(conf.settings.web.auth.login_backends))
    user = await authenticate_with(backends, request, **credentials)
    if user is None or not bool(user.is_active):
        return None
    return user


async def login_user(
    request: Any,
    user: Any,
    *,
    response: Any,
    remember: bool = False,
    auth_settings: AuthSettings | None = None,
    db_manager: DatabaseManager | None = None,
) -> Any:
    """Open the exclusive session for an authenticated user and attach its cookie to `response`.

    The session class is the one the Session middleware attached to the request; "remember me" only
    picks the longer server-side lifetime, the cookie follows it. The user's other sessions end.
    """
    request_session = getattr(request.ctx, "session", None)
    if not isinstance(request_session, SessionData):
        raise RuntimeError("Login requires the Session middleware")
    session_settings = conf.settings.web.session
    expiry = session_settings.remember_expiry if remember else session_settings.expiry
    role_ids = await role_ids_for_login(request, user_identity(user), db_manager=db_manager)
    session_data = session_data_for_user(type(request_session), user, expiry=expiry, login_ip=client_ip(request), role_ids=role_ids)
    session_manager = getattr(request.app.ctx, "session", None)
    if session_manager is None:
        raise RuntimeError("Login requires the Session extension on the application")
    new_session_id = await session_manager.exclusive_login(session_data)
    await touch_last_login(user_identity(user), auth_settings=auth_settings, db_manager=db_manager)
    session_manager.update_session_id_to_cookie(response, new_session_id, session_data)
    # From here on the request is the user who just signed in, as Django's login() makes it.
    record_authentication(request, session_authentication(session_data))
    return response


async def logout_user(request: Any, redirect_to: str) -> Any:
    """End the current session, schedule the cookie removal and redirect."""
    await Session.logout_session(request)
    forget_session_authentication(request)
    return redirect_response(redirect_to)


@dataclass
class LoginFlow:
    """The login page, its submit and sign-out for one site.

    Every login stands on one floor, an active account, which `authenticate_credentials`
    enforces. `accept_user` is what a site adds on top: None admits every active user (a
    dashboard's default), the built-in Admin passes its staff rule. Failed sign-ins count
    against `rate_limit`, by default the limits of `auth_settings`.

    A dashboard takes the paths from `settings.web.account`; the Admin passes the ones under its
    prefix. `home_path` is where a sign-in lands without a safe `next`.
    """

    login_path: str
    logout_path: str
    home_path: str
    password_reset_path: str | None = None
    accept_user: Callable[[AbstractUser], bool] | None = None
    rate_limit: LoginRateLimit | None = None
    auth_settings: AuthSettings | None = None
    db_manager: DatabaseManager | None = None

    def limiter(self) -> LoginRateLimit:
        """The failed sign-in limits the submit applies."""
        if self.rate_limit is None:
            self.rate_limit = LoginRateLimit(auth_settings=self.auth_settings)
        return self.rate_limit

    def register_routes(
        self,
        app: Sanic | Router | None = None,
        *,
        render: PageRenderer | None = None,
        template_prefix: str | None = None,
        is_authenticated: Callable[[Any], bool] = session_is_authenticated,
        name_prefix: str = "",
    ) -> None:
        """Install the login page and its submit at `login_path`, and sign-out at `logout_path`.

        The page renders through `render(request, "login", **context)` or, without one, through
        `render_template("<template_prefix>/login.html")`. The context carries `login_form`,
        `login_url`, `next_url`, `login_error` and `password_reset_url`. A browser that
        `is_authenticated` (by default: its session is signed in) skips the page for its `next`.
        Route names are `<name_prefix>login`, `..._login_submit` and `..._logout`; `app` omitted,
        the routes register through `oldman.web.router`.
        """
        render_view = resolve_page_renderer(render, template_prefix)

        async def login_page(request: Any, *, error: object, next_url: str) -> HTTPResponse:
            return await render_view(
                request,
                "login",
                login_form=LoginForm(request=request),
                login_url=self.login_path,
                next_url=next_url,
                login_error=login_error_message(error),
                password_reset_url=self.password_reset_path,
            )

        @add_csrf_token()
        async def login(request: Any):
            next_url = safe_next_url(request.args.get("next"), self.home_path)
            if is_authenticated(request):
                return redirect_response(next_url)
            return await login_page(request, error=request.args.get("error"), next_url=next_url)

        @csrf_protect()
        @add_csrf_token()
        async def login_submit(request: Any):
            next_url = safe_next_url(form_value(request, "next", str(request.args.get("next", "") or "")), self.home_path)
            username = form_value(request, "username").strip()
            limiter = self.limiter()
            # Before the password is checked, so a spent budget costs no PBKDF2 round.
            retry_after = await limiter.retry_after(request, username)
            if retry_after is not None:
                response = await login_page(request, error=RATE_LIMITED, next_url=next_url)
                response.status = 429
                response.headers["Retry-After"] = str(retry_after)
                return response
            user = await authenticate_credentials(
                request,
                username=username,
                password=form_value(request, "password"),
                auth_settings=self.auth_settings,
                db_manager=self.db_manager,
            )
            # Refused by the site's own rule, an account gets the wrong-password answer: telling
            # them apart would confirm the password was right.
            if user is None or (self.accept_user is not None and not self.accept_user(user)):
                await limiter.record_failure(request, username)
                return redirect_response(login_error_url(self.login_path, next_url, INVALID_CREDENTIALS), status=303)
            return await login_user(
                request,
                user,
                response=redirect_response(next_url),
                remember=remember_me_requested(request),
                auth_settings=self.auth_settings,
                db_manager=self.db_manager,
            )

        async def logout(request: Any):
            return await logout_user(request, self.login_path)

        target = app if app is not None else router
        target.add_route(cast(Any, login), self.login_path, methods=["GET"], name=f"{name_prefix}login")
        target.add_route(cast(Any, login_submit), self.login_path, methods=["POST"], name=f"{name_prefix}login_submit")
        target.add_route(cast(Any, logout), self.logout_path, methods=["GET"], name=f"{name_prefix}logout")


__all__ = [
    "INVALID_CREDENTIALS",
    "LoginFlow",
    "authenticate_credentials",
    "LOGIN_RATE_LIMIT_PATH",
    "RATE_LIMITED",
    "LoginRateLimit",
    "form_value",
    "login_error_message",
    "login_error_url",
    "login_settings",
    "login_user",
    "logout_user",
    "remember_me_requested",
]
