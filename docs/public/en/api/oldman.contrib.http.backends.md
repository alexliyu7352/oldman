# `oldman.contrib.http.backends`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

HTTP client backend implementations.

Import with `from oldman.contrib.http.backends import <name>`.

## `AioHttpClient`

class · defined in `oldman.contrib.http.backends.aiohttp`

```python
class AioHttpClient(BaseHttpClient)
```

HTTP client implemented with aiohttp.

Constructor:

```python
AioHttpClient(parent: 'MultiHttpClient')
```

Members:

- `session_attribute: ClassVar[str] = 'session'`
- `backend_label: ClassVar[str] = 'aiohttp'`
- `async def init_client() -> None` — Initialize the aiohttp client.
- `async def close_session(session: Any) -> None` — Close the aiohttp session.
- `async def get_client() -> aiohttp.ClientSession` — Return or create the aiohttp session.
- `def export_cookie_jar(destination: CookieJar) -> None` — Export runtime aiohttp Cookies to the standard-library jar.
- `def prepare_request_params(**kwargs: Any) -> dict[str, Any]` — Convert aiohttp parameters and supply the common User-Agent.
- `async def request(method: HttpMethod, url: str, **kwargs: Any) -> HttpResponse` — Execute an aiohttp request.
- `async def stream(method: HttpMethod, url: str, **kwargs: Any)` — Context manager for streaming requests.
- `async def reconnect_stream(method: HttpMethod, url: str, live_stream: bool=False, **kwargs: Any)` — Reuse the common stream adapter with lifecycle ownership held explicitly by the resumable response.

## `CurlCffiClient`

class · defined in `oldman.contrib.http.backends.curl`

```python
class CurlCffiClient(BaseHttpClient)
```

HTTP client implemented with curl_cffi.

Constructor:

```python
CurlCffiClient(parent: 'MultiHttpClient')
```

Members:

- `session_attribute: ClassVar[str] = 'client'`
- `backend_label: ClassVar[str] = 'curl_cffi'`
- `async def init_client() -> None` — Initialize the curl_cffi client.
- `async def close_session(session: Any) -> None` — Close the curl_cffi session.
- `async def get_client() -> AsyncSession` — Return or create the curl_cffi client.
- `def update_impersonate(**kwargs: Any) -> dict[str, Any]` — Resolve curl impersonation User-Agents while preserving ordinary User-Agents.
- `def prepare_request_params(**kwargs: Any) -> dict[str, Any]` — Convert curl_cffi request parameters.
- `async def request(method: HttpMethod, url: str, **kwargs: Any) -> HttpResponse` — Execute a curl_cffi request.
- `async def stream(method: HttpMethod, url: str, **kwargs: Any)` — Context manager for streaming requests.
- `async def reconnect_stream(method: HttpMethod, url: str, live_stream: bool=False, **kwargs: Any)` — Match stream behavior for interface compatibility.

## `HttpxClient`

class · defined in `oldman.contrib.http.backends.httpx`

```python
class HttpxClient(BaseHttpClient)
```

HTTP client implemented with HTTPX.

Constructor:

```python
HttpxClient(parent: 'MultiHttpClient')
```

Members:

- `session_attribute: ClassVar[str] = 'http_client'`
- `backend_label: ClassVar[str] = 'HTTPX'`
- `async def init_client() -> None` — Initialize the HTTPX client.
- `async def close_session(session: Any) -> None` — Close the HTTPX client.
- `async def get_client() -> httpx.AsyncClient` — Return or create the HTTPX client instance.
- `def prepare_request_params(**kwargs: Any) -> dict[str, Any]` — Convert HTTPX parameters and supply the common User-Agent.
- `async def request(method: HttpMethod, url: str, **kwargs: Any) -> HttpResponse` — Execute an HTTPX request.
- `async def stream(method: HttpMethod, url: str, **kwargs: Any)` — Context manager for streaming requests.
- `async def reconnect_stream(method: HttpMethod, url: str, live_stream: bool=False, **kwargs: Any)` — Reuse the common stream adapter with lifecycle ownership held explicitly by the resumable response.
