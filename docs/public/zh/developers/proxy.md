# 流媒体中转

`oldman.contrib.proxy` 的 `BaseStreamProxy`（以及 `SimpleStreamProxy`、`SimpleEncryptedStreamProxy`、`EncryptStreamProxy`、`EncryptMixStreamProxy`）在 Sanic 的路由处理函数里，把上游的 HLS / DASH / TS 内容转给播放器。上游请求走[后端 HTTP 客户端](http-client.md)的 `reconnect_stream`，读取中断后的内部续传在那里完成（见那一页"中断后的续传"）；这一页只写中转层自己的合同：播放器收到什么，以及路由处理函数要知道什么。清单改写、缓存键和 URL 密封见接口索引 `docs/public/en/api/oldman.contrib.proxy.md`。

下面说的规则适用于 `stream_response` 和经过它的入口：`get_ts_stream`、`proxy_stream`、`fetch_sub_manifest_or_stream`（含 `EncryptMixStreamProxy` 的同名入口）、`SimpleStreamProxy.proxy_sub_manifest_or_stream`。`get_ts_stream_direct` 走自己的直连 TCP 实现，不适用。

## 状态码与响应头

经过 `stream_response` 的响应，上游的状态码和响应头原样转给播放器：200、206（带上游的 Content-Range）、304、404 连同错误页正文都一样。逐跳头（Connection、Transfer-Encoding、Keep-Alive 等，以及 Connection 点名的头）不转，同名的头（例如多个 Set-Cookie）逐条保留。发给播放器的响应在读到第一块正文时才创建；上游没有正文时照常发状态码和响应头。

`SimpleStreamProxy` 只有音视频内容（Content-Type 含 video、audio 或 octet-stream）走这条路。上游回 200、206 以外的状态码时，它只回状态码和响应头、不带正文（404 收到的是 `Content-Length: 0`）；上游跳转时回一个指向自己代理路径的 302。其余内容先整份读完：是播放清单（m3u8；`SimpleStreamProxy` 还有 mpd）就把里面的地址改写成代理地址、回 200；不是播放清单的（字幕、JSON、被标成文字类型或没有类型的密钥……）字节、状态码和 Content-Type 照上游原样回，上游没写类型时回 `application/octet-stream`。`fetch_sub_manifest_or_stream` 的 m3u8 分支走 `process_sub_manifest`，回 200 或 404 "Content expired"，也不经过 `stream_response`。

内置入口不会把播放器的 Range 转给上游（`get_request_headers` 只返回基础头）。要转发，就把它放进 `get_ts_stream` 的 `headers=`，或者覆盖 `get_request_headers`；下面说的 206、416 都以此为前提。

## 最终失败

`stream_response` 收到的读取异常都已经是最终失败（内部续传救不回来），按已经发出多少处理：

- **一个字节都还没发**：异常原样抛给入口，`get_ts_stream` 和 `SimpleStreamProxy` 返回 500，不是空的 200。
- **已经发出一部分**：关掉播放器的这条连接，不发结束标记（分块传输没有结束块；带 Content-Length 的比声明的短），播放器据此知道内容不完整、去重新请求；上游的响应交给后台任务放掉（最多等 `RELEASE_TIMEOUT`，2 秒），然后立刻抛出 `RequestCancelled`，原因在 `__cause__` 里。日志记一条带地址的"流式响应异常"，不记成"协程取消"。
- **请求被取消**（播放器断开，或者太久没读走数据、到了 Sanic 的 `RESPONSE_TIMEOUT`）：已经发出一部分的，同样关掉连接、不发结束标记，再把取消原样抛出；入口照常记"协程取消"。

连接在 `stream_response` 里就关掉，所以结果不取决于路由处理函数怎么处理这个异常。路由处理函数要知道的：

