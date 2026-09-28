"""Authenticate tools and machines that speak HTTP Basic, by a fixed account from ``web.auth.http_basic``."""

from __future__ import annotations

from typing import Any

import oldman.conf as conf
from oldman.utils.crypto import constant_time_equals
from oldman.web.authentication.base import Authentication
from oldman.web.request import basic_credentials

HTTP_BASIC_METHOD = "http_basic"


def http_basic_challenge() -> str:
    """The ``WWW-Authenticate`` value that asks a client for Basic credentials of the configured realm."""
    return f'Basic realm="{conf.settings.web.auth.http_basic.realm}", charset="UTF-8"'


class HTTPBasicAuthentication:
    """A username and password from ``web.auth.http_basic.accounts`` in ``Authorization: Basic``.

    The caller is not a user: ``request.ctx.user`` stays anonymous and ``request.ctx.auth.caller``
    is the account name. Every account is compared, username and password both in constant
    time, so the answer takes as long whichever part was wrong. A browser remembers Basic
    credentials and sends them by itself, so the credential is ambient and CSRF protection
    applies.
    """

    name = HTTP_BASIC_METHOD

    def __init__(self) -> None:
        accounts = conf.settings.web.auth.http_basic.accounts
        if not accounts:
            raise ValueError("web.auth.authenticators lists 'http_basic' but web.auth.http_basic.accounts is empty")
        self._accounts = tuple(accounts.items())

    async def authenticate(self, request: Any) -> Authentication | None:
        credentials = basic_credentials(request)
        if credentials is None:
            return None
        username, password = credentials
        matched: str | None = None
        for account, expected in self._accounts:
            # `&` rather than `and`: both comparisons run whether or not the username matched.
            if constant_time_equals(username, account) & constant_time_equals(password, expected):
                matched = account
        if matched is None:
            return None
        return Authentication(method=self.name, caller=matched, ambient=True)


__all__ = ["HTTP_BASIC_METHOD", "HTTPBasicAuthentication", "http_basic_challenge"]
