# `oldman.contrib.proxy`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

@author:alex

Import with `from oldman.contrib.proxy import <name>`.

## `BaseStreamProxy`

class · defined in `oldman.contrib.proxy.base`

```python
class BaseStreamProxy
```

Base class for media streaming proxies.

Constructor:

```python
BaseStreamProxy(proxy_name: str='base')
```

Members:

- `classmethod def generate_channel_id(url: str) -> str` — Generate a channel ID with LRU caching to reduce repeated computation.
- `classmethod def is_use_curl(user_agent: str | None=None) -> bool` — Choose curl_cffi from the user_agent prefix.
- `def get_client_type(user_agent: str | None=None) -> ClientType` — Return the client type.
- `def get_client_key(client_type: ClientType, client_remark: str='', proxy_url: str | None=None, content_decoding: bool=False) -> str`
- `async def get_client(user_agent: str | None=None, proxy_url: str | None=None, content_decoding: bool=False, client_remark: str | None=None) -> MultiHttpClient` — Return or create the HTTP client.
- `async def get_request_headers(request: Request | None=None, base_headers: dict | None=None) -> dict` — Build request headers by merging base headers with important client headers.
- `async def delete_cached_channel_url(channel_id: str)` — Delete the cached channel URL.
- `async def save_cached_channel_url(channel_id: str, url: str, ttl: int=60 * 60 * 24 * 7)` — Cache a channel URL.
- `async def get_cached_channel_url(channel_id: str) -> str | None` — Return a cached channel URL.
- `staticmethod def generate_hash_url(current_id: str, ts_url: str) -> str` — Compute a TS URL hash.
- `async def save_sub_url(channel_id: str, cached_id: str, ts_url: str, sub_ttl: int=60, direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, ext_name: str | None=None, **extra_context) -> str` — Save a TS URL in Redis and generate a new URL.
- `async def get_sub_url(channel_id: str, hash_url: str) -> dict[str, Any] | Any` — Return TS URL information.
- `async def proxy_m3u8_ts_path(channel_id: str, m3u8_content: str, base_url: str, cached_id: str='', sub_ttl: tuple[int, int]=(3600, 300), direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, **extra_context) -> str` — Rewrite TS paths in m3u8 content to proxy paths.
- `def proxy_mpd_path(mpd_content: str, play_url: str) -> str` — Rewrite TS paths in mpd content to proxy paths.
- `async def get_final_m3u8(request: Request, m3u8_url: str, user_agent: str | None=None, proxy_url: str | None=None, headers: dict[str, str] | None=None, **extra_context) -> tuple[str | None, str]` — Fetch m3u8 content with nested-playlist support.
- `def update_ttl_from_content(m3u8_content: str, current_ttl: int) -> int` — Extract cache duration from m3u8 content and update its TTL.
- `async def fetch_remote_manifest(request: Request, channel_id: str, play_url: str, ttl: int=2, sub_ttl: tuple[int, int]=(3600, 300), direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, is_sub_manifest: bool=False, **extra_context) -> str | None` — Fetch remote m3u8 content with caching.
- `async def stream_response(request: Request, response: ReconnectStreamResponse, content_type: str='video/mp2t') -> None` — Stream response content.
- `async def get_ts_stream(request: Request, ts_url: str, proxy_url: str | None=None, user_agent: str | None=None, headers: dict[str, str] | None=None, live_stream: bool=False, **kwargs: Any) -> HTTPResponse | None` — Fetch TS stream content.
- `async def get_ts_stream_direct(request: Request, ts_url: str, proxy_url: str | None=None, user_agent: str | None=None) -> HTTPResponse | None` — Fetch TS content over direct TCP with optimized CPU use and chunked-encoding handling.
- `async def process_sub_manifest(request: Request, channel_id: str, ts_context: dict[str, Any], ttl: int=2, sub_ttl: int=0, **kwargs) -> HTTPResponse | None` — Process a child m3u8 playlist, allowing subclass-specific behavior.
- `async def process_sub_stream(request: Request, channel_id: str, ts_context: dict[str, Any], **kwargs) -> HTTPResponse | None` — Process a child stream, allowing subclass-specific behavior.
- `async def fetch_sub_manifest_or_stream(request: Request, channel_id: str, hash_url: str, ttl: int=2, sub_url_ttl: int=0) -> HTTPResponse | None` — Fetch and proxy a child m3u8 playlist or TS file.
- `async def proxy_stream(request: Request, play_url: str, direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, headers: dict[str, str] | None=None) -> HTTPResponse | None` — Proxy a live media stream.
- `async def get_real_url(request: Request, play_url: str, ttl: int, included: list[str] | None=None, blacklisted: list[str] | None=None, proxy_url: str | None=None, user_agent: str | None=None, headers: dict | None=None, http_method: HttpMethod=HttpMethod.GET) -> tuple[str | None, str | None]` — Return the real URL.
- `staticmethod def validate_real_url(real_url: str, included: list[str] | None=None, blacklisted: list[str] | None=None) -> tuple[bool, str | None]` — Validate whether the real URL meets requirements.
- `async def delete_real_url_cache(play_url: str) -> None` — Delete the cached real URL.
- `async def get_real_url_with_sub(request: Request, play_url: str, ttl: int, included: list[str] | None=None, blacklisted: list[str] | None=None, proxy_url: str | None=None, user_agent: str | None=None, headers: dict | None=None) -> tuple[str | None, str | None]` — Return the real URL, choosing the first child m3u8 URL when present.

## `EncryptMixStreamProxy`

class · defined in `oldman.contrib.proxy.encrypt`

```python
class EncryptMixStreamProxy(UrlSealingMixin, BaseStreamProxy)
```

