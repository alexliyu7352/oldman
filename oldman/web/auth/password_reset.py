"""Password reset flow shared by the Admin site and project login pages.

Request page → "check your email" page → link from the mail → set-password page → done page. The
request page answers the same way whether or not the address has an account; the token comes from
`oldman.auth.password_reset` and needs no storage.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from sanic import Sanic
from sanic.response import HTTPResponse
from wtforms.validators import DataRequired

import oldman.conf as conf
from oldman.auth import (
    change_user_password,
    decode_user_id,
    encode_user_id,
    get_user_by_email,
    get_user_by_id,
    user_identity,
)
from oldman.auth.base import AbstractUser
from oldman.auth.password_reset import PasswordResetTokenGenerator, password_reset_settings
from oldman.auth.settings import AuthSettings
from oldman.db import DatabaseManager
from oldman.i18n import gettext_lazy
from oldman.logging import get_logger
from oldman.mail import send_templated_mail
from oldman.providers.redis import redis_key
from oldman.web.auth.flows import PageRenderer, resolve_page_renderer, session_is_authenticated
from oldman.web.auth.forms import UserPasswordForm
from oldman.web.auth.session import revoke_user_logins
from oldman.web.components.forms import EmailField, TailwindForm
from oldman.web.request import client_ip
from oldman.web.response import redirect_response
from oldman.web.routing import Router, router
from oldman.web.security.csrf import add_csrf_token, csrf_protect
from oldman.web.security.rate_limiter import RateLimiter, redis_rate_limiter

logger = get_logger("default.web.auth.password_reset")

RATE_LIMIT_PATH = "password-reset"


class PasswordResetRequestForm(TailwindForm):
    """Ask for the account's email address."""

    email = EmailField(
        cast(str, gettext_lazy("Email")),
        id="email",
        validators=[DataRequired()],
        render_kw={
            "required": True,
            "inputmode": "email",
            "placeholder": gettext_lazy("you@example.com"),
            "autofocus": True,
        },
    )


class PasswordResetForm(UserPasswordForm):
    """New password plus confirmation, under the shared password policy."""


class RequestOutcome(enum.Enum):
    """What happened to a reset request; SENT and SKIPPED must look the same to the browser."""

    SENT = "sent"
    SKIPPED = "skipped"
    IP_LIMITED = "ip_limited"


