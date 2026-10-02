# `oldman.contrib.proxy`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

@author:alex

Import with `from oldman.contrib.proxy import <name>`.

## `BaseStreamProxy`

class · defined in `oldman.contrib.proxy.base`

```python
class BaseStreamProxy
```

流媒体代理基类。

Constructor:

```python
BaseStreamProxy(proxy_name: str='base')
```

Members:

- `classmethod def generate_channel_id(url: str) -> str` — 生成频道ID (使用LRU缓存减少重复计算)
- `classmethod def is_use_curl(user_agent: str | None=None) -> bool` — 判断是否使用curl_cffi, 根据user_agent起始字符串判断
- `def get_client_type(user_agent: str | None=None) -> ClientType` — 获取客户端类型
- `def get_client_key(client_type: ClientType, client_remark: str='', proxy_url: str | None=None, content_decoding: bool=False) -> str`
- `async def get_client(user_agent: str | None=None, proxy_url: str | None=None, content_decoding: bool=False, client_remark: str | None=None) -> MultiHttpClient` — 获取或创建HTTP客户端
- `async def get_request_headers(request: Request | None=None, base_headers: dict | None=None) -> dict` — 获取请求头,合并基础头和客户端重要头信息
- `async def delete_cached_channel_url(channel_id: str)` — 删除缓存的频道URL
- `async def save_cached_channel_url(channel_id: str, url: str, ttl: int=60 * 60 * 24 * 7)` — 保存频道URL到缓存
- `async def get_cached_channel_url(channel_id: str) -> str | None` — 从缓存获取频道URL
- `staticmethod def generate_hash_url(current_id: str, ts_url: str) -> str` — 生成TS URL的哈希值
- `async def save_sub_url(channel_id: str, cached_id: str, ts_url: str, sub_ttl: int=60, direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, ext_name: str | None=None, **extra_context) -> str` — 保存TS URL到Redis并生成新URL
- `async def get_sub_url(channel_id: str, hash_url: str) -> dict[str, Any] | Any` — 获取TS URL信息
- `async def proxy_m3u8_ts_path(channel_id: str, m3u8_content: str, base_url: str, cached_id: str='', sub_ttl: tuple[int, int]=(3600, 300), direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, **extra_context) -> str` — 处理m3u8内容,替换TS路径为代理路径
- `def proxy_mpd_path(mpd_content: str, play_url: str) -> str` — 处理mpd内容,替换TS路径为代理路径
- `async def get_final_m3u8(request: Request, m3u8_url: str, user_agent: str | None=None, proxy_url: str | None=None, headers: dict[str, str] | None=None, **extra_context) -> tuple[str | None, str]` — 获取m3u8内容,支持嵌套m3u8处理
- `def update_ttl_from_content(m3u8_content: str, current_ttl: int) -> int` — 从m3u8内容中提取缓存时间并更新TTL
- `async def fetch_remote_manifest(request: Request, channel_id: str, play_url: str, ttl: int=2, sub_ttl: tuple[int, int]=(3600, 300), direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, is_sub_manifest: bool=False, **extra_context) -> str | None` — 获取远程m3u8内容,支持缓存
- `async def stream_response(request: Request, response: ReconnectStreamResponse, content_type: str='video/mp2t') -> None` — 流式返回响应内容
- `async def get_ts_stream(request: Request, ts_url: str, proxy_url: str | None=None, user_agent: str | None=None, headers: dict[str, str] | None=None, live_stream: bool=False) -> HTTPResponse | None` — 获取TS流内容
- `async def get_ts_stream_direct(request: Request, ts_url: str, proxy_url: str | None=None, user_agent: str | None=None) -> HTTPResponse | None` — 使用直接TCP连接获取TS流内容，优化CPU使用率并处理chunked编码
- `async def process_sub_manifest(request: Request, channel_id: str, ts_context: dict[str, Any], ttl: int=2, sub_ttl: int=0, **kwargs) -> HTTPResponse | None` — 处理子m3u8的逻辑，子类可重载此方法以实现特定逻辑
- `async def process_sub_stream(request: Request, channel_id: str, ts_context: dict[str, Any], **kwargs) -> HTTPResponse | None` — 处理子流的逻辑，子类可重载此方法以实现特定逻辑
- `async def fetch_sub_manifest_or_stream(request: Request, channel_id: str, hash_url: str, ttl: int=2, sub_url_ttl: int=0) -> HTTPResponse | None` — 获取子m3u8或ts文件 中转
- `async def proxy_stream(request: Request, play_url: str, direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, headers: dict[str, str] | None=None) -> HTTPResponse | None` — 代理直播流媒体
- `async def get_real_url(request: Request, play_url: str, ttl: int, included: list[str] | None=None, blacklisted: list[str] | None=None, proxy_url: str | None=None, user_agent: str | None=None, headers: dict | None=None, http_method: HttpMethod=HttpMethod.GET) -> tuple[str | None, str | None]` — 获取真实URL
- `staticmethod def validate_real_url(real_url: str, included: list[str] | None=None, blacklisted: list[str] | None=None) -> tuple[bool, str | None]` — 验证真实URL是否符合要求。
- `async def delete_real_url_cache(play_url: str) -> None` — 删除真实URL缓存
- `async def get_real_url_with_sub(request: Request, play_url: str, ttl: int, included: list[str] | None=None, blacklisted: list[str] | None=None, proxy_url: str | None=None, user_agent: str | None=None, headers: dict | None=None) -> tuple[str | None, str | None]` — 获取真实URL, 如果有子m3u8,获取子m3u8的第一个URL

