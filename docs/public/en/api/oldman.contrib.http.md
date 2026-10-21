# `oldman.contrib.http`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

@author:alex

Import with `from oldman.contrib.http import <name>`.

## `BaseHttpClient`

class · defined in `oldman.contrib.http.base`

```python
class BaseHttpClient
```

Base interface required of all HTTP client implementations.

Members:

- `async def init_client() -> None` — Initialize the backend without requiring an immediate network connection.
- `session_attribute: ClassVar[str] = ''`
- `backend_label: ClassVar[str] = 'HTTP'`
- `async def close_session(session: Any) -> None` — Close an active session using the subclass-specific implementation.
- `async def reset_client() -> bool` — Discard the session for recreation on the next request, propagating failures so callers can choose a cooldown.
- `async def close_client() -> bool` — Release session resources.
- `def export_cookie_jar(destination: CookieJar) -> None` — Export backend Cookies to the standard-library jar unless the backend already uses it directly.
- `async def request(method: HttpMethod, url: str, **kwargs: Any) -> HttpResponse` — Execute an ordinary request and return a common buffered response.
- `async def stream(method: HttpMethod, url: str, **kwargs: Any) -> AsyncIterator[HttpStreamResponse]` — Open a common streaming-response context.
- `async def reconnect_stream(method: HttpMethod, url: str, live_stream: bool=False, **kwargs: Any) -> AsyncIterator[Any]` — Open a backend stream context managed by the resumption wrapper.
- `async def get(url: str, **kwargs: Any) -> HttpResponse` — Send a GET request.
- `async def post(url: str, **kwargs: Any) -> HttpResponse` — Send a POST request.
- `async def put(url: str, **kwargs: Any) -> HttpResponse` — Send a PUT request.
- `async def delete(url: str, **kwargs: Any) -> HttpResponse` — Send a DELETE request.

## `ClientType`

class · defined in `oldman.contrib.http.schemas`

```python
class ClientType(enum.StrEnum)
```

String enumeration of HTTP client types.

## `HTTPClientError`

class · defined in `oldman.contrib.http.exceptions`

```python
class HTTPClientError(Exception)
```

Base exception for errors defined by the unified HTTP client.

## `HttpContentDecodingError`

class · defined in `oldman.contrib.http.exceptions`

```python
class HttpContentDecodingError(HTTPClientError)
```

Response content cannot be decoded from its Content-Encoding.

## `HttpHeaders`

class · defined in `oldman.contrib.http.response`

```python
class HttpHeaders(Mapping[str, str])
```

Immutable, case-insensitive HTTP headers that retain duplicates.

Constructor:

```python
HttpHeaders(headers: HeaderItems | Mapping[str, str] | None=None) -> None
```

Members:

- `def get_list(name: str) -> list[str]` — Return every value associated with a header name.
- `def multi_items() -> list[tuple[str, str]]` — Return header pairs without joining duplicate values.
- `def copy() -> HttpHeaders` — Return an independent immutable headers object.

## `HttpMethod`

class · defined in `oldman.contrib.http.schemas`

```python
class HttpMethod(enum.StrEnum)
```

String enumeration of HTTP methods.

## `HttpRangeError`

class · defined in `oldman.contrib.http.exceptions`

```python
class HttpRangeError(HTTPClientError)
```

A resumed response does not satisfy the requested byte range.

## `HttpResponse`

class · defined in `oldman.contrib.http.response`

```python
class HttpResponse
```

Fully buffered response returned by every HTTP backend.

Constructor:

```python
HttpResponse(*, status_code: int, url: str, headers: HeaderItems | Mapping[str, str] | HttpHeaders | None=None, cookies: CookieJar | None=None, raw_content: bytes=b'', decode_content: bool=False, encoding: str | None=None, reason: str='', http_version: str='', native_response: Any=None) -> None
```

Members:

- `property text: str` — Decode the buffered response body.
- `property content: bytes` — Return the body after the configured Content-Encoding decoding.
- `property ok: bool` — Report whether the response is below the HTTP error range.
- `property is_success: bool` — Report whether the response has a successful 2xx status.
- `property is_redirect: bool` — Report whether the response has a 3xx status.
- `def read() -> bytes` — Return the already-buffered response body.
- `def raw_content() -> bytes` — Return the complete body before Content-Encoding decoding.
- `def json(**kwargs: Any) -> Any` — Deserialize the buffered response body as JSON.
- `def raise_for_status() -> HttpResponse` — Raise the framework status exception for 4xx and 5xx responses.

## `HttpStatusError`

class · defined in `oldman.contrib.http.exceptions`

```python
class HttpStatusError(HTTPClientError)
```

An unsuccessful HTTP-status error carrying the common response object.

Constructor:

```python
HttpStatusError(response: HttpResponse | HttpStreamResponse) -> None
```

## `HttpStreamConsumedError`

class · defined in `oldman.contrib.http.exceptions`

```python
class HttpStreamConsumedError(HTTPClientError)
```

A one-shot response stream has already been consumed.

## `HttpStreamResponse`

class · defined in `oldman.contrib.http.response`

```python
class HttpStreamResponse
```

Streaming response with one asynchronous API for every backend.

Constructor:

```python
HttpStreamResponse(*, status_code: int, url: str, headers: HeaderItems | Mapping[str, str] | HttpHeaders | None=None, cookies: CookieJar | None=None, decode_content: bool=False, encoding: str | None=None, reason: str='', http_version: str='', iter_raw: AsyncBytesFactory, close: AsyncClose, native_response: Any=None) -> None
```

