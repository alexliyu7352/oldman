"""The login and logout steps every site shares: form values, error redirects and opening the session."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import oldman.conf as conf
from oldman.auth import touch_last_login, user_identity
from oldman.auth.settings import AuthSettings, LoginSettings
from oldman.db import DatabaseManager
from oldman.i18n import gettext
from oldman.web.auth.session import session_data_for_user
from oldman.web.request import client_ip, get_arg
from oldman.web.response import redirect_response
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
            self.counter = redis_rate_limiter(namespace=f"{conf.settings.core.app_name}:{LOGIN_RATE_LIMIT_PATH}")
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
    session_data = session_data_for_user(type(request_session), user, expiry=expiry, login_ip=client_ip(request))
    session_manager = getattr(request.app.ctx, "session", None)
    if session_manager is None:
        raise RuntimeError("Login requires the Session extension on the application")
    new_session_id = await session_manager.exclusive_login(session_data)
    await touch_last_login(user_identity(user), auth_settings=auth_settings, db_manager=db_manager)
    session_manager.update_session_id_to_cookie(response, new_session_id, session_data)
    return response


async def logout_user(request: Any, redirect_to: str) -> Any:
    """End the current session, schedule the cookie removal and redirect."""
    await Session.logout_session(request)
    return redirect_response(redirect_to)


__all__ = [
    "INVALID_CREDENTIALS",
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