- 连接一关，Sanic 就会取消这个处理任务：**处理函数在中转调用之后遇到的第一个 await 会被取消**。中转之后还有收尾工作（写 Redis、释放并发额度等）的，放在中转调用之前做，或者接住 `CancelledError`。
- 把取消吞掉不改变播放器收到的字节，但 Sanic 的日志会不同（原样上抛时都没有）：吞掉后返回另一个响应，上游中途失败时多一条 ERROR（"The response object returned by the route handler will not be sent…"）；返回 None，上游中途失败时没有额外日志，请求方断开、正文带 Content-Length 时多两条 ERROR（"Response was smaller than content-length"、"The error response will not be sent to the client…"）。响应超时发生在第一块正文之前、处理函数返回 None 时，Sanic 记 "Invalid response type None"，播放器收到 500。框架自己的 `proxy_stream`、`fetch_sub_manifest_or_stream`、`SimpleStreamProxy` 是返回 None 的写法。
- 判断是不是上游失败：带原因的 `RequestCancelled`（`error.__cause__ is not None`）是上游最终失败，不带原因的是请求被取消。`SimpleStreamProxy.proxy_sub_manifest_or_stream` 把前者原样上抛，后者照旧记"协程取消"并返回 None。

`get_ts_stream` 的其余关键字参数原样交给 `reconnect_stream`（`retries`、`retry_backoff`、`no_retry_statuses` 等）。例如播放器的 Range 经 `headers` 转给上游、上游见到 Range 就回 416 时，默认去掉 Range 再请求一次，播放器拿到完整的 200；传 `no_retry_statuses=[404, 416]` 则把 416 原样交给播放器。

## 直播入口

`proxy_stream` 一律按直播处理（`live_stream=True`）：上游断开后不带 Range 重连，新连接的字节接在已发出的后面。这对直播是对的（接上的是一条新的流）；有的直播源会发一个很大的假 Content-Length，同样照常重连。点播文件不要走这个入口：一个带 Content-Length 的文件中途断开时，重连回来的是从头开始的内容，会接在已发出的部分后面。点播文件用 `get_ts_stream`，按文件规则带 Range 续传。

## 浏览器指纹与压缩

User-Agent 以 edge、chrome、firefox、safari、curl 开头（不分大小写）时，上游请求走 curl 后端。值以这些字开头（区分大小写）、又不含 `/` 和空白时，当成 curl_cffi 的指纹名，使用浏览器指纹（例如 `chrome`、`chrome124`、`edge`、`safari17_0`、`firefox`）：发出去的 User-Agent 换成指纹自己的，`Accept-Encoding` 也由指纹决定（例如 `gzip, deflate, br, zstd`，`edge` 是 `gzip, deflate, br`）。这样的值不是有效指纹名时（打错的名字，或者 curl_cffi 去掉的版本），每个请求报 ImpersonateError，不会悄悄当成 User-Agent 发出。指纹名里没有 `/` 和空白，所以 `curl/8.0`、`chrome (custom build)`、真实浏览器的 UA（`Chrome/120.0.0.0 …`）走 curl 后端但不用指纹，原样作为 User-Agent 发出；值正好是 `curl` 时不用指纹，发客户端自己的 User-Agent。用了指纹、中转用的客户端又不解压，所以：

- 上游压缩时，压缩过的字节连同 `Content-Encoding` 原样转给播放器；只认 gzip / deflate 的播放器解不开 br、zstd。
- 动态压缩的上游（分块传输、弱 ETag、不理会 Range，nginx 的 gzip / brotli 模块就是这样）中途断开后续不上：既没有长度可比，也不按 Range 续传。播放器会收到没有结束标记的断开。

需要明文的请求在请求头里自己写 `Accept-Encoding: identity`，调用方写的头优先于指纹；`SimpleStreamProxy` 要解析 m3u8，就是这样写的。不用指纹的请求在不解压时本来就发 `identity`。`BaseStreamProxy` 取清单用的是开了解压的 `request()`，作为清单取回的 m3u8 会被解开，不受影响；受影响的是经 `get_ts_stream` / `proxy_stream` 当作流转发的资源。影音切片很少被压缩，主要是字幕、密钥、当作流转发的 m3u8 这类文本。
