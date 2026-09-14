"""Backend-neutral HTTP client exceptions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .response import HttpResponse, HttpStreamResponse


class HTTPClientError(Exception):
    """Base exception for errors defined by the unified HTTP client."""


class HttpStatusError(HTTPClientError):
    """携带统一响应对象的非成功 HTTP 状态错误。"""

    def __init__(self, response: HttpResponse | HttpStreamResponse) -> None:
        """Retain backend-neutral response metadata for error handling."""

        self.response = response
        self.status_code = response.status_code
        self.url = response.url
        message = response.reason or "HTTP status error"
        super().__init__(f"{self.status_code} {message}: {self.url}")


class HttpContentDecodingError(HTTPClientError):
    """Response content cannot be decoded from its Content-Encoding."""


class HttpStreamConsumedError(HTTPClientError):
    """A one-shot response stream has already been consumed."""


class HttpRangeError(HTTPClientError):
    """A resumed response does not satisfy the requested byte range."""


class RequestFailedError(Exception):
    """A retried request failed with its final HTTP response."""

    def __init__(self, message: str, status_code: int, response_text: str) -> None:
        """Record the final status and body after retry exhaustion."""

        if not message:
            show_message = f"请求失败，状态码: {status_code}, 响应内容: {response_text}"
        else:
            show_message = f"{message} - 状态码: {status_code}, 响应内容: {response_text}"
        super().__init__(show_message)
        self.status_code = status_code
        self.response_text = response_text
        self.message = show_message


__all__ = [
    "HTTPClientError",
    "HttpContentDecodingError",
    "HttpRangeError",
    "HttpStatusError",
    "HttpStreamConsumedError",
    "RequestFailedError",
]