## `EncryptMixStreamProxy`

class · defined in `oldman.contrib.proxy.encrypt`

```python
class EncryptMixStreamProxy(UrlSealingMixin, BaseStreamProxy)
```

支持加密和缓存的代理类,

Constructor:

```python
EncryptMixStreamProxy(proxy_name: str='base')
```

Members:

- `async def encrypt_url(url: str) -> str` — 把真实 URL 封成不可伪造的路径段；代理、UA 等参数仍走缓存。
- `async def decrypt_url(encrypted_url: str) -> str | None` — 还原真实 URL；被改写或伪造的路径段返回 None。
- `async def get_encrypt_sub_url(channel_id: str, ts_url: str, ext_name: str | None=None) -> str` — 保存TS URL到Redis并生成新URL
- `async def proxy_m3u8_ts_path(channel_id: str, m3u8_content: str, base_url: str, cached_id: str='', sub_ttl: tuple[int, int]=(3600, 300), direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, **extra_context) -> str` — 处理m3u8内容,替换TS路径为代理路径, 并支持加密TS路径
- `async def save_params(channel_id: str, sub_ttl: int, direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, **extra_context) -> None` — 保存TS请求参数到Redis
- `async def load_params(channel_id: str) -> dict[str, Any] | None` — 从Redis加载TS请求参数
- `def calculate_m3u8_ttl(channel_id: str, m3u8_content: str) -> int` — 优化的 TTL 计算：快速判断类型和计算
- `async def fetch_sub_manifest_or_stream(request: Request, channel_id: str, hash_url: str, ttl: int=2, sub_url_ttl: int=0) -> HTTPResponse | None` — 获取子m3u8或ts文件 中转

## `EncryptStreamProxy`

class · defined in `oldman.contrib.proxy.encrypt`

```python
class EncryptStreamProxy(UrlSealingMixin, BaseStreamProxy)
```

支持加密的代理类

Members:

- `async def encrypt_url(url: str) -> str` — 把上下文串封成不可伪造的路径段。
- `async def decrypt_url(encrypted_url: str) -> str | None` — 还原上下文串；被改写或伪造的路径段返回 None。
- `async def save_sub_url(channel_id: str, ts_url: str, direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, ext_name: str | None=None, **extra_context) -> str` — 保存TS URL到Redis并生成新URL
- `async def proxy_m3u8_ts_path(channel_id: str, m3u8_content: str, base_url: str, cached_id: str='', sub_ttl: tuple[int, int]=(3600, 300), direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, **extra_context) -> str`
- `async def proxy_m3u8_ts_path_inter(channel_id: str, m3u8_content: str, base_url: str, direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, **extra_context) -> str` — 处理m3u8内容,替换TS路径为代理路径, 并支持加密TS路径
- `async def get_sub_url(channel_id: str, hash_url: str) -> dict[str, Any] | Any`