Members:

- `property closed: bool` — Report whether the unified response has been closed.
- `property ok: bool` — Report whether the response is below the HTTP error range.
- `property is_success: bool` — Report whether the response has a successful 2xx status.
- `property is_redirect: bool` — Report whether the response has a 3xx status.
- `async def aread() -> bytes` — Read, decode, and cache the complete response body.
- `async def raw_content() -> bytes` — Read and cache the complete body before Content-Encoding decoding.
- `async def json(**kwargs: Any) -> Any` — Read and deserialize the response body as JSON.
- `def aiter_raw(chunk_size: int | None=None) -> AsyncGenerator[bytes, None]` — Iterate wire-level bytes with stable optional rechunking.
- `def aiter_bytes(chunk_size: int | None=None) -> AsyncGenerator[bytes, None]` — Iterate decoded-content bytes with stable optional rechunking.
- `async def aiter_text(chunk_size: int | None=None) -> AsyncGenerator[str, None]` — Incrementally decode text without splitting multibyte characters.
- `async def aiter_lines(chunk_size: int | None=None) -> AsyncGenerator[str, None]` — Iterate decoded lines across arbitrary backend chunk boundaries.
- `async def aclose() -> None` — Close the backend stream exactly once.
- `def raise_for_status() -> HttpStreamResponse` — Raise the framework status exception for 4xx and 5xx responses.

## `MultiHttpClient`

class · defined in `oldman.contrib.http.multi_client`

```python
class MultiHttpClient(BaseHttpClient)
```

Common HTTP client factory supporting multiple backends.

Constructor:

```python
MultiHttpClient(client_type: ClientType=ClientType.HTTPX, connect_timeout: float=10.0, read_timeout: float=30.0, proxy_url: str | None=None, retry_count: int=3, retry_backoff_factor: float=0.5, no_retry_statuses: list[int] | None=None, keepalive_expiry: int=300, max_connections: int=0, user_agent: str | None=None, content_decoding: bool=False, nameservers: list[str] | None=None, cookie_jar: CookieJar | None=None, verify: bool=True)
```

Members:

- `property client` — Return the current backend client instance.
- `def is_initialized() -> bool` — Check whether the client is initialized.
- `async def init_client() -> None` — Initialize the HTTP client, preserving its existing backend if already initialized.
- `async def check_health() -> bool` — Check client health and reset if needed.
- `async def reset_client() -> bool` — Reset the HTTP client with enhanced diagnostics.
- `async def close_client() -> bool` — Close the HTTP client and release resources.
- `async def request(method: HttpMethod, url: str, **kwargs: Any) -> HttpResponse` — Send an HTTP request with automatic retries and error handling.
- `async def stream(method: HttpMethod, url: str, **kwargs: Any) -> AsyncIterator[HttpStreamResponse]` — Open an enhanced streaming-request context with retry and resumption support.
- `async def reconnect_stream(method: HttpMethod, url: str, live_stream: bool=False, **kwargs) -> AsyncIterator['ReconnectStreamResponse']` — Establish a common stream response that resumes interrupted reads using Range.
- `def export_cookies() -> CookieJar | None` — Explicitly export runtime backend Cookies to the standard-library jar supplied at construction.
- `def save_cookies(filename: str | None=None) -> None` — Export and save Cookies to a file for MozillaCookieJar only.
- `def response_has_cookies(response: HttpResponse | HttpStreamResponse) -> bool` — Check whether the response contains new Cookies.

## `ReconnectStreamResponse`

class · defined in `oldman.contrib.http.reconnect_stream`

```python
class ReconnectStreamResponse
```

A stream response that reconnects after interrupted reads, retaining backend context between connection and body consumption.

Constructor:

```python
ReconnectStreamResponse(client: _ReconnectClient, method: HttpMethod, url: str, live_stream: bool=False, **kwargs) -> None
```

Members:

- `async def connect() -> None` — Establish initial or resumed responses using a shared consecutive retry budget for connection, status, and read failures.
- `def incr_timeout(reset: bool=False) -> None` — Update the parent client's consecutive-timeout count.
- `async def aiter_bytes(chunk_size: int=512 * 1024) -> AsyncIterator[bytes]` — Yield contiguous response bytes, recovering interrupted reads under resumption rules.
- `async def release_response() -> None` — Exit the backend context through idempotent common-response closure.
- `def detach_response() -> AbstractAsyncContextManager[HttpStreamResponse] | None` — Transfer the current response context to the caller for closure, leaving release nothing to await.
- `async def release() -> None` — Clean up the current resumable response.
- `def update_response_status(response: HttpStreamResponse) -> None` — Set public status, headers, and resumption mode from the first response; later responses only verify continuity.

## `RequestFailedError`

class · defined in `oldman.contrib.http.exceptions`

```python
class RequestFailedError(Exception)
```

A retried request failed with its final HTTP response.

Constructor:

```python
RequestFailedError(message: str, status_code: int, response_text: str) -> None
```

## Module `oldman.contrib.http.response`

Backend-neutral HTTP response objects.

Import with `from oldman.contrib.http.response import <name>`.

### `cookie_jar_from_headers`

function · defined in `oldman.contrib.http.response`

```python
def cookie_jar_from_headers(headers: HttpHeaders, url: str) -> CookieJar
```

Let the standard CookieJar parse and validate every Set-Cookie field.

### `copy_cookie_jar`

function · defined in `oldman.contrib.http.response`

```python
def copy_cookie_jar(cookies: CookieJar | None) -> CookieJar
```

Detach response cookies from mutable backend session jars.
