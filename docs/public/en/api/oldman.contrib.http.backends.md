# `oldman.contrib.http.backends`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

HTTP客户端后端实现

Import with `from oldman.contrib.http.backends import <name>`.

## `AioHttpClient`

class · defined in `oldman.contrib.http.backends.aiohttp`

```python
class AioHttpClient(BaseHttpClient)
```

aiohttp实现的HTTP客户端

Constructor:

```python
AioHttpClient(parent: 'MultiHttpClient')
```

Members:

- `session_attribute: ClassVar[str] = 'session'`
- `backend_label: ClassVar[str] = 'aiohttp'`
- `async def init_client() -> None` — 初始化aiohttp客户端
- `async def close_session(session: Any) -> None` — 关闭 aiohttp 会话。
- `async def get_client() -> aiohttp.ClientSession` — 获取或创建aiohttp会话
- `def export_cookie_jar(destination: CookieJar) -> None` — 把 aiohttp 运行态 Cookie 导出到标准库 jar。
- `def prepare_request_params(**kwargs: Any) -> dict[str, Any]` — 转换 aiohttp 参数并补充统一 User-Agent。
- `async def request(method: HttpMethod, url: str, **kwargs: Any) -> HttpResponse` — 执行aiohttp请求
- `async def stream(method: HttpMethod, url: str, **kwargs: Any)` — 流式请求上下文管理器
- `async def reconnect_stream(method: HttpMethod, url: str, live_stream: bool=False, **kwargs: Any)` — 复用统一流适配器，生命周期由断点续传对象显式持有。

## `CurlCffiClient`

class · defined in `oldman.contrib.http.backends.curl`

```python
class CurlCffiClient(BaseHttpClient)
```

curl_cffi实现的HTTP客户端

Constructor:

```python
CurlCffiClient(parent: 'MultiHttpClient')
```

Members:

- `session_attribute: ClassVar[str] = 'client'`
- `backend_label: ClassVar[str] = 'curl_cffi'`
- `async def init_client() -> None` — 初始化curl_cffi客户端
- `async def close_session(session: Any) -> None` — 关闭 curl_cffi 会话。
- `async def get_client() -> AsyncSession` — 获取或创建curl_cffi客户端
- `def update_impersonate(**kwargs: Any) -> dict[str, Any]` — 解析 curl impersonate User-Agent，并保留普通 User-Agent。
- `def prepare_request_params(**kwargs: Any) -> dict[str, Any]` — 转换 curl_cffi 请求参数。
- `async def request(method: HttpMethod, url: str, **kwargs: Any) -> HttpResponse` — 执行curl_cffi请求
- `async def stream(method: HttpMethod, url: str, **kwargs: Any)` — 流式请求上下文管理器
- `async def reconnect_stream(method: HttpMethod, url: str, live_stream: bool=False, **kwargs: Any)` — 应该与stream方法一致，只是为了兼容接口

## `HttpxClient`

class · defined in `oldman.contrib.http.backends.httpx`

```python
class HttpxClient(BaseHttpClient)
```

HTTPX实现的HTTP客户端

Constructor:

```python
HttpxClient(parent: 'MultiHttpClient')
```

Members:

- `session_attribute: ClassVar[str] = 'http_client'`
- `backend_label: ClassVar[str] = 'HTTPX'`
- `async def init_client() -> None` — 初始化HTTPX客户端
- `async def close_session(session: Any) -> None` — 关闭 HTTPX 客户端。
- `async def get_client() -> httpx.AsyncClient` — 获取或创建HTTPX客户端实例
- `def prepare_request_params(**kwargs: Any) -> dict[str, Any]` — 转换 HTTPX 参数并补充统一 User-Agent。
- `async def request(method: HttpMethod, url: str, **kwargs: Any) -> HttpResponse` — 执行HTTPX请求
- `async def stream(method: HttpMethod, url: str, **kwargs: Any)` — 流式请求上下文管理器
- `async def reconnect_stream(method: HttpMethod, url: str, live_stream: bool=False, **kwargs: Any)` — 复用统一流适配器，生命周期由断点续传对象显式持有。