@dataclass
class PasswordResetFlow:
    """Paths, settings and collaborators for one site's reset flow.

    The request page sits at `base_path`; the "check your email" page at `<base_path>/sent`, the
    set-password page at `<base_path>/<uidb64>/<token>` and the finished page at `<base_path>/done`.
    A dashboard passes `settings.web.account.password_reset_url`, the address its login page links
    to; the built-in Admin passes the one under its prefix. `home_path` is where a browser that is
    already signed in goes instead of the request page.
    """

    base_path: str
    login_path: str
    home_path: str | None = None
    # The name the mail calls the site by; None takes the site name (core.site_name, else core.app_name).
    site_name: str | None = None
    mail_template: str = "oldman/auth/mail/password_reset"
    auth_settings: AuthSettings | None = None
    db_manager: DatabaseManager | None = None
    token_generator: PasswordResetTokenGenerator | None = None
    rate_limiter: RateLimiter | None = None
    public_url: str | None = None

    @property
    def request_path(self) -> str:
        """The request page and its submit."""
        return self.base_path

    @property
    def sent_path(self) -> str:
        """Where a submitted request lands, mail or not."""
        return f"{self.base_path}/sent"

    @property
    def done_path(self) -> str:
        """Where a new password lands."""
        return f"{self.base_path}/done"

    def confirm_path(self, uidb64: str, token: str) -> str:
        """The set-password page one mailed link opens."""
        return f"{self.base_path}/{uidb64}/{token}"

    def generator(self) -> PasswordResetTokenGenerator:
        """Token generator bound to this flow's reset settings (lifetime from `auth_settings`)."""
        if self.token_generator is None:
            self.token_generator = PasswordResetTokenGenerator(expiry=password_reset_settings(self.auth_settings).expiry)
        return self.token_generator

    def limiter(self) -> RateLimiter:
        if self.rate_limiter is None:
            self.rate_limiter = redis_rate_limiter(namespace=redis_key("ratelimit", RATE_LIMIT_PATH))
        return self.rate_limiter

    async def request_reset(self, request: Any, email: str, *, language: str | None = None) -> RequestOutcome:
        """Apply both limits, look the address up and mail the link when there is an active account."""
        settings = password_reset_settings(self.auth_settings)
        address = client_ip(request)
        if (
            settings.ip_limit
            and address
            and await self.limiter().is_rate_limited(f"ip:{address}", RATE_LIMIT_PATH, settings.ip_limit, settings.ip_window)
        ):
            logger.info("Password reset requests from %s exceed the IP limit", address)
            return RequestOutcome.IP_LIMITED

        normalized = email.strip().lower()
        if settings.email_limit and await self.limiter().is_rate_limited(
            f"email:{normalized}", RATE_LIMIT_PATH, settings.email_limit, settings.email_window
        ):
            logger.info("Password reset mails for %s exceed the address limit", normalized)
            return RequestOutcome.SKIPPED

        user = await get_user_by_email(normalized, auth_settings=self.auth_settings, db_manager=self.db_manager)
        if user is None or not bool(user.is_active) or not user.email:
            return RequestOutcome.SKIPPED
        # The browser never waits for SMTP: a slow or failing mail server would otherwise tell it
        # which addresses have accounts. Delivery problems go to the log, not to the page.
        request.app.ctx.tasks.spawn(self.deliver_reset_mail, user, language=language)
        return RequestOutcome.SENT

    def reset_url(self, user: AbstractUser) -> str:
        """Absolute link for the mail, on the configured public domain."""
        base = (self.public_url or conf.settings.web.domain).rstrip("/")
        return f"{base}{self.confirm_path(encode_user_id(user_identity(user)), self.generator().make_token(user))}"

    async def deliver_reset_mail(self, user: AbstractUser, *, language: str | None = None) -> None:
        """Background task body: send the mail and log a failure instead of raising it."""
        try:
            await self.send_reset_mail(user, language=language)
        except Exception:
            logger.exception("Password reset mail for user %s could not be sent", user_identity(user))

    async def send_reset_mail(self, user: AbstractUser, *, language: str | None = None) -> int:
        """Send the templated reset mail to the user's address; raises when the backend fails."""
        settings = password_reset_settings(self.auth_settings)
        context = {
            "user": user,
            "username": user.username,
            "reset_url": self.reset_url(user),
            "site_name": self.site_name or conf.settings.core.resolved_site_name(),
            "expiry_hours": max(1, round(settings.expiry / 3600)),
        }
        return await send_templated_mail(self.mail_template, context, to=[str(user.email)], language=language)

    async def verify(self, uidb64: str, token: str) -> AbstractUser | None:
        """The active user a link belongs to, or None when the id or token does not hold."""
        user_id = decode_user_id(uidb64)
        if user_id is None:
            return None
        user = await get_user_by_id(user_id, auth_settings=self.auth_settings, db_manager=self.db_manager)
        if user is None or not bool(user.is_active):
            return None
        if not self.generator().check_token(user, token):
            return None
        return user

    async def complete(self, request: Any, user: AbstractUser, raw_password: str) -> None:
        """Store the new password and end the user's sessions; the used link dies with the hash."""
        user_id = user_identity(user)
        await change_user_password(user_id, raw_password, auth_settings=self.auth_settings, db_manager=self.db_manager)
        await revoke_user_logins(request, user_id)

    def register_routes(
        self,
        app: Sanic | Router | None = None,
        *,
        render: PageRenderer | None = None,
        template_prefix: str | None = None,
        is_authenticated: Callable[[Any], bool] = session_is_authenticated,
        name_prefix: str = "",
    ) -> None:
        """Install the six views: request page and submit, sent, confirm page and submit, done.

        `app` 省略时用 `oldman.web.router` 注册——应用没有、也不需要取得服务器实例的途径。
        显式传入仍然支持:Admin 传它自己安装时拿到的那个,测试传自己的替身做隔离。

        Pages (`request`, `sent`, `confirm`, `invalid`, `done`) render through
        `render(request, page, **context)` or, without one, through
        `render_template("<template_prefix>/<page>.html")`; this flow then sets the status and the
        no-store headers on the response. Either way the context carries `csrf_token`,
        `login_url`, `request_url` and `expiry_hours` plus the page's own values: `form` and `action`
        on the request and confirm pages, `username` on the confirm page, `rate_limited=True` on a
        429. A browser that `is_authenticated` goes to `home_path` instead of the request page.
        Route names are `<name_prefix>password_reset`, `..._submit`, `..._sent`, `..._confirm`,
        `..._confirm_submit` and `..._done`.
        """
        render_view = resolve_page_renderer(render, template_prefix)

        async def page(request: Any, name: str, *, status: int = 200, **context: Any) -> HTTPResponse:
            settings = password_reset_settings(self.auth_settings)
            response = await render_view(
                request,
                name,
                csrf_token=request.ctx.csrf_token,
                login_url=self.login_path,
                request_url=self.request_path,
                expiry_hours=max(1, round(settings.expiry / 3600)),
                **context,
            )
            response.status = status
            # The set-password URL carries the token: no link may pass it to another site and no cache
            # may keep the page. Not `no-referrer`: under it a browser sends `Origin: null` even on this
            # page's own form post, and the CSRF same-origin check rightly rejects that.
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers["Cache-Control"] = "no-store"
            if status == 429:
                response.headers["Retry-After"] = str(settings.ip_window)
            return response

        @add_csrf_token()
        async def request_page(request: Any):
            if self.home_path is not None and is_authenticated(request):
                return redirect_response(self.home_path)
            return await page(request, "request", form=PasswordResetRequestForm(request=request), action=self.request_path)

        @csrf_protect()
        @add_csrf_token()
        async def request_submit(request: Any):
            form = PasswordResetRequestForm.from_request(request)
            if not await form.validate():
                return await page(request, "request", form=form, action=self.request_path)
            outcome = await self.request_reset(request, str(form.cleaned_data["email"]), language=getattr(request.ctx, "locale", None))
            if outcome is RequestOutcome.IP_LIMITED:
                return await page(request, "request", status=429, form=form, action=self.request_path, rate_limited=True)
            # Known and unknown addresses land on the same page: the answer must not reveal accounts.
            return redirect_response(self.sent_path, status=303)

        @add_csrf_token()
        async def sent_page(request: Any):
            return await page(request, "sent")

        @add_csrf_token()
        async def confirm_page(request: Any, uidb64: str, token: str):
            user = await self.verify(uidb64, token)
            if user is None:
                return await page(request, "invalid")
            return await page(request, "confirm", form=PasswordResetForm(request=request), action=request.path, username=user.username)

        @csrf_protect()
        @add_csrf_token()
        async def confirm_submit(request: Any, uidb64: str, token: str):
            user = await self.verify(uidb64, token)
            if user is None:
                return await page(request, "invalid")
            form = PasswordResetForm.from_request(request)
            if not await form.validate():
                return await page(request, "confirm", form=form, action=request.path, username=user.username)
            await self.complete(request, user, str(form.cleaned_data["password"]))
            return redirect_response(self.done_path, status=303)

        @add_csrf_token()
        async def done_page(request: Any):
            return await page(request, "done")

        confirm_route = self.confirm_path("<uidb64:str>", "<token:str>")
        target = app if app is not None else router
        target.add_route(cast(Any, request_page), self.request_path, methods=["GET"], name=f"{name_prefix}password_reset")
        target.add_route(cast(Any, request_submit), self.request_path, methods=["POST"], name=f"{name_prefix}password_reset_submit")
        target.add_route(cast(Any, sent_page), self.sent_path, methods=["GET"], name=f"{name_prefix}password_reset_sent")
        target.add_route(cast(Any, confirm_page), confirm_route, methods=["GET"], name=f"{name_prefix}password_reset_confirm")
        target.add_route(cast(Any, confirm_submit), confirm_route, methods=["POST"], name=f"{name_prefix}password_reset_confirm_submit")
        target.add_route(cast(Any, done_page), self.done_path, methods=["GET"], name=f"{name_prefix}password_reset_done")


__all__ = [
    "PasswordResetFlow",
    "PasswordResetForm",
    "PasswordResetRequestForm",
    "RateLimiter",
    "RequestOutcome",
    "client_ip",
    "redis_rate_limiter",
]
