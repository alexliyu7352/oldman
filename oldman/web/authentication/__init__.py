"""Request authentication: who is calling, and how they proved it.

Every request leaves the pipeline with ``request.ctx.user`` — a signed-in
:class:`RequestUser` or :data:`ANONYMOUS_USER` — and ``request.ctx.auth``, the
:class:`Authentication` that recognized it or None. Permission checks read only these,
whichever method produced them. The methods a service tries are configured in
``web.auth.authenticators``.

This package imports nothing from ``oldman.web.auth`` or ``oldman.web.http``: both depend
on it.
"""

from oldman.web.authentication.api_key import API_KEY_HEADER, API_KEY_METHOD, APIKeyAuthentication
from oldman.web.authentication.base import (
    ANONYMOUS_USER,
    AnonymousUser,
    Authentication,
    Authenticator,
    RequestUser,
    exempt_from_csrf,
    record_authentication,
    request_user,
    user_from_session,
)
from oldman.web.authentication.http_basic import HTTP_BASIC_METHOD, HTTPBasicAuthentication, http_basic_challenge
from oldman.web.authentication.ip_allowlist import IP_ALLOWLIST_METHOD, IPAllowlistAuthentication
from oldman.web.authentication.jwt import (
    JWT_METHOD,
    AccessToken,
    JWTAuthentication,
    access_token_revoked,
    issue_access_token,
    read_access_token,
    revoke_access_token,
    revoke_user_tokens,
    user_from_access_token,
)
from oldman.web.authentication.pipeline import (
    BUILTIN_AUTHENTICATORS,
    install_authentication,
    resolve_authenticators,
)
from oldman.web.authentication.refresh import (
    RefreshToken,
    RotatedRefreshToken,
    issue_refresh_token,
    refresh_token_user,
    revoke_refresh_token,
    rotate_refresh_token,
)
from oldman.web.authentication.session import (
    SESSION_METHOD,
    SessionAuthentication,
    forget_session_authentication,
    session_authentication,
)

__all__ = [
    "ANONYMOUS_USER",
    "API_KEY_HEADER",
    "API_KEY_METHOD",
    "APIKeyAuthentication",
    "BUILTIN_AUTHENTICATORS",
    "HTTP_BASIC_METHOD",
    "HTTPBasicAuthentication",
    "IPAllowlistAuthentication",
    "IP_ALLOWLIST_METHOD",
    "JWT_METHOD",
    "AccessToken",
    "AnonymousUser",
    "Authentication",
    "Authenticator",
    "JWTAuthentication",
    "RefreshToken",
    "RequestUser",
    "RotatedRefreshToken",
    "SESSION_METHOD",
    "SessionAuthentication",
    "access_token_revoked",
    "exempt_from_csrf",
    "forget_session_authentication",
    "http_basic_challenge",
    "install_authentication",
    "issue_access_token",
    "issue_refresh_token",
    "refresh_token_user",
    "read_access_token",
    "record_authentication",
    "request_user",
    "resolve_authenticators",
    "revoke_access_token",
    "revoke_refresh_token",
    "revoke_user_tokens",
    "rotate_refresh_token",
    "session_authentication",
    "user_from_access_token",
    "user_from_session",
]