## `SimpleEncryptedStreamProxy`

class · defined in `oldman.contrib.proxy.simple`

```python
class SimpleEncryptedStreamProxy(UrlSealingMixin, SimpleStreamProxy)
```

简单加密的流代理, 加密真实URL, 但是不进行任何缓存, 直接转发请求到本地的代理上

Members:

- `def encrypt_url(url: str) -> str` — 把真实 URL 封成不可伪造的路径段。
- `def decrypt_url(encrypted_url: str) -> str | None` — 还原真实 URL；被改写或伪造的路径段返回 None。
- `def get_encrypt_path(base_url: str, url: str, proxy_params_str: str | None=None, local_proxy: str | None=None) -> str`
- `def proxy_m3u8_process(m3u8_content: str, base_url: str, local_proxy: str, direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, **extra_context) -> str` — 处理m3u8内容,替换TS路径为代理路径, 如果本身不包含子m3u8, 那么就生成一个包含实际代理路径的m3u8内容
- `def process_m3u8_ts_path(m3u8_content: str, base_url: str, proxy_params_str: str | None=None, local_proxy: str | None=None) -> str` — 处理m3u8内容,替换TS路径为代理路径
- `async def proxy_sub_manifest_or_stream(request: Request, stream_url: str, params_str: str | None, user_headers: dict[str, str] | None=None, live_stream: bool=False, local_proxy: str | None=None, client_type: str | None=None) -> HTTPResponse | None` — 代理子请求

## `SimpleStreamProxy`

class · defined in `oldman.contrib.proxy.simple`

```python
class SimpleStreamProxy(BaseStreamProxy)
```

简单的流代理, 不进行任何的加密和缓存, 直接转发请求到本地的代理上

Constructor:

```python
SimpleStreamProxy(proxy_name: str='base', local_proxy='')
```

Members:

- `classmethod async def process_manifest(content: str, base_url: str, proxy_params_str: str | None=None, local_proxy: str | None=None) -> str`
- `def proxy_m3u8_process(m3u8_content: str, base_url: str, local_proxy: str, direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, **extra_context) -> str` — 处理m3u8内容,替换TS路径为代理路径, 如果本身不包含子m3u8, 那么就生成一个包含实际代理路径的m3u8内容
- `staticmethod def make_params(direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, **extra_context) -> str` — 序列化请求参数到base64字符串
- `staticmethod def load_params(params_str: str) -> dict[str, Any] | None` — 反序列化请求参数从base64字符串
- `async def proxy_remote_manifest(request: Request, channel_id: str, play_url: str, local_proxy: str | None=None, direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, **extra_context) -> str | None` — 直接代理远程m3u8内容, 不进行任何缓存
- `def get_client_remark(stream_url: str) -> str` — 返回url的md5值作为客户端备注
- `async def proxy_sub_manifest_or_stream(request: Request, stream_url: str, params_str: str | None, user_headers: dict[str, str] | None=None, live_stream: bool=False, local_proxy: str | None=None, client_type: str | None=None) -> HTTPResponse | None` — 代理子请求

## Module `oldman.contrib.proxy.sealing`

The URL sealer the proxy classes share, keyed from the configured root secret.

Import with `from oldman.contrib.proxy.sealing import <name>`.

### `build_url_sealer`

function · defined in `oldman.contrib.proxy.sealing`

```python
def build_url_sealer() -> UrlSealer
```

Derive the proxy's own key from `web.security.secret_key`.

### `UrlSealingMixin`

class · defined in `oldman.contrib.proxy.sealing`

```python
class UrlSealingMixin
```

Give a proxy its sealer, resolved when the instance is built.

Constructor:

```python
UrlSealingMixin(*args: Any, **kwargs: Any) -> None
```

Members:

- `def seal_url(url: str) -> str` — Return the opaque path segment that stands in for `url`.
- `def unseal_url(token: str) -> str | None` — Return the real URL, or None when the token was edited, forged or malformed.
