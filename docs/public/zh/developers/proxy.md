# 流媒体中转

`oldman.contrib.proxy` 的 `BaseStreamProxy`（以及 `SimpleStreamProxy`、`SimpleEncryptedStreamProxy`、`EncryptStreamProxy`、`EncryptMixStreamProxy`）在 Sanic 的路由处理函数里，把上游的 HLS / DASH / TS 内容转给播放器。上游请求走[后端 HTTP 客户端](http-client.md)的 `reconnect_stream`，读取中断后的内部续传在那里完成（见那一页"中断后的续传"）；这一页只写中转层自己的合同：播放器收到什么，以及路由处理函数要知道什么。清单改写、缓存键和 URL 密封见接口索引 `docs/public/en/api/oldman.contrib.proxy.md`。

下面说的规则适用于 `stream_response` 和经过它的入口：`get_ts_stream`、`proxy_stream`、`fetch_sub_manifest_or_stream`（含 `EncryptMixStreamProxy` 的同名入口）、`SimpleStreamProxy.proxy_sub_manifest_or_stream`。`get_ts_stream_direct` 走自己的直连 TCP 实现，不适用。

## 状态码与响应头

上游的状态码和响应头原样转给播放器：200、206（带上游的 Content-Range）、304、404 连同错误页正文都一样。逐跳头（Connection、Transfer-Encoding、Keep-Alive 等，以及 Connection 点名的头）不转，同名的头（例如多个 Set-Cookie）逐条保留。发给播放器的响应在读到第一块正文时才创建；上游没有正文时照常发状态码和响应头。

## 最终失败

`stream_response` 收到的读取异常都已经是最终失败（内部续传救不回来），按已经发出多少处理：

- **一个字节都还没发**：异常原样抛给入口，`get_ts_stream` 和 `SimpleStreamProxy` 返回 500，不是空的 200。
- **已经发出一部分**：关掉播放器的这条连接，不发结束标记（分块传输没有结束块；带 Content-Length 的比声明的短），播放器据此知道内容不完整、去重新请求；上游的响应交给后台任务放掉（最多等 `RELEASE_TIMEOUT`，2 秒），然后立刻抛出 `RequestCancelled`，原因在 `__cause__` 里。日志记一条带地址的"流式响应异常"，不记成"协程取消"。
- **请求被取消**（播放器断开，或者太久没读走数据、到了 Sanic 的 `RESPONSE_TIMEOUT`）：已经发出一部分的，同样关掉连接、不发结束标记，再把取消原样抛出；入口照常记"协程取消"。

连接在 `stream_response` 里就关掉，所以结果不取决于路由处理函数怎么处理这个异常。路由处理函数要知道的：

- 连接一关，Sanic 就会取消这个处理任务：**处理函数在中转调用之后遇到的第一个 await 会被取消**。中转之后还有收尾工作（写 Redis、释放并发额度等）的，放在中转调用之前做，或者接住 `CancelledError`。
- 把取消吞掉、再返回 None 或另一个响应，播放器收到的字节不变，但 Sanic 会多记一条 ERROR（"The response object returned by the route handler will not be sent…"；响应超时发生在第一块正文之前、处理函数返回 None 时，是 "Invalid response type None"，播放器收到 500）。原样上抛就没有这条日志。
- 判断是不是上游失败：带原因的 `RequestCancelled`（`error.__cause__ is not None`）是上游最终失败，不带原因的是请求被取消。`SimpleStreamProxy.proxy_sub_manifest_or_stream` 把前者原样上抛，后者照旧记"协程取消"并返回 None。

`get_ts_stream` 的其余关键字参数原样交给 `reconnect_stream`（`retries`、`retry_backoff`、`no_retry_statuses` 等）。例如播放器带着 Range 来、上游见到 Range 就回 416 时，默认去掉 Range 再请求一次，播放器拿到完整的 200；传 `no_retry_statuses=[404, 416]` 则把 416 原样交给播放器。

## 直播入口

`proxy_stream` 一律按直播处理（`live_stream=True`）：上游断开后不带 Range 重连，新连接的字节接在已发出的后面。这对直播是对的（接上的是一条新的流）；有的直播源会发一个很大的假 Content-Length，同样照常重连。点播文件不要走这个入口：一个带 Content-Length 的文件中途断开时，重连回来的是从头开始的内容，会接在已发出的部分后面。点播文件用 `get_ts_stream`，按文件规则带 Range 续传。

## 浏览器指纹与压缩

User-Agent 以 chrome、edge、firefox、safari 等开头时，上游请求走 curl 后端并使用对应的浏览器指纹，`Accept-Encoding` 由指纹决定（例如 `gzip, deflate, br, zstd`）。中转用的客户端不解压，所以：

- 上游压缩时，压缩过的字节连同 `Content-Encoding` 原样转给播放器；只认 gzip / deflate 的播放器解不开 br、zstd。
- 动态压缩的上游（分块传输、弱 ETag、不理会 Range，nginx 的 gzip / brotli 模块就是这样）中途断开后续不上：既没有长度可比，也不按 Range 续传。播放器会收到没有结束标记的断开。

需要明文的请求在请求头里自己写 `Accept-Encoding: identity`，调用方写的头优先于指纹；`SimpleStreamProxy` 要解析 m3u8，就是这样写的。不用指纹的请求在不解压时本来就发 `identity`。影音切片很少被压缩，受影响的主要是 m3u8、字幕、密钥这类文本资源。
