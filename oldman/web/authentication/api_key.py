"""Authenticate callers that are not users — other services, scripts — by a key from ``web.auth.api_keys``."""

from __future__ import annotations

from typing import Any

import oldman.conf as conf
from oldman.utils.crypto import constant_time_equals
from oldman.web.authentication.base import Authentication
from oldman.web.request import bearer_credential, get_arg

API_KEY_METHOD = "api_key"
API_KEY_HEADER = "X-API-Key"


class APIKeyAuthentication:
    """A key from ``web.auth.api_keys`` in the ``X-API-Key`` header.

    A key that opts in is also read from its ``query_param`` or from ``Authorization: Bearer``.
    The caller is not a user: ``request.ctx.user`` stays anonymous and ``request.ctx.auth.caller``
    names the key, which is what ``authenticated_by("api_key", callers=...)`` checks. Keys are
    compared in constant time, and a wrong or missing key leaves the request to the next method.
    The client attaches the key on purpose and a browser never does, so the credential is not
    ambient and CSRF protection does not apply.
    """

    name = API_KEY_METHOD

    def __init__(self) -> None:
        keys = conf.settings.web.auth.api_keys
        if not keys:
            raise ValueError("web.auth.authenticators lists 'api_key' but web.auth.api_keys is empty")
        self._keys = tuple(keys.items())

    async def authenticate(self, request: Any) -> Authentication | None:
        headers = getattr(request, "headers", None) or {}
        header_key = headers.get(API_KEY_HEADER)
        bearer = bearer_credential(request)
        for caller, key in self._keys:
            presented = [header_key]
            if key.authorization:
                presented.append(bearer)
            if key.query_param is not None:
                presented.append(get_arg(getattr(request, "args", None) or {}, key.query_param))
            if any(isinstance(value, str) and value and constant_time_equals(value, key.secret) for value in presented):
                return Authentication(method=self.name, caller=caller, ambient=False)
        return None


__all__ = ["API_KEY_HEADER", "API_KEY_METHOD", "APIKeyAuthentication"]
