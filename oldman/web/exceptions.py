"""Web exceptions the framework raises, named so handlers can match on them."""

from sanic.exceptions import BadRequest, Forbidden, NotFound, SanicException, Unauthorized


class TooManyRequests(SanicException):
    """A request refused by a rate limit; carries Retry-After when the window is known."""

    status_code = 429


class CSRFFailure(Forbidden):
    """A state-changing request whose CSRF token or origin did not check out.

    Still a 403, so code that handles Forbidden keeps working. The HTML error page shows
    `page_description` — what the visitor can do about it, already translated — instead of
    claiming they lack permission; the message itself stays for logs and JSON responses.
    """

    def __init__(self, message: str, *, page_description: str) -> None:
        super().__init__(message)
        self.page_description = page_description


__all__ = ["BadRequest", "CSRFFailure", "Forbidden", "NotFound", "TooManyRequests", "Unauthorized"]
