"""Password reset flow shared by the Admin site and project login pages.

Request page → "check your email" page → link from the mail → set-password page → done page. The
request page answers the same way whether or not the address has an account; the token comes from
`oldman.auth.password_reset` and needs no storage.
"""

from __future__ import annotations

import enum
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

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
from oldman.web.auth.forms import UserPasswordForm
from oldman.web.auth.session import revoke_user_sessions
from oldman.web.components.forms import EmailField, TailwindForm
from oldman.web.request import client_ip
from oldman.web.response import redirect_response
from oldman.web.security.csrf import add_csrf_token, csrf_protect
from oldman.web.security.rate_limiter import RateLimiter, redis_rate_limiter
from oldman.web.session import SessionData
from oldman.web.template import render_template

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


class PageRenderer(Protocol):
    """Renders one page of the flow (`request`, `sent`, `confirm`, `invalid`, `done`) with the given context.

    `register_routes` sets the status and the no-store headers on the response it gets back.
    """

    def __call__(self, request: Any, page: str, /, **context: Any) -> Awaitable[HTTPResponse]: ...


def session_is_authenticated(request: Any) -> bool:
    """Whether the request carries a signed-in Session; the default check for skipping the request page."""
    session = getattr(getattr(request, "ctx", None), "session", None)
    return isinstance(session, SessionData) and session.is_authenticated()


@dataclass
class PasswordResetFlow:
    """Paths, settings and collaborators for one site's reset flow.

    `confirm_path` must build the set-password URL by plain interpolation of the two segments:
    `register_routes` calls it with the route placeholders to obtain the route pattern.
    `home_path` is where a browser that is already signed in goes instead of the request page.
    """

    request_path: str
    sent_path: str
    done_path: str
    login_path: str
    confirm_path: Callable[[str, str], str]
    home_path: str | None = None
    site_name: str = "Oldman"
    mail_template: str = "oldman/auth/mail/password_reset"
    auth_settings: AuthSettings | None = None
    db_manager: DatabaseManager | None = None
    token_generator: PasswordResetTokenGenerator | None = None
    rate_limiter: RateLimiter | None = None
    public_url: str | None = None

    def generator(self) -> PasswordResetTokenGenerator:
        """Token generator bound to this flow's reset settings (lifetime from `auth_settings`)."""
        if self.token_generator is None:
            self.token_generator = PasswordResetTokenGenerator(expiry=password_reset_settings(self.auth_settings).expiry)
        return self.token_generator

    def limiter(self) -> RateLimiter:
        if self.rate_limiter is None:
            self.rate_limiter = redis_rate_limiter(namespace=f"{conf.settings.core.app_name}:{RATE_LIMIT_PATH}")
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
            "site_name": self.site_name,
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
        await revoke_user_sessions(request, user_id)

    def register_routes(
        self,
        app: Sanic,
        *,
        render: PageRenderer | None = None,
        template_prefix: str | None = None,
        is_authenticated: Callable[[Any], bool] = session_is_authenticated,
        name_prefix: str = "",
    ) -> None:
        """Install the six views: request page and submit, sent, confirm page and submit, done.

        Pages render through `render(request, page, **context)` or, without one, through
        `render_template("<template_prefix>/<page>.html")`. Either way the context carries `csrf_token`,
        `login_url`, `request_url` and `expiry_hours` plus the page's own values: `form` and `action`
        on the request and confirm pages, `username` on the confirm page, `rate_limited=True` on a
        429. A browser that `is_authenticated` goes to `home_path` instead of the request page.
        Route names are `<name_prefix>password_reset`, `..._submit`, `..._sent`, `..._confirm`,
        `..._confirm_submit` and `..._done`.
        """
        if (render is None) == (template_prefix is None):
            raise ValueError("register_routes takes exactly one of render= or template_prefix=")
        if render is None:
            page_prefix = cast(str, template_prefix).rstrip("/")

            async def render_page(request: Any, page: str, /, **context: Any) -> HTTPResponse:
                return await render_template(f"{page_prefix}/{page}.html", context={"request": request, **context})

            render = render_page
        render_view = render

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
            # The set-password URL carries the token: no link may pass it on and no cache may keep the page.
            response.headers["Referrer-Policy"] = "no-referrer"
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
        app.add_route(cast(Any, request_page), self.request_path, methods=["GET"], name=f"{name_prefix}password_reset")
        app.add_route(cast(Any, request_submit), self.request_path, methods=["POST"], name=f"{name_prefix}password_reset_submit")
        app.add_route(cast(Any, sent_page), self.sent_path, methods=["GET"], name=f"{name_prefix}password_reset_sent")
        app.add_route(cast(Any, confirm_page), confirm_route, methods=["GET"], name=f"{name_prefix}password_reset_confirm")
        app.add_route(cast(Any, confirm_submit), confirm_route, methods=["POST"], name=f"{name_prefix}password_reset_confirm_submit")
        app.add_route(cast(Any, done_page), self.done_path, methods=["GET"], name=f"{name_prefix}password_reset_done")


__all__ = [
    "PageRenderer",
    "PasswordResetFlow",
    "PasswordResetForm",
    "PasswordResetRequestForm",
    "RateLimiter",
    "RequestOutcome",
    "client_ip",
    "redis_rate_limiter",
    "session_is_authenticated",
]
