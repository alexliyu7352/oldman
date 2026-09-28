"""Web exceptions the framework raises, named so handlers can match on them."""

from sanic.exceptions import BadRequest, Forbidden, NotFound, SanicException, Unauthorized


class TooManyRequests(SanicException):
    """A request refused by a rate limit; carries Retry-After when the window is known."""

    status_code = 429


__all__ = ["BadRequest", "Forbidden", "NotFound", "TooManyRequests", "Unauthorized"]
