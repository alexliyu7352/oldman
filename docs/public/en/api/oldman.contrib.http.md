# `oldman.contrib.http`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

@author:alex

Import with `from oldman.contrib.http import <name>`.

## `BaseHttpClient`

class · defined in `oldman.contrib.http.base`

```python
class BaseHttpClient
```

所有HTTP客户端实现必须遵循的基础接口

Members:

- `async def init_client() -> None` — 初始化 backend，但不要求立即建立网络连接。
- `session_attribute: ClassVar[str] = ''`
- `backend_label: ClassVar[str] = 'HTTP'`
- `async def close_session(session: Any) -> None` — 关闭一个活动会话。子类用自己的关闭调用覆盖它。
- `async def reset_client() -> bool` — 丢弃当前会话，下次请求会重新建立。失败向上抛，由调用方决定冷却。
- `async def close_client() -> bool` — 释放会话资源。
- `def export_cookie_jar(destination: CookieJar) -> None` — 把 backend 运行态 Cookie 导出到标准库 jar；直接使用该 jar 的实现无需处理。
- `async def request(method: HttpMethod, url: str, **kwargs: Any) -> HttpResponse` — 执行普通请求并返回统一的缓冲响应。
- `async def stream(method: HttpMethod, url: str, **kwargs: Any) -> AsyncIterator[HttpStreamResponse]` — 打开统一的流式响应上下文。
- `async def reconnect_stream(method: HttpMethod, url: str, live_stream: bool=False, **kwargs: Any) -> AsyncIterator[Any]` — 打开供断点续传包装器管理的 backend 流上下文。
- `async def get(url: str, **kwargs: Any) -> HttpResponse` — GET请求
- `async def post(url: str, **kwargs: Any) -> HttpResponse` — POST请求
- `async def put(url: str, **kwargs: Any) -> HttpResponse` — PUT请求
- `async def delete(url: str, **kwargs: Any) -> HttpResponse` — DELETE请求

## `ClientType`

class · defined in `oldman.contrib.http.schemas`

```python
class ClientType(enum.StrEnum)
```

HTTP 客户端类型的字符串枚举

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

HTTP 方法的字符串枚举

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

携带统一响应对象的非成功 HTTP 状态错误。

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

支持多种后端的统一HTTP客户端工厂

Constructor:

```python
MultiHttpClient(client_type: ClientType=ClientType.HTTPX, connect_timeout: float=10.0, read_timeout: float=30.0, proxy_url: str | None=None, retry_count: int=3, retry_backoff_factor: float=0.5, no_retry_statuses: list[int] | None=None, keepalive_expiry: int=300, max_connections: int=0, user_agent: str | None=None, content_decoding: bool=False, nameservers: list[str] | None=None, cookie_jar: CookieJar | None=None, verify: bool=True)
```

Members:

- `property client` — 获取当前实现的客户端实例
- `def is_initialized() -> bool` — 检查客户端是否已初始化
- `async def init_client() -> None` — 初始化HTTP客户端；已初始化时保持现有 backend 不变。
- `async def check_health() -> bool` — 检查客户端健康状态，根据需要重置
- `async def reset_client() -> bool` — 重置HTTP客户端 - 增强调试版本
- `async def close_client() -> bool` — 关闭HTTP客户端并清理资源。
- `async def request(method: HttpMethod, url: str, **kwargs: Any) -> HttpResponse` — 发送HTTP请求，支持自动重试和错误处理
- `async def stream(method: HttpMethod, url: str, **kwargs: Any) -> AsyncIterator[HttpStreamResponse]` — 改进的流式请求上下文管理器，支持重试和续传
- `async def reconnect_stream(method: HttpMethod, url: str, live_stream: bool=False, **kwargs) -> AsyncIterator['ReconnectStreamResponse']` — 建立支持读取中断后按 Range 续传的统一流响应。
- `def export_cookies() -> CookieJar | None` — 显式导出 backend 运行态 Cookie 到构造时传入的标准库 jar。
- `def save_cookies(filename: str | None=None) -> None` — 导出并保存 cookies 到文件（仅对 MozillaCookieJar 有效）。
- `def response_has_cookies(response: HttpResponse | HttpStreamResponse) -> bool` — 检查响应是否包含新的 cookies

## `ReconnectStreamResponse`

class · defined in `oldman.contrib.http.reconnect_stream`

```python
class ReconnectStreamResponse
```

一个通用的流式响应包装类，用于在需要时重新连接流式请求。由于上层业务是流式输出, 所以需要先建立连接并记录response头, 然后读取数据.

Constructor:

```python
ReconnectStreamResponse(client: _ReconnectClient, method: HttpMethod, url: str, live_stream: bool=False, **kwargs) -> None
```

Members:

- `async def connect() -> None` — 建立初始响应，并让连接失败和状态重试共享一个预算。
- `def incr_timeout(reset: bool=False) -> None` — 更新父客户端记录的连续超时次数。
- `async def aiter_bytes(chunk_size: int=512 * 1024) -> AsyncIterator[bytes]` — 迭代正文，并用一个连续预算处理读取失败和后续重连。
- `async def release_response() -> None` — 退出 backend 上下文，由统一流响应完成幂等关闭。
- `async def release() -> None` — 清理当前断点续传响应。
- `def update_response_status(response: HttpStreamResponse) -> None` — Update response metadata and reject unsafe resume responses.

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
