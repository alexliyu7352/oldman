"""Bearer tokens for clients that are not browsers: obtain, refresh and revoke them over HTTP.

A front end served on its own, a mobile app or another service signs in here with the
credentials the login page takes, and gets an access token for the ``Authorization:
Bearer`` header plus a refresh token to renew it. Nothing travels in a cookie, so the
three routes take no CSRF token: a page on another site can make a browser post to them,
but cannot read the tokens that come back.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from sanic import Sanic

from oldman.auth import AbstractUser, get_user_by_id, touch_last_login, user_identity
from oldman.auth.settings import AuthSettings
from oldman.db import DatabaseManager
from oldman.i18n import gettext
from oldman.web.api import ApiErrorCode, DefaultApiResponse
from oldman.web.auth.login import LoginRateLimit, authenticate_credentials, form_value
from oldman.web.auth.permissions import role_ids_for_login
from oldman.web.authentication import (
    AccessToken,
    RefreshToken,
    issue_access_token,
    issue_refresh_token,
    read_access_token,
    refresh_token_user,
    revoke_access_token,
    revoke_refresh_token,
    rotate_refresh_token,
)
from oldman.web.request import bearer_credential, request_sends_json
from oldman.web.response import Response, json_response
from oldman.web.routing import Router, router
from oldman.web.security.csrf import csrf_exempt

# The flow passes these to the login backends itself; a client must not be able to.
_RESERVED_CREDENTIALS = frozenset({"auth_settings", "db_manager"})


def _is_text(value: object) -> bool:
    """A non-empty string that UTF-8 can write: JSON may carry a lone surrogate ("\\ud800"), which it cannot."""
    if not isinstance(value, str) or not value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _body_fields(request: Any, names: tuple[str, ...]) -> dict[str, str] | None:
    """The named fields of a JSON object or form body, or None when any is missing or not text.

    Text that cannot be UTF-8 counts as not text: the fields end up in digests and Redis keys,
    and encoding them would raise - a 500 anyone could cause without signing in.
    """
    if request_sends_json(request):
        payload = request.json
        source: Mapping[str, Any] = payload if isinstance(payload, Mapping) else {}
        values = {name: source.get(name) for name in names}
    else:
        values = {name: form_value(request, name) for name in names}
    if not all(_is_text(value) for value in values.values()):
        return None
    return cast(dict[str, str], values)


def _respond(payload: DefaultApiResponse, *, status: int = 200, headers: Mapping[str, str] | None = None) -> Response:
    # Neither the tokens nor the answers about them may be kept by a browser or a proxy cache.
    return json_response(payload.to_dict(), status=status, headers={"Cache-Control": "no-store", **(headers or {})})


def _refused(status: int, error_code: ApiErrorCode, message: str, *, headers: Mapping[str, str] | None = None) -> Response:
    return _respond(DefaultApiResponse(error_code=error_code, message=message), status=status, headers=headers)


def _issued(access: AccessToken, refresh: RefreshToken) -> Response:
    return _respond(
        DefaultApiResponse(
            data={
                "access_token": access.token,
                "token_type": "Bearer",
                "expires_in": access.expires_in,
                "refresh_token": refresh.token,
                "refresh_expires_in": refresh.expires_in,
            }
        )
    )


@dataclass
class TokenFlow:
    """Who may hold bearer tokens, and the three routes that hand them out, renew and end them.

    ``accept_user`` has no default on purpose: a site whose login page admits only staff
    must not give tokens to every account because the token route forgot to ask. It is
    asked at sign-in and again at every refresh with the User read fresh from the
    database, so an account that is disabled, deleted or no longer accepted gets no new
    access token at its next refresh.

    ``credential_fields`` are the body fields handed to the login backends — ``username``
    and ``password`` for the built-in ``users`` backend; nothing else the client sends
    reaches them. Failed sign-ins count against the same limits as the login page
    (``rate_limit``, by default the one for ``auth_settings``).
    """

    accept_user: Callable[[AbstractUser], bool]
    credential_fields: tuple[str, ...] = ("username", "password")
    auth_settings: AuthSettings | None = None
    db_manager: DatabaseManager | None = None
    rate_limit: LoginRateLimit | None = None

    def __post_init__(self) -> None:
        if not self.credential_fields:
            raise ValueError("TokenFlow needs at least one credential field")
        reserved = _RESERVED_CREDENTIALS.intersection(self.credential_fields)
        if reserved:
            raise ValueError(f"TokenFlow credential fields may not include {sorted(reserved)}")

    def limiter(self) -> LoginRateLimit:
        """The failed sign-in limits the obtain route applies."""
        if self.rate_limit is None:
            self.rate_limit = LoginRateLimit(auth_settings=self.auth_settings)
        return self.rate_limit

    def register_routes(
        self,
        app: Sanic | Router | None = None,
        *,
        obtain_path: str,
        refresh_path: str,
        revoke_path: str,
        name_prefix: str = "",
    ) -> None:
        """Install the three POST routes.

        Obtain takes the credential fields and answers with an access token and a refresh
        token. Refresh takes ``refresh_token`` and answers with a new pair: the refresh token
        it was given stops working. Revoke takes ``refresh_token`` and ends its sign-in; the
        access token in the request's ``Authorization`` header, if any, stops working too.
        Bodies are JSON objects or forms. Answers use the framework's JSON envelope and are
        never cached; a malformed body gets 400, a refused credential 401, too many failed
        sign-ins 429 with ``Retry-After``.

        ``app`` omitted, the routes register through ``oldman.web.router``. Route names are
        ``<name_prefix>token_obtain``, ``..._refresh`` and ``..._revoke``. The service must set
        ``web.auth.jwt.secret``; the services that accept the tokens list ``jwt`` in
        ``web.auth.authenticators`` — this one need not, if it only hands tokens out. The
        secret is not checked here, because views modules call this on import, and importing
        one must work where no service runs; a service without it fails its first request.
        """
        credential_fields = self.credential_fields

        @csrf_exempt
        async def obtain(request: Any):
            credentials = _body_fields(request, credential_fields)
            if credentials is None:
                return _refused(
                    400, ApiErrorCode.INVALID_REQUEST, gettext("Required: %(fields)s", request=request, fields=", ".join(credential_fields))
                )
            username = credentials.get("username", "")
            limiter = self.limiter()
            retry_after = await limiter.retry_after(request, username)
            if retry_after is not None:
                return _refused(
                    429,
                    ApiErrorCode.TOO_MANY_REQUESTS,
                    gettext("Too many sign-in attempts", request=request),
                    headers={"Retry-After": str(retry_after)},
                )
            user = await authenticate_credentials(request, **credentials, auth_settings=self.auth_settings, db_manager=self.db_manager)
            # An account the site gives no tokens gets the same answer as a wrong password:
            # telling them apart would confirm the password was right. A login backend may
            # return a disabled account; no token is issued to one, whatever accept_user says.
            if user is None or not user.is_active or not self.accept_user(user):
                await limiter.record_failure(request, username)
                return _refused(401, ApiErrorCode.AUTHENTICATION_REQUIRED, gettext("Invalid credentials", request=request))
            user_id = user_identity(user)
            await touch_last_login(user_id, auth_settings=self.auth_settings, db_manager=self.db_manager)
            role_ids = await role_ids_for_login(request, user_id, db_manager=self.db_manager)
            return _issued(issue_access_token(user, role_ids=role_ids), await issue_refresh_token(user_id))

        @csrf_exempt
        async def refresh(request: Any):
            fields = _body_fields(request, ("refresh_token",))
            if fields is None:
                return _refused(400, ApiErrorCode.INVALID_REQUEST, gettext("Required: %(fields)s", request=request, fields="refresh_token"))
            # Everything that can fail on the way happens before the token is used up: a client
            # whose refresh failed on a database hiccup retries with the token it still holds.
            user_id = await refresh_token_user(fields["refresh_token"])
            if user_id is None:
                return _refused(401, ApiErrorCode.AUTHENTICATION_REQUIRED, gettext("Invalid refresh token", request=request))
            user = await get_user_by_id(user_id, auth_settings=self.auth_settings, db_manager=self.db_manager)
            if user is None or not user.is_active or not self.accept_user(user):
                await revoke_refresh_token(fields["refresh_token"])
                return _refused(401, ApiErrorCode.AUTHENTICATION_REQUIRED, gettext("Invalid refresh token", request=request))
            role_ids = await role_ids_for_login(request, user_id, db_manager=self.db_manager)
            rotated = await rotate_refresh_token(fields["refresh_token"])
            if rotated is None:
                return _refused(401, ApiErrorCode.AUTHENTICATION_REQUIRED, gettext("Invalid refresh token", request=request))
            return _issued(issue_access_token(user, role_ids=role_ids), rotated.refresh_token)

        @csrf_exempt
        async def revoke(request: Any):
            fields = _body_fields(request, ("refresh_token",))
            if fields is None:
                return _refused(400, ApiErrorCode.INVALID_REQUEST, gettext("Required: %(fields)s", request=request, fields="refresh_token"))
            await revoke_refresh_token(fields["refresh_token"])
            # The access token the client signs out with stops working now, not when it expires.
            presented = bearer_credential(request)
            claims = read_access_token(presented) if presented is not None else None
            if claims is not None:
                await revoke_access_token(claims)
            return _respond(DefaultApiResponse())

        target = app if app is not None else router
        target.add_route(cast(Any, obtain), obtain_path, methods=["POST"], name=f"{name_prefix}token_obtain")
        target.add_route(cast(Any, refresh), refresh_path, methods=["POST"], name=f"{name_prefix}token_refresh")
        target.add_route(cast(Any, revoke), revoke_path, methods=["POST"], name=f"{name_prefix}token_revoke")


__all__ = ["TokenFlow"]
