# Media streaming proxy

`BaseStreamProxy` in `oldman.contrib.proxy` (and `SimpleStreamProxy`, `SimpleEncryptedStreamProxy`, `EncryptStreamProxy`, and `EncryptMixStreamProxy`) forwards upstream HLS / DASH / TS content to players inside Sanic route handlers. Upstream requests use [Backend HTTP client](http-client.md)'s `reconnect_stream`, which performs internal resumption after interrupted reads (see "Resuming after interruption" on that page). This page covers the proxy layer's own contract: what the player receives and what route handlers need to know. For manifest rewriting, cache keys, and URL sealing, see the API index at `docs/public/en/api/oldman.contrib.proxy.md`.

These rules apply to `stream_response` and entry points using it: `get_ts_stream`, `proxy_stream`, `fetch_sub_manifest_or_stream` (including the same-named `EncryptMixStreamProxy` entry point), and `SimpleStreamProxy.proxy_sub_manifest_or_stream`. `get_ts_stream_direct` uses its own direct TCP implementation and is excluded.

## Status codes and response headers

Responses through `stream_response` preserve upstream status codes and headers for the player: 200, 206 (with upstream Content-Range), 304, and 404 including error-page bodies. Hop-by-hop headers (Connection, Transfer-Encoding, Keep-Alive, and headers named by Connection) are excluded. Repeated headers such as Set-Cookie are retained individually. The player response is created only upon reading the first body chunk; an empty upstream body still sends the status and headers normally.

`SimpleStreamProxy` uses this path only for audiovisual content (Content-Type containing video, audio, or octet-stream). For upstream statuses other than 200/206, it returns only the status and headers without a body (404 has `Content-Length: 0`). Upstream redirects become a 302 pointing to its own proxy path. Other content is read fully first. Playlists (m3u8, and mpd for `SimpleStreamProxy`) have their URLs rewritten to proxy URLs and return 200. Non-playlists (subtitles, JSON, keys marked as text or without a type, etc.) retain upstream bytes, status, and Content-Type, defaulting to `application/octet-stream` if absent. The m3u8 branch of `fetch_sub_manifest_or_stream` uses `process_sub_manifest`, returns 200 or 404 "Content expired", and also bypasses `stream_response`.

Built-in entry points do not forward player Range headers upstream: `get_request_headers` returns only base headers. To forward Range, include it in `get_ts_stream`'s `headers=` or override `get_request_headers`. The 206/416 behavior below assumes this forwarding.

## Final failures

Read exceptions reaching `stream_response` are final failures that internal resumption could not recover. Handling depends on how much has been sent:

- **No bytes sent yet**: the exception propagates unchanged to the entry point. `get_ts_stream` and `SimpleStreamProxy` return 500 rather than an empty 200.
- **Some bytes already sent**: the player's connection closes without a terminator (no final chunk for chunked transfer; fewer bytes than declared with Content-Length). The player can detect incomplete content and request again. A background task releases the upstream response, waiting at most `RELEASE_TIMEOUT` (2 seconds), while `RequestCancelled` is raised immediately with the cause in `__cause__`. One streaming-response error containing the URL is logged, rather than a coroutine-cancellation message.
- **Request cancelled** (player disconnect or Sanic `RESPONSE_TIMEOUT` because data was not consumed in time): if any bytes were sent, the connection likewise closes without a terminator, then cancellation propagates unchanged. The entry point logs coroutine cancellation normally.

`stream_response` closes the connection itself, so the result does not depend on the route handler's exception handling. Route handlers need to know:

- Once the connection closes, Sanic cancels the handler task: **the handler's first await after the proxy call is cancelled**. Perform subsequent cleanup (Redis writes, concurrency-slot release, etc.) before the proxy call or catch `CancelledError`.
- Swallowing cancellation does not change the bytes received by the player, but changes Sanic logs (none of these occur when it propagates). Returning another response adds an ERROR after mid-stream upstream failure ("The response object returned by the route handler will not be sent…"). Returning None adds no log for upstream failure, but adds two ERRORs for caller disconnect with Content-Length ("Response was smaller than content-length" and "The error response will not be sent to the client…"). If response timeout occurs before the first body chunk and the handler returns None, Sanic logs "Invalid response type None" and the player receives 500. Framework `proxy_stream`, `fetch_sub_manifest_or_stream`, and `SimpleStreamProxy` use the return-None pattern.
- To distinguish upstream failure, inspect `RequestCancelled`: a cause (`error.__cause__ is not None`) means final upstream failure; no cause means request cancellation. `SimpleStreamProxy.proxy_sub_manifest_or_stream` propagates the former unchanged, while logging coroutine cancellation and returning None for the latter as before.

Other `get_ts_stream` keyword arguments pass unchanged to `reconnect_stream`, including `retries`, `retry_backoff`, and `no_retry_statuses`. For example, when a player Range is forwarded through `headers` and the upstream rejects any Range with 416, the default retries once without Range and gives the player a complete 200. `no_retry_statuses=[404, 416]` instead passes 416 unchanged to the player.

## Live-stream entry point

`proxy_stream` always uses live mode (`live_stream=True`). After an upstream disconnect, it reconnects without Range and appends the new connection's bytes to those already sent. This suits live streams because the reconnection supplies a new stream. Some live sources send a large fictitious Content-Length; they still reconnect normally. Do not use this entry point for on-demand files: after a mid-file disconnect, reconnection starts from the beginning and appends that content to the delivered prefix. Use `get_ts_stream` for on-demand files to resume with Range under file rules.

## Browser fingerprints and compression

A User-Agent beginning with edge, chrome, firefox, safari, or curl (case-insensitively) selects the curl backend. If it begins with one of those words case-sensitively and contains neither `/` nor whitespace, it is treated as a curl_cffi browser fingerprint name, such as `chrome`, `chrome124`, `edge`, `safari17_0`, or `firefox`. The outgoing User-Agent becomes the fingerprint's own value, and the fingerprint also controls `Accept-Encoding` (for example, `gzip, deflate, br, zstd`; `edge` uses `gzip, deflate, br`). An invalid fingerprint name (a typo or a version removed by curl_cffi) raises ImpersonateError per request rather than silently being sent as User-Agent. Fingerprint names contain no `/` or whitespace, so `curl/8.0`, `chrome (custom build)`, and actual browser UAs (`Chrome/120.0.0.0 …`) select curl without fingerprinting and are sent unchanged. Exactly `curl` disables fingerprinting and uses the client's own User-Agent. With fingerprinting and the proxy client's decoding disabled:

- Compressed upstream bytes and `Content-Encoding` pass unchanged to the player. Players supporting only gzip/deflate cannot decode br/zstd.
- Dynamically compressed upstreams (chunked transfer, weak ETag, ignored Range, as with nginx gzip/brotli modules) cannot resume after interruption: there is no comparable length or Range resumption. Players receive a disconnect without a terminator.

Requests needing plaintext should explicitly send `Accept-Encoding: identity`; caller headers override the fingerprint. `SimpleStreamProxy` does this to parse m3u8. Without fingerprints, non-decoding requests already send `identity`. `BaseStreamProxy` fetches manifests through decoding-enabled `request()`, so m3u8 fetched as manifests is decoded and unaffected. Resources forwarded as streams through `get_ts_stream` / `proxy_stream` are affected. Audiovisual segments are rarely compressed; the main cases are text such as subtitles, keys, and m3u8 forwarded as streams.

<!-- source: zh/developers/proxy.md @ c9869a81 -->