Proxy class supporting encryption and caching.

Constructor:

```python
EncryptMixStreamProxy(proxy_name: str='base')
```

Members:

- `async def encrypt_url(url: str) -> str` — Seal the real URL into an unforgeable path segment while retaining proxy, UA, and other parameters in cache.
- `async def decrypt_url(encrypted_url: str) -> str | None` — Restore the real URL, returning None for modified or forged path segments.
- `async def get_encrypt_sub_url(channel_id: str, ts_url: str, ext_name: str | None=None) -> str` — Save a TS URL in Redis and generate a new URL.
- `async def proxy_m3u8_ts_path(channel_id: str, m3u8_content: str, base_url: str, cached_id: str='', sub_ttl: tuple[int, int]=(3600, 300), direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, **extra_context) -> str` — Rewrite m3u8 TS paths to proxy paths with optional encrypted TS paths.
- `async def save_params(channel_id: str, sub_ttl: int, direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, **extra_context) -> None` — Save TS request parameters in Redis.
- `async def load_params(channel_id: str) -> dict[str, Any] | None` — Load TS request parameters from Redis.
- `def calculate_m3u8_ttl(channel_id: str, m3u8_content: str) -> int` — Compute TTL efficiently with fast type checks.
- `async def fetch_sub_manifest_or_stream(request: Request, channel_id: str, hash_url: str, ttl: int=2, sub_url_ttl: int=0) -> HTTPResponse | None` — Fetch and proxy a child m3u8 playlist or TS file.

## `EncryptStreamProxy`

class · defined in `oldman.contrib.proxy.encrypt`

```python
class EncryptStreamProxy(UrlSealingMixin, BaseStreamProxy)
```

Proxy class with encryption support.

Members:

- `async def encrypt_url(url: str) -> str` — Seal a context string into an unforgeable path segment.
- `async def decrypt_url(encrypted_url: str) -> str | None` — Restore a context string, returning None for modified or forged path segments.
- `async def save_sub_url(channel_id: str, ts_url: str, direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, ext_name: str | None=None, **extra_context) -> str` — Save a TS URL in Redis and generate a new URL.
- `async def proxy_m3u8_ts_path(channel_id: str, m3u8_content: str, base_url: str, cached_id: str='', sub_ttl: tuple[int, int]=(3600, 300), direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, **extra_context) -> str`
- `async def proxy_m3u8_ts_path_inter(channel_id: str, m3u8_content: str, base_url: str, direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, **extra_context) -> str` — Rewrite m3u8 TS paths to proxy paths with optional encrypted TS paths.
- `async def get_sub_url(channel_id: str, hash_url: str) -> dict[str, Any] | Any`

## `SimpleEncryptedStreamProxy`

class · defined in `oldman.contrib.proxy.simple`

```python
class SimpleEncryptedStreamProxy(UrlSealingMixin, SimpleStreamProxy)
```

A simple encrypted stream proxy that seals real URLs and forwards locally without caching.

Members:

- `def encrypt_url(url: str) -> str` — Seal the real URL into an unforgeable path segment.
- `def decrypt_url(encrypted_url: str) -> str | None` — Restore the real URL, returning None for modified or forged path segments.
- `def get_encrypt_path(base_url: str, url: str, proxy_params_str: str | None=None, local_proxy: str | None=None) -> str`
- `def proxy_m3u8_process(m3u8_content: str, base_url: str, local_proxy: str, direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, **extra_context) -> str` — Rewrite m3u8 TS paths, generating a playlist containing the actual proxy path when there are no child playlists.
- `def process_m3u8_ts_path(m3u8_content: str, base_url: str, proxy_params_str: str | None=None, local_proxy: str | None=None) -> str` — Rewrite TS paths in m3u8 content to proxy paths.
- `async def proxy_sub_manifest_or_stream(request: Request, stream_url: str, params_str: str | None, user_headers: dict[str, str] | None=None, live_stream: bool=False, local_proxy: str | None=None, client_type: str | None=None) -> HTTPResponse | None` — Proxy a child request.

## `SimpleStreamProxy`

class · defined in `oldman.contrib.proxy.simple`

```python
class SimpleStreamProxy(BaseStreamProxy)
```

A simple stream proxy forwarding requests locally without encryption or caching.

Constructor:

```python
SimpleStreamProxy(proxy_name: str='base', local_proxy='')
```

Members:

- `classmethod async def process_manifest(content: str, base_url: str, proxy_params_str: str | None=None, local_proxy: str | None=None) -> str`
- `def proxy_m3u8_process(m3u8_content: str, base_url: str, local_proxy: str, direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, **extra_context) -> str` — Rewrite m3u8 TS paths, generating a playlist containing the actual proxy path when there are no child playlists.
- `staticmethod def make_params(direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, **extra_context) -> str` — Serialize request parameters as a base64 string.
- `staticmethod def load_params(params_str: str) -> dict[str, Any] | None` — Deserialize request parameters from a base64 string.
- `async def proxy_remote_manifest(request: Request, channel_id: str, play_url: str, local_proxy: str | None=None, direct: bool=False, proxy_url: str | None=None, user_agent: str | None=None, **extra_context) -> str | None` — Proxy remote m3u8 content directly without caching.
- `def get_client_remark(stream_url: str) -> str` — Return the URL's MD5 digest as the client label.
- `async def proxy_sub_manifest_or_stream(request: Request, stream_url: str, params_str: str | None, user_headers: dict[str, str] | None=None, live_stream: bool=False, local_proxy: str | None=None, client_type: str | None=None) -> HTTPResponse | None` — Proxy a child request.

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
