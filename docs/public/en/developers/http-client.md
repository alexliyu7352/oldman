# Backend HTTP client

`oldman.contrib.http.MultiHttpClient` lets Python services make outbound requests to other HTTP services. It does not handle inbound Sanic requests or interpret browser DefaultApiResponse.actions. Business code chooses a backend but consumes the common HttpResponse/HttpStreamResponse interfaces.

Agents: before writing code, read the [caching and networking guide (in Chinese)](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/agents/cache-and-network.md) (`docs/public/zh/agents/cache-and-network.md`). It says which interface the task needs, how to wire it and what counts as done.

## Actual use in the demo

The `/examples/http/client` page offers four buttons: JSON, upstream 404, timeout, and byte stream. See [the user tutorial](../users/cache-and-http.md#running-the-backend-http-example) for instructions. Below is the demo's complete [http_example.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/http_example.py):

```python
"""Real upstream diagnostics using the framework's shared HTTP client API."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

import httpx
from oldman.contrib.http import (
    ClientType,
    HttpContentDecodingError,
    HttpMethod,
    HttpStatusError,
    MultiHttpClient,
)

from apps.examples.apps import app

REQUEST_TIMEOUT = 5
STREAM_LIMIT = 1024 * 1024
OPERATION_PATHS = {
    "json": "/get",
    "status": "/status/404",
    "timeout": "/delay/10",
    "stream": "/stream-bytes/65536",
}
# WebService initializes/closes this per-worker client, never per browser request.
# No browser identity or upstream login credentials belong to this shared pool.
http_client = MultiHttpClient(
    client_type=ClientType.HTTPX,
    retry_count=0,
    max_connections=8,
    user_agent="Oldman-EPG-HTTP-Example",
    content_decoding=True,
    verify=True,
)


@dataclass
class HTTPResult:
    """Observed upstream outcome, separate from the Demo response's HTTP status."""

    path: str
    outcome: Literal["success", "http_error", "timeout", "connection_error", "invalid_content", "too_large"] = "success"
    status_code: int | None = None
    content_type: str = ""
    elapsed_ms: float = 0
    json_text: str | None = None
    byte_count: int | None = None
    sha256: str = ""


async def run_http_example(operation: str) -> HTTPResult:
    """Return known network failures as diagnostics; programming errors propagate."""
    path = OPERATION_PATHS[operation]
    url = f"{str(app.settings.http_base_url).rstrip('/')}{path}"
    result = HTTPResult(path=path)
    started = perf_counter()
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            if operation == "stream":
                async with http_client.stream(
                    HttpMethod.GET, url, timeout=REQUEST_TIMEOUT, follow_redirects=False,
                ) as response:
                    result.status_code = response.status_code
                    result.content_type = response.headers.get("content-type", "")
                    response.raise_for_status()
                    if not response.is_success:  # raise_for_status does not reject 3xx.
                        result.outcome = "http_error"
                        return result
                    digest = hashlib.sha256()
                    result.byte_count = 0
                    async for chunk in response.aiter_bytes(4096):
                        result.byte_count += len(chunk)
                        if result.byte_count > STREAM_LIMIT:
                            result.outcome = "too_large"
                            return result  # Exiting the context closes the response.
                        digest.update(chunk)
                    result.sha256 = digest.hexdigest()
            else:
                response = await http_client.get(
                    url, timeout=REQUEST_TIMEOUT, follow_redirects=False,
                    params={"example": "oldman-epg-dashboard"} if operation == "json" else None,
                )
                result.status_code = response.status_code
                result.content_type = response.headers.get("content-type", "")
                response.raise_for_status()
                if not response.is_success:
                    result.outcome = "http_error"
                else:
                    result.json_text = json.dumps(response.json(), ensure_ascii=False, indent=2)
    except HttpStatusError:
        result.outcome = "http_error"
    except (TimeoutError, httpx.TimeoutException):
        result.outcome = "timeout"
    except httpx.RequestError:
        result.outcome = "connection_error"
    except (HttpContentDecodingError, json.JSONDecodeError, UnicodeDecodeError):
        result.outcome = "invalid_content"
    finally:
        result.elapsed_ms = round((perf_counter() - started) * 1000, 1)
    return result
```

`app` comes from the demo's [apps/examples/apps.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/apps.py) and binds [ExamplesSettings](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/settings.py) during service bootstrap. Initialize that service before calling it; do not use default App settings from an uninitialized Shell. HTTPResult is diagnostic data passed to Jinja by this example, not a new framework response protocol.

[views/http.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/http.py) validates operation against a fixed allowlist. It does not forward browser-supplied URLs, Cookies, or user data upstream. HTML strings in JSON appear as text in the result template; upstream HTML is not executed. Known network/parsing failures become explicit diagnostics; actual programming exceptions and cancellation still propagate.

## Creation, initialization, and shutdown

The module's http_client is **an instance created by the demo**, not a framework global singleton. [services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py) imports `from apps.examples.http_example import http_client` and manages it through these two complete WebService methods:

```python
    async def before_server_start(self, app: WebApp) -> None:
        """Initialize the example HTTP adapter without connecting to its upstream."""
        await super().before_server_start(app)
        await http_client.init_client()
```

```python
    async def after_server_stop(self, app: WebApp) -> None:
        """Close the HTTP pool and always preserve the framework's own cleanup."""
        try:
            await http_client.close_client()
        finally:
            await super().after_server_stop(app)
```

These are class methods rather than module-level listeners. WebApp comes from oldman.web.routing, and the parent class is WebApplication. The framework closes caches, Redis, and the database after after_server_stop, even if HTTP-client shutdown fails. The super calls here do nothing but are harmless to retain.

After construction, await init_client before making requests. init_client is idempotent; HTTPX still establishes actual connections on the first request. MultiHttpClient currently is not an async with context manager. Do not invent `await response.json()` for ordinary buffered responses.

For frequent calls, let the service or business client own one instance instead of rebuilding a pool per request. Short standalone commands initialize it in their asynchronous function and close it in try/finally. Application does not automatically close clients created by application code. Built-in atexit handling is only a fallback, not a substitute for explicit closure on the same event loop.

Available types are ClientType.HTTPX, AIOHTTP, and CURL_CFFI. A common response contract does not make private backend parameters, TLS fingerprints, DNS, or Cookie implementations identical. Normal application paths should not call backend-private APIs through native_response.

## Configuration and parameters

The global http_client section contains only max_connections and user_agent. The demo overrides them with explicit constructor values above; business URLs do not belong in that section. Excerpt from the demo's public YAML:

```yaml
app_settings:
  examples:
    http_base_url: https://httpbin.org
```

Merge this into existing configuration without replacing other App settings. ExamplesSettings accepts HTTP(S) base URLs with optional path prefixes and rejects credentials, query strings, and fragments. There is no endpoint accepting arbitrary browser-submitted URLs. Read it through the Examples App's app.settings rather than settings.examples. Initial defaults use public upstream services. Existing configurations can add the fields with settings sync, and deployers can substitute compatible instances of their own.

A standalone script constructing MultiHttpClient without bootstrap uses framework schema defaults; one HTTP request does not require starting Web. This example also reads App Settings, however, so its service bootstrap remains necessary. Constructor max_connections=0 selects the Settings default (300); an explicit positive value overrides it. user_agent=None likewise reads configuration, whose schema default is okhttp/3.8.7.

Other constructor parameters are connect_timeout=10, read_timeout=30, proxy_url=None, retry_count=3, retry_backoff_factor=0.5, no_retry_statuses=None, keepalive_expiry=300, content_decoding=False, nameservers=None, cookie_jar=None, and verify=True. Currently the aiohttp backend consumes nameservers; do not assume HTTPX/curl uses the custom resolver too.

TLS verify accepts only a constructor-level bool and defaults to server-certificate validation. Passing verify per request is rejected before sending. Do not silently hide deployment certificate errors with global verify=False. Verify proxy, CA, credential, and other deployment behavior against the actual backend and environment.

Calling conventions:

- get/post/put/delete(url, **kwargs) are convenience methods.
- For PATCH/HEAD/OPTIONS and others, use `request(HttpMethod.PATCH, url, ...)`.
- Common kwargs include headers, params, data, json, cookies, timeout, and follow_redirects.
- Each backend converts numeric timeout values to its own timeout object; detailed semantics differ. Use an outer asyncio.timeout to limit the entire retry chain.
- Redirects are followed by default. When only a specific endpoint is acceptable, set follow_redirects=False and inspect 3xx responses. The framework has no automatic SSRF address allowlist. Do not turn arbitrary browser input directly into backend fetch URLs.

## Status errors and retries

For ordinary request calls, 2xx responses return immediately. Non-2xx responses retry when permitted, then still return HttpResponse. **Not every 4xx/5xx automatically raises an exception.** Call response.raise_for_status() when exceptions are required. It raises HttpStatusError only for 400–599; business code must still check 3xx.

Default retry_count=3 means the initial attempt plus at most three retries, with exponential delays starting at 0.5 seconds. Default no_retry_statuses is [404]. Per-request retries, no_retry_statuses, and retry_backoff override these. An empty constructor list still selects the default [404], rather than disabling status filtering.

Retries currently do not assess idempotency by HTTP method: POST may also be resent. Ordinary writes, payments, and resource creation should explicitly use `retries=0`, or an instance with retry_count=0. Business code must establish idempotency before enabling retries. error_code is a business field in response JSON; the HTTP client neither interprets it nor retries based on it.

aiohttp also performs its own resend for idempotent requests when the server closes without any response, retrying on another connection. This does not count toward retry_count. If the upstream always closes without responding, retry_count=N sends 2×(N+1) requests with aiohttp, versus N+1 with httpx/curl. After the budget is exhausted, connection/read failures usually propagate as native backend exceptions; cancellation propagates too. Catching only HTTPClientError does not cover all network errors, and RequestFailedError does not inherit it. Protocol-defined status, decoding, stream-consumption, and Range errors are HttpStatusError, HttpContentDecodingError, HttpStreamConsumedError, and HttpRangeError. reconnect_stream adds two cases: a declared live stream repeatedly ending by connection close raises built-in ConnectionError after exhausting retries; an actively read stream attempting to resume after close_client() raises RuntimeError.

## Reading the two response types

| Content | Ordinary HttpResponse | HttpStreamResponse |
| --- | --- | --- |
| Status/URL/headers | status_code, url, headers, reason, http_version | Same |
| Status checks | is_success means 2xx; is_redirect means 3xx; ok means <400 | Same |
| Complete body | content/read(): buffered bytes | await aread(): buffers the entire body in memory |
| Undecoded body | raw_content(): bytes without Content-Encoding decoding | await raw_content(): same |
| Text / JSON | text property / json() | aiter_text / aiter_lines / await json() |
| Chunks | No network chunk iteration; body already read | aiter_bytes or aiter_raw |
| Closure | Backend releases response after reading | Stream context closes on exit; low-level aclose() interface |

headers is case-insensitive. Use get_list(name) or multi_items() for repeated headers; especially, do not concatenate multiple Set-Cookie values before parsing. cookies is a response-Cookie snapshot in standard-library CookieJar form, not the backend client's entire session jar.

Until buffered, a stream can be consumed only once. Calling aread/json after chunk iteration raises HttpStreamConsumedError. Calling aread first permits buffered rereads but loses the memory benefit for large files. Do not return a closed stream for another asynchronous task to continue reading.

## Ordinary streams and Storage

This page already includes a real streaming example: run_http_example's stream branch counts bytes and computes a digest in chunks inside the response context without loading the complete file. Success means only that this transfer completed. The page shows the actual byte count rather than hardcoding the expected 65536. Reading stops above 1 MiB, and partial content has no complete digest. This limit belongs only to the example's stream branch, not ordinary get responses.

Saving downloads directly to Storage combines a different set of interfaces; the current demo has no complete example. Obtain an initialized named Storage, enter client.stream, check the status, pass response.aiter_bytes(...) as Storage.save's asynchronous byte-iterator input, await saving and retain Storage's actual logical name, then exit the response context. Do not close the stream before save or treat the logical name as a local absolute path. See [Storage](storage.md) for input, naming, and save-failure contracts.

The stream context closes the response stream; the client owner still closes its pool. stream mainly retries while establishing a response and does not promise transparent resumption during reading. Business code must not depend on it replaying an already partly delivered body.

content_decoding=False is the current default. Requests normally declare Accept-Encoding: identity and retain original bytes even if the server compresses anyway. True enables unified gzip, deflate, br, and zstd decoding (requests advertise only gzip, deflate by default, but br/zstd responses can still decode). Browser-fingerprinted curl requests are an exception: User-Agent is a curl_cffi fingerprint name such as chrome, chrome124, or edge; see [Media streaming proxy](proxy.md#browser-fingerprints-and-compression). Their fingerprint determines Accept-Encoding regardless of decoding (for example, chrome defaults to gzip, deflate, br, zstd; older fingerprints may omit zstd). Without decoding, returned bytes may therefore be compressed. To request plaintext without decoding, explicitly send Accept-Encoding: identity. raw_content/aiter_raw still expose original bytes. Other encodings and truncated/corrupt compressed bodies raise HttpContentDecodingError. A body containing zero bytes counts as empty rather than truncated: 204, 304, HEAD, Content-Length: 0, and compressed close-delimited bodies disconnected before the first byte. As with uncompressed content, "empty" and "truncated" cannot then be distinguished.

## Resuming after interruption

`async with client.reconnect_stream(HttpMethod.GET, url, live_stream=False, ...) as stream` returns ReconnectStreamResponse, not an ordinary HttpStreamResponse. status_code and response_headers describe the first response and do not change during internal resumption. Read through aiter_bytes. current_response exposes the current connection's underlying response, whose raise_for_status can be called first. The context handles release.

- Status and headers come from the first response and remain unchanged during internal resumption. aiter_bytes(chunk_size) yields whatever arrives; chunk_size is only a maximum chunk size (only for raw chunks when decoding, as below). curl batches small chunks arriving within 50 milliseconds.
- If the upstream rejects the caller's Range with 416, it retries once without Range, without consuming a retry, to obtain full content. Including 416 in no_retry_statuses instead returns it unchanged.
- Default file mode (live_stream=False) resumes interrupted reads with Range at the received-byte offset, without If-Range. Continuity checks use bytes: a 206 must match the first response's start/end/total length, or the upstream may return a full 200 of the same total length (without an initial length, a matching strong ETag is required), skipping previously delivered bytes. Content-Encoding must not change. Multipart responses replay the original request and compare the delivered prefix byte for byte. Changed ETag/Last-Modified values do not count as failure: many CDNs change nodes and these headers while retaining identical content.
- The initial 206 must begin at the caller's requested offset (for suffix ranges, the beginning of the resource's last n bytes), stay within the requested interval, and have valid Content-Range; otherwise HttpRangeError is raised. Servers may provide only part of the range, such as the first 1MB for bytes=0-. That 206 is returned unchanged, and internal resumption stays within that segment. Content-Range determines body length: shorter bodies resume, longer ones fail. An unsolicited 206 without valid Content-Range is read normally but cannot resume.
- Failed continuity raises HttpRangeError (or HttpStatusError for an error status), without concatenation. Accepted risk: replacement content of the same length at the same URL cannot be detected; without an initial length, any replacement cannot be detected.
- A body shorter than Content-Length counts as interrupted even after a normal connection end. A lengthless body missing its terminating chunk counts as complete if resumption receives 416 with `bytes */N` matching the number of bytes already received.
- Resume offsets count **raw bytes**. With content_decoding enabled, the wrapper decodes complete responses (not 206) and removes Content-Encoding and Content-Length from response_headers. It emits raw bytes for 206, HEAD, and unsupported encodings. chunk_size limits only underlying raw chunks: a decoded chunk may be much larger with high compression, and total output is unlimited. Understand this before enabling decoding for untrusted upstreams. Decoded response_headers retain upstream ETag and Accept-Ranges, which describe the compressed representation.
- live_stream=True reconnects the current live stream without Range/If-Range or continuity checks. For close-delimited bodies (HTTP/1.x without length or chunking), upstream closure counts as interruption and triggers reconnection. It provides no seamless replay, packet-loss recovery, or browser SSE event replay.
- The retry budget is consecutive: connection failures, error statuses, and interrupted reads share retry_count. Consecutive reconnects with no new bytes exhaust it and fail; delivering new bytes resets it. A live upstream repeatedly sending a little then disconnecting therefore reconnects until the caller stops reading.
- Only GET 200/206 responses resume as files; declared live streams reconnect as live streams. Other responses, such as POST, fail directly if interrupted mid-body (curl errors before response headers are retried as connection failures).

Use this entry point for downloads/stream forwarding that the application actually needs. Ordinary JSON APIs need only request/get, without resumption logic.

## Cookies and extension

Constructor cookie_jar accepts standard-library CookieJar/MozillaCookieJar. Per-request cookies supplies values for that request, accepts no CookieJar, and cannot accompany an explicit Cookie header. Cookie jars may contain sign-in credentials; do not share one instance across unrelated users.

aiohttp uses its own runtime jar and writes back to the supplied standard-library jar on explicit export_cookies, save_cookies, or close_client. Other backends follow their adapters. save_cookies writes files only for MozillaCookieJar; the application must check permissions before overwriting a destination. The framework does not coordinate concurrent clients sharing a mutable jar.

BaseHttpClient defines the common init_client/reset_client/close_client/request/stream interfaces. Concrete backend constructors receive MultiHttpClient. The factory recognizes only three ClientType values; it has no configuration-path plugin registration interface for arbitrary backends. Prefer composing existing clients for application extensions rather than copying Cookie, streaming, or retry implementations.

<!-- source: zh/developers/http-client.md @ 84e6ddf1 -->
