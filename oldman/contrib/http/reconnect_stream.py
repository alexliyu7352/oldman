"""
@author:alex
@date:2025/8/10
@time:13:52
"""

__author__ = "alex"
import asyncio
import re
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AbstractAsyncContextManager, aclosing
from email.message import Message
from hashlib import sha256
from typing import Any, Protocol

import httpx
from curl_cffi.requests import Response as CurlResponse

from oldman.contrib.http.contants import StreamConnectionError, StreamReadError
from oldman.contrib.http.exceptions import HttpContentDecodingError, HttpRangeError, HttpStatusError
from oldman.contrib.http.response import (
    _DECODER_ERRORS,
    HttpHeaders,
    HttpStreamResponse,
    _content_decoder,
    _content_encodings,
    _ContentDecoder,
)
from oldman.contrib.http.schemas import HttpMethod
from oldman.logging import logger

from ._logging import redact_url

_CONTENT_RANGE_PATTERN = re.compile(r"^bytes\s+(\d+)-(\d+)/(\d+|\*)$", re.IGNORECASE)
# 416 的 Content-Range 只有资源的总长度。
_UNSATISFIED_RANGE_PATTERN = re.compile(r"^bytes\s+\*/(\d+)$", re.IGNORECASE)
# 读正文时可以续传的中断：后端的读取错误和超时、正文短于声明的长度、直播流的上游关了连接。
_READ_ERRORS = (*StreamReadError, httpx.TimeoutException, TimeoutError, asyncio.IncompleteReadError, ConnectionError)
# curl 的队列空了以后，先等这么久（秒）再把攒着的块交出去，见 _iter_response。
_CURL_BATCH_WAIT = 0.05


class _ShortBody(asyncio.IncompleteReadError):
    """包装器自己发现的正文不足（连接正常结束、字节却不够）：按读取中断续传；续不上时以 HttpRangeError 交给调用方。"""

    def __init__(self, message: str, missing: int) -> None:
        super().__init__(b"", missing)
        self.message = message


class _HttpClientParent(Protocol):
    """断点续传所需的 MultiHttpClient 最小配置接口。"""

    retry_count: int
    retry_backoff_factor: float
    no_retry_statuses: list[int]
    timeout_count: int
    proxy_url: str | None
    content_decoding: bool


class _ReconnectClient(Protocol):
    """断点续传只依赖 backend 的统一流接口。"""

    @property
    def parent(self) -> _HttpClientParent:
        """返回持有重试和健康状态的父客户端。"""

        ...

    def reconnect_stream(
        self,
        method: HttpMethod,
        url: str,
        live_stream: bool = False,
        **kwargs: Any,
    ) -> AbstractAsyncContextManager[HttpStreamResponse]:
        """返回一个尚未进入的统一流上下文。"""

        ...


class ReconnectStreamResponse:
    """读取中断后自动重连的流式响应。上层业务先拿响应头、再读正文，所以底层上下文跨 connect 和 aiter_bytes 保存。

    对外的状态码和响应头在首次响应时确定，内部重连不改变它们。底层始终读未经解压的实体字节，Range 的偏移和长度都按它算。
    首次的 206 必须从调用方要的起点开始、落在要的区间之内（可以只是一部分，见 _check_requested_range），正文长度以 Content-Range 为准。

    **文件**（live_stream=False，默认）：读取中断后从已收下的位置带 Range 续传，接不接得上只核对字节层面：
    - 上游按要求回 206：起点、终点、总长度都要和首次对得上；
    - 上游不理会 Range、把完整内容重发一遍（200）：总长度要和首次相同（首次没有长度时，要强 ETag 和首次相同），
      再按字节数跳过已经交出的部分；
    - 压缩方式（Content-Encoding）要和首次相同；
    - multipart（多区间）响应的正文每次由服务器临时拼出，只能重放原请求，并逐字节比对已交出的部分（只对它记输出摘要）。
    其余情况明确失败，不拼接。ETag、Last-Modified、Content-Type 和首次不同不算失败，续传也不带 If-Range：
    很多 CDN 每次把请求分到不同的节点，内容相同，这几个头却各不相同（用户 2026-10-18 定）。
    已接受的风险：同一个地址上的内容被换成长度相同的另一份时发现不了，前后两份会拼在一起（curl -C、wget -c 相同）；
    首次响应没有长度时，换成任何长度的另一份都发现不了。

    **直播**（live_stream=True，由调用方声明，封装层不猜）：重连得到的是一条新的流，接着输出，不核对接不接得上；
    正文靠关连接结束（HTTP/1.x、没有 Content-Length、也不分块）时，上游关连接按中断处理去重连。
    分块正文收到结束块、或读满 Content-Length 的，是上游明确的结束，不重连。

    重试预算是连续的：连接失败、错误状态码和读取中断共用一份，重连后又交出了新字节，预算就恢复（文件和直播都这样）。

    客户端开了 content_decoding 时由这里解压后输出（gzip、deflate、br、zstd，与 HttpStreamResponse 同一套严格的解码器：
    截断、坏数据、压缩流后面的多余数据都报错），对外响应头去掉 Content-Encoding 和 Content-Length。
    206、HEAD、认不出的压缩方式按原始字节输出，响应头不动。解压器跨文件的内部续传保留，直播重连时换新的。
    """

    def __init__(
        self,
        client: _ReconnectClient,
        method: HttpMethod,
        url: str,
        live_stream: bool = False,
        **kwargs,
    ) -> None:
        """保存原始请求，网络连接延迟到 ``connect``。"""

        self.client: _ReconnectClient = client
        self.method = method
        self.url = url
        self._log_url = redact_url(url)
        self.kwargs = kwargs

        # 已经交给调用方的字节数（解压输出时是解压后的字节数）。
        self.transmitted_bytes = 0
        # 本次响应已收下的实体字节数（未解压）：续传位置和长度核对都按它算。
        self._received_bytes = 0
        self.retries_left = kwargs.pop("retries", client.parent.retry_count)
        self.retry_backoff = kwargs.pop("retry_backoff", client.parent.retry_backoff_factor)
        self.no_retry_statuses = kwargs.pop("no_retry_statuses", client.parent.no_retry_statuses)
        self.status_code: int | None = None
        self.response_headers = HttpHeaders()
        self.supports_range = True
        # 本次响应的长度（字节）；None 表示未知，不能把 0 当成已经读完。
        self.content_length: int | None = None
        self.range_tested = False  # 首次响应到达后才确定范围和续传方式
        self.live_stream = live_stream
        self.current_response: HttpStreamResponse | None = None
        self._response_context: AbstractAsyncContextManager[HttpStreamResponse] | None = None

        # 调用方的 Range / If-Range 只用于首次请求。
        self.headers: dict[str, str] = dict(kwargs.get("headers", {}) or {})
        self.original_range_header = next((value for name, value in self.headers.items() if name.lower() == "range"), None)
        # 本次响应在资源里的起点、终点（含）和资源总长度；首次响应到达后由它确定。
        self.response_start = 0
        self.response_end: int | None = None
        self.total_length: int | None = None
        if live_stream:
            self.supports_range = False
            self.original_range_header = None
            self._set_header(self.headers, "Range", None)
            self._set_header(self.headers, "If-Range", None)
        # 上游用 416 拒绝过调用方的 Range，已经改成不带 Range 重新请求（见 connect）。
        self._range_refused = False

        self._initial_headers: HttpHeaders | None = None
        # 首次是成功的 GET（200/206）、不是直播：按文件规则续传。
        self._finite = False
        # 当前这条连接的正文靠关连接结束：结束和中断分不出来。
        self._ends_at_close = False
        self._multipart = False
        # 首次响应的强 ETag：只在上游重发完整内容、又没有长度可比时用（见 _prepare_recovery）。
        self._strong_etag: str | None = None
        # 由这里解压时，决定解码器的响应头；解码器在第一块正文到达时建立。
        self._decode_headers: HttpHeaders | None = None
        self._decoder: _ContentDecoder | None = None
        # 只有 multipart 记输出摘要：它的重放要靠比对已交出的字节才能确认接得上。
        self._output_digest = sha256()
        self._replayed_digest = sha256()
        # 当前连接的读取位置，以及要跳过的已交出部分的终点，都是资源里的绝对偏移。
        self._read_offset = 0
        self._skip_until = 0
        # 首次是 206、续传拿到完整 200 时，读到原区间的终点就结束。
        self._truncate_at_end = False
        # initial：首次请求；range：从收下的位置带 Range 续传；replay：重放原请求。两者对 206 起点的要求不同。
        self._request_mode = "initial"
        self._request_headers = HttpHeaders()
        self._retries_remaining = self.retries_left
        self._recovery_attempt = 0
        self._backoff_pending = False
        # 续传时才确认内容其实已经收全（见 _prepare_recovery 的 416）：不再读正文，直接结束。
        self._complete = False

    async def connect(self) -> None:
        """建立首次响应；读取中断后也由它建立恢复响应。连接失败、错误状态码和读取中断共用一份连续的重试预算。"""

        if self.client is None:
            raise RuntimeError("流式响应已经释放")
        if not self.range_tested:
            self._reset_recovery_budget()
        # 下一次请求不是失败后的重试，而是把同一个请求去掉 Range 再问一次（见下面的 416）：不扣预算、不退避。
        asking_again = False
        while True:
            # 先放掉上一次尝试的响应再退避：留着它，那条连接在等待期间一直占着连接池。
            await self.release_response()
            if self._backoff_pending and not asking_again:
                await self._wait_before_retry()
            self._backoff_pending = False
            asking_again = False
            try:
                context = self._get_stream_response()
                response = await context.__aenter__()
            except StreamConnectionError as error:
                if isinstance(error, TimeoutError | httpx.TimeoutException):
                    self.incr_timeout()
                if not self._consume_retry():
                    raise
                self._backoff_pending = True
                logger.warning(f"流式连接失败，尝试重新连接: {type(error).__name__}, [{self._log_url}]")
                continue
            self._response_context = context
            self.current_response = response
            status = response.status_code
            if status == 416 and not self.range_tested and self.original_range_header and status not in self.no_retry_statuses:
                # 上游不接受调用方带来的 Range：去掉 Range 把同一个请求再发一次，拿完整的内容（服务器本来就可以不理会 Range）。
                # 播放器带着 Range 来（ffmpeg 默认带 bytes=0-），有的上游（没有长度的流尤其如此）见到 Range 就回 416。
                # 只做这一次。调用方不要这个行为，就把 416 写进 no_retry_statuses，416 原样交回。
                logger.warning(f"上游用 416 拒绝了请求里的 Range，去掉 Range 重新请求: {self.original_range_header}, [{self._log_url}]")
                self._set_header(self.headers, "Range", None)
                self._set_header(self.headers, "If-Range", None)
                self.original_range_header = None
                self._range_refused = True
                asking_again = True
                continue
            # 续传时的 416 不在这里重试，交给 _prepare_recovery 判断（内容其实已经收全，或者接不上）。
            if not response.is_success and status != 416 and status not in self.no_retry_statuses and self._consume_retry():
                logger.warning(f"流式连接收到状态码 {status}，将重试: {self._log_url}")
                self._backoff_pending = True
                continue
            try:
                self.update_response_status(response)
            except BaseException:
                await self.release_response()
                raise
            self.incr_timeout(True)
            return

    def _reset_recovery_budget(self) -> None:
        """交出新字节以后恢复完整的重试预算。"""

        self._retries_remaining = self.retries_left
        self._recovery_attempt = 0

    def _consume_retry(self) -> bool:
        """消费一次连续重试预算。"""

        if self._retries_remaining <= 0:
            return False
        self._retries_remaining -= 1
        self._recovery_attempt += 1
        return True

    async def _wait_before_retry(self) -> None:
        """在已经放掉失败的响应之后做一次指数退避。"""

        wait_time = self.retry_backoff * (2 ** (self._recovery_attempt - 1))
        if wait_time > 0:
            await asyncio.sleep(wait_time)

    def _get_stream_response(self) -> AbstractAsyncContextManager[HttpStreamResponse]:
        """首次请求照原样发；恢复时按首次响应决定带内部 Range 还是重放原请求。

        每一次都请求调用方给的地址（经过跳转的，续传也重新走一遍入口）：入口每次给出的最终地址可以不同，
        带一次性签名的地址用过就失效，CDN 调度时原来的节点可能正是出了故障的那个。
        """

        client = self.client
        if client is None:
            raise RuntimeError("流式响应已经释放")
        headers = self.headers.copy()
        self._request_mode = "initial"
        if self.range_tested:
            self._request_mode = "replay"
            if self.live_stream:
                self._set_header(headers, "Range", None)
                self._set_header(headers, "If-Range", None)
            elif self._finite and not self._multipart and self.supports_range:
                # 从收下的实体字节之后接着要，调用方区间的终点保留；不带 If-Range（调用方带来的也去掉）：
                # 带了它，ETag 和首次不同的节点会把整份内容重发一遍。接不接得上由 _prepare_recovery 核对。
                self._request_mode = "range"
                offset = self.response_start + self._received_bytes
                self._set_header(headers, "Range", f"bytes={offset}-{'' if self.response_end is None else self.response_end}")
                self._set_header(headers, "If-Range", None)
            elif self.status_code == 200:
                # 首次的 200 定义了完整响应（包括忽略调用方 Range 的），重放时不再带调用方的区间。
                self._set_header(headers, "Range", None)
                self._set_header(headers, "If-Range", None)
            elif not self.original_range_header and not self._multipart:
                self._set_header(headers, "Range", f"bytes={self.response_start}-{'' if self.response_end is None else self.response_end}")
        self._request_headers = HttpHeaders(headers)
        kwargs = self.kwargs.copy()
        kwargs["headers"] = headers
        return client.reconnect_stream(self.method, self.url, live_stream=self.live_stream, **kwargs)

    def incr_timeout(self, reset: bool = False) -> None:
        """更新父客户端记录的连续超时次数。"""

        if self.client:
            if reset:
                self.client.parent.timeout_count = 0
            else:
                self.client.parent.timeout_count += 1

    async def aiter_bytes(self, chunk_size: int = 512 * 1024) -> AsyncIterator[bytes]:
        """输出本次响应的连续字节；读取中断后按续传规则恢复。

        chunk_size 是每块的上限，不是下限：收到多少交多少，不为凑满它等待（curl 的短暂攒批见 _iter_response）。
        """

        if chunk_size <= 0:
            raise ValueError("chunk_size 必须为正整数")
        while True:
            if self.current_response is None:
                await self.connect()
                if self._complete:
                    # 续传的 416 证明字节已经收全：和正常读完一样走下面的收尾（解码器要核对压缩流有没有被截断）。
                    break
            response = self.current_response
            if response is None:
                raise RuntimeError("流响应尚未建立")
            try:
                async with aclosing(self._iter_response(response, chunk_size)) as chunks:
                    async for raw_chunk in chunks:
                        chunk = self._recover_chunk(raw_chunk) if self._finite else raw_chunk
                        if self._finite and self.content_length is not None:
                            remaining = self.content_length - self._received_bytes
                            if len(chunk) > remaining and not self._truncate_at_end:
                                raise HttpRangeError(f"正文超过本次响应的长度 {self.content_length} 字节: {self.url}")
                            chunk = chunk[:remaining]
                        if chunk:
                            # 交出新字节才算这次恢复成功：之后再断线，重试预算从头算。
                            self._reset_recovery_budget()
                            self._received_bytes += len(chunk)
                            output = chunk if self._decode_headers is None else self._decode(chunk)
                            if output:
                                self.transmitted_bytes += len(output)
                                if self._multipart:
                                    self._output_digest.update(output)
                                yield output
                        if self._truncate_at_end and self._received_bytes == self.content_length:
                            break
                # 该跳过的部分没读完、或已知长度不足，即使协议上正常结束，也不能当作读完。
                if self._read_offset < self._skip_until:
                    raise _ShortBody(
                        f"重新发来的内容在已交付的 {self._skip_until - self.response_start} 字节之前就结束了: {self.url}",
                        self._skip_until - self._read_offset,
                    )
                if self._finite and self.content_length is not None and self._received_bytes != self.content_length:
                    raise _ShortBody(
                        f"正文短于本次响应的长度 {self.content_length} 字节，只收到 {self._received_bytes} 字节: {self.url}",
                        self.content_length - self._received_bytes,
                    )
                if self.live_stream and self._ends_at_close and self.status_code in (200, 206):
                    # 声明的直播流，正文靠关连接结束：上游一关连接，看起来和"发完了"一模一样。直播没有"发完"，按中断去重连。
                    raise ConnectionError("直播流的上游关闭了连接（正文没有长度也不分块，结束和中断分不出来，按中断处理）")
            except _READ_ERRORS as error:
                complete = self._finite and self.content_length is not None and self._received_bytes == self.content_length
                if not complete:
                    if isinstance(error, TimeoutError | httpx.TimeoutException):
                        self.incr_timeout()
                    # 错误状态的正文、不按文件续传的响应（HEAD、POST……）不续传。
                    if self.status_code not in (200, 206) or (not self._finite and not self.live_stream) or not self._consume_retry():
                        if isinstance(error, _ShortBody):
                            raise HttpRangeError(error.message) from error
                        raise
                    logger.warning(f"流读取中断，尝试恢复: {type(error).__name__}, 已输出 {self.transmitted_bytes} 字节, [{self._log_url}]")
                    self._backoff_pending = True
                    await self.release_response()
                    continue
                # 本次响应的字节已经全部收下，出错的只是收尾（例如分块正文缺了结束块）：内容是完整的。
            break
        tail = self._finish_decoding()
        if tail:
            self.transmitted_bytes += len(tail)
            yield tail
        self.incr_timeout(True)

    async def _iter_response(self, response: HttpStreamResponse, chunk_size: int) -> AsyncGenerator[bytes, None]:
        """底层收到多少交多少，每块不超过 chunk_size。

        等凑满才交的话（中转用的 chunk_size 是 2MB），一个 1MB 的切片要整个下载完，播放器才收到第一个字节。
        curl 的块很小（上游有速率时常常只有一两 KB），一块一交会让多路限速流的中转多耗不少 CPU：
        队列里还有现成的块就一并带上；队列空了先等 _CURL_BATCH_WAIT（50 毫秒），这段时间到的也带上；这次传输
        在等待期间结束就立刻交。代价是每一批最多晚 50 毫秒。
        读取出错时，已经收到、还攒着的字节先交出去，再把错误抛出：不交的话续传要重新下载它们。
        """

        native = response.native_response
        queue = getattr(native, "queue", None) if isinstance(native, CurlResponse) else None
        transfer = getattr(native, "astream_task", None) if queue is not None else None
        parts: list[bytes] = []
        size = 0
        # 这一批已经等过一次了：每批只等一次，所以一批数据最多晚 _CURL_BATCH_WAIT。
        waited = False
        failure: Exception | None = None
        try:
            async with aclosing(response.aiter_raw()) as chunks:
                async for chunk in chunks:
                    parts.append(chunk)
                    size += len(chunk)
                    if queue is not None and size < chunk_size and not waited and queue.empty():
                        waited = True
                        if transfer is None:
                            await asyncio.sleep(_CURL_BATCH_WAIT)
                        else:
                            # 等够时间，或者这次传输结束（不取消它；它的错误会从队列里读到）。
                            await asyncio.wait({asyncio.ensure_future(transfer)}, timeout=_CURL_BATCH_WAIT)
                    if size >= chunk_size or queue is None or queue.empty():
                        data = b"".join(parts)
                        parts, size, waited = [], 0, False
                        for offset in range(0, len(data), chunk_size):
                            yield data[offset : offset + chunk_size]
        except Exception as error:
            failure = error
        if parts:
            data = b"".join(parts)
            for offset in range(0, len(data), chunk_size):
                yield data[offset : offset + chunk_size]
        if failure is not None:
            raise failure

    def _decode(self, chunk: bytes) -> bytes:
        """把实体字节喂给本次响应唯一的解码器；文件的内部续传换了连接也接着喂，输出才连续。"""

        if self._decoder is None:
            assert self._decode_headers is not None
            self._decoder = _content_decoder(self._decode_headers, True)
        try:
            return self._decoder.decode(chunk)
        except _DECODER_ERRORS as exc:
            raise HttpContentDecodingError(f"响应正文解码失败: {exc}") from exc

    def _finish_decoding(self) -> bytes:
        """正文读完时收尾解码；截断的压缩流在这里报错。"""

        if self._decode_headers is None:
            return b""
        if self._decoder is None:
            self._decoder = _content_decoder(self._decode_headers, True)
        try:
            return self._decoder.flush()
        except _DECODER_ERRORS as exc:
            raise HttpContentDecodingError(f"响应正文解码失败: {exc}") from exc

    async def release_response(self) -> None:
        """退出 backend 上下文，由统一流响应完成幂等关闭。"""

        context = self._response_context
        response = self.current_response
        self._response_context = None
        self.current_response = None
        try:
            if context is not None:
                await context.__aexit__(None, None, None)
            elif response is not None:
                await response.aclose()
        except Exception as e:
            logger.error(f"释放流响应时出错: {type(e).__name__}")

    def detach_response(self) -> AbstractAsyncContextManager[HttpStreamResponse] | None:
        """把当前这条底层响应的上下文交出去，由调用方负责退出它；之后 release 没有东西要等。

        给中转层在最终失败时用：它要立刻把异常抛给调用方，不能在处理请求的任务里等上游的响应放掉，
        于是把上下文拿走、放到后台去退出。没有打开的响应时返回 None。
        """

        context = self._response_context
        self._response_context = None
        self.current_response = None
        return context

    async def release(self) -> None:
        """清理当前断点续传响应。"""

        try:
            await self.release_response()
        finally:
            self.client = None  # type: ignore[assignment] -- release 后对象与来源实现一样不可复用

    def update_response_status(self, response: HttpStreamResponse) -> None:
        """首次响应确定对外状态、响应头和续传方式；之后的响应只核对能不能接上，不改对外的东西。"""

        status = response.status_code
        headers = response.headers
        # HTTP/2、HTTP/3 的流有明确的结束标记，没有长度也不靠关连接结束；HEAD 没有正文。
        self._ends_at_close = (
            response.http_version.upper().startswith("HTTP/1")
            and self.method != HttpMethod.HEAD
            and "content-length" not in headers
            and "chunked" not in headers.get("transfer-encoding", "").lower()
        )
        if not self.range_tested:
            self.status_code = status
            self.response_headers = headers.copy()
            self._initial_headers = headers
            self._finite = not self.live_stream and self.method == HttpMethod.GET and status in (200, 206)
            self._multipart = status == 206 and headers.get("content-type", "").lower().startswith("multipart/byteranges")
            self.supports_range = not self.live_stream and headers.get("accept-ranges", "").strip().lower() != "none"
            if status == 416 or self._range_refused or (status == 200 and self.original_range_header):
                self.supports_range = False
            # 200 忽略调用方 Range 时从零开始；206 的起点（包括后缀区间）由 Content-Range 给出。
            self.response_start = 0
            if self._finite:
                try:
                    if status == 206 and not self._multipart:
                        # Content-Range 决定这一段的长度；Content-Length 与它不一致时以它为准：正文短了续传，长了报错。
                        self.response_start, self.response_end, self.total_length = self._range(headers)
                        self.content_length = self.response_end - self.response_start + 1
                    else:
                        self.content_length = self._length(headers)
                        if self.content_length is not None:
                            self.response_end = self.content_length - 1
                            self.total_length = self.content_length if status == 200 else None
                except HttpRangeError as error:
                    if status == 206 and self.original_range_header:
                        # 调用方要的区间，必须由有效的 Content-Range 证明拿到的正是它。
                        raise
                    # 没人要求的 206、或长度不合规范的 200：照常读完，只是不做内部续传，读取中断就直接失败。
                    logger.warning(f"首个响应的长度或范围无法解析，照常读取但不做内部续传: {error}, [{self._log_url}]")
                    self._finite = False
                    self.supports_range = False
                    self.response_start, self.response_end, self.content_length, self.total_length = 0, None, None, None
                else:
                    if status == 206 and not self._multipart and self.original_range_header:
                        self._check_requested_range()
                etag = headers.get("etag", "").strip()
                if etag.startswith('"') and etag.endswith('"'):
                    self._strong_etag = etag
            self._decode_headers = self._decodable(status, headers)
            if self._decode_headers is not None:
                # 输出的是解压后的内容：对外响应头不能再声明压缩方式和压缩后的长度（中转时它们会原样发给下游）。
                self.response_headers = HttpHeaders(
                    [(name, value) for name, value in headers.multi_items() if name not in ("content-encoding", "content-length")]
                )
            self.range_tested = True
            self._read_offset = self.response_start
            self._skip_until = self.response_start
            return
        if self.live_stream:
            if not response.is_success:
                raise HttpStatusError(response)
            # 直播重连是一条新的流，压缩流也从头开始。
            self._decode_headers = self._decodable(status, headers)
            self._decoder = None
            return
        self._prepare_recovery(response)

    def _decodable(self, status: int, headers: HttpHeaders) -> HttpHeaders | None:
        """这个响应由这里解压时返回决定解码器的响应头，否则返回 None（按原始字节输出，响应头不动）。

        206 是压缩流里的一段（Range 按压缩后的字节计），解不开，由发 Range 的一方自己处理。
        """

        client = self.client
        if client is None or not client.parent.content_decoding or self.method == HttpMethod.HEAD:
            return None
        if all(encoding == "identity" for encoding in _content_encodings(headers)):
            return None
        try:
            _content_decoder(headers, True)
        except HttpContentDecodingError:
            unsupported = True
        else:
            unsupported = False
        if status == 206 or unsupported:
            logger.warning(
                f"响应无法解压，按原始字节输出并保留 Content-Encoding: status={status}, "
                f"content-encoding={headers.get('content-encoding')!r}, [{self._log_url}]"
            )
            return None
        return headers

    @staticmethod
    def _set_header(headers: dict[str, str], name: str, value: str | None) -> None:
        """不分大小写地替换或删除一个请求头。"""

        for key in list(headers):
            if key.lower() == name.lower():
                del headers[key]
        if value is not None:
            headers[name] = value

    @staticmethod
    def _length(headers: HttpHeaders) -> int | None:
        """解析 Content-Length；同一个值重复出现（多个头合并成逗号分隔）按一个处理（RFC 9110 8.6）。"""

        value = headers.get("content-length")
        if value is None:
            return None
        values = {item.strip() for item in value.split(",")}
        digits = values.pop()
        if values or not digits.isascii() or not digits.isdigit():
            raise HttpRangeError(f"无效 Content-Length: {value!r}")
        return int(digits)

    @staticmethod
    def _range(headers: HttpHeaders) -> tuple[int, int, int | None]:
        """解析单区间 206 的实际范围，不根据调用方的 Range 猜测响应起点。"""

        value = headers.get("content-range", "")
        match = _CONTENT_RANGE_PATTERN.fullmatch(value.strip())
        if match is None:
            raise HttpRangeError(f"无效 Content-Range: {value!r}")
        start, end = int(match[1]), int(match[2])
        total = int(match[3]) if match[3] != "*" else None
        if end < start or (total is not None and end >= total):
            raise HttpRangeError(f"无效 Content-Range: {value!r}")
        return start, end, total

    def _check_requested_range(self) -> None:
        """首次的 206 必须从调用方要的起点开始，并落在要的区间之内；后缀区间的起点是资源最后 n 个字节的开头。

        服务器可以只给要的一部分（RFC 9110 14.2，例如 CDN 对 bytes=0- 只回前 1MB），这个 206 本身说清了给的是哪一段，
        原样交给调用方，内部续传也只在这一段之内。起点不对、或超出要的区间，才不是调用方要的。认不出的 Range（多区间等）不核对。
        """

        match = re.fullmatch(r"bytes=(\d*)-(\d*)", (self.original_range_header or "").strip(), re.IGNORECASE)
        if match is None or (not match[1] and not match[2]):
            return
        total = self.total_length
        last_allowed: int | None
        if match[1]:
            expected_start = int(match[1])
            last_allowed = int(match[2]) if match[2] else None
        else:
            if total is None:
                raise HttpRangeError(f"后缀 Range 的响应缺少资源总长度，无法核对范围: {self.url}")
            expected_start, last_allowed = max(total - int(match[2]), 0), None
        if self.response_start != expected_start or (last_allowed is not None and self.response_end is not None and self.response_end > last_allowed):
            raise HttpRangeError(
                f"206 的范围不是请求的 Range 的一部分: 请求 {self.original_range_header}, 实际 {self.response_start}-{self.response_end}, {self.url}"
            )

    @staticmethod
    def _content_type(value: str) -> tuple[str, dict[str, Any]]:
        """媒体类型和参数：类型、参数名和 charset 不分大小写，boundary 等参数值区分。"""

        if not value:
            return "", {}
        message = Message()
        message["Content-Type"] = value
        parameters = {
            name.lower(): param.lower() if name.lower() == "charset" and isinstance(param, str) else param
            for name, param in (message.get_params() or [])[1:]
        }
        return message.get_content_type(), parameters

    def _prepare_recovery(self, response: HttpStreamResponse) -> None:
        """核对恢复连接上的响应还能接上原响应，并确定这条连接要跳过多少已交出的部分。"""

        status = response.status_code
        headers = response.headers
        initial = self._initial_headers
        if status == 416 and self._finite and self._request_mode == "range" and self.content_length is None:
            # 没有长度的响应，字节其实已经全部收下，只是没等到结束标记连接就断了：续传的起点正好是资源总长度，
            # 上游只能回 416，Content-Range: bytes */N 的 N 等于已经收到的位置，说明内容是完整的。
            unsatisfied = _UNSATISFIED_RANGE_PATTERN.fullmatch(headers.get("content-range", "").strip())
            if unsatisfied is not None and int(unsatisfied[1]) == self.response_start + self._received_bytes:
                self._complete = True
                return
        if status not in (200, 206):
            raise HttpStatusError(response)
        if initial is None or not self._finite:
            raise HttpRangeError(f"无法恢复本次响应: status={status}, {self.url}")
        # 压缩方式变了，字节位置就对不上了。只有回应 If-Range 的 206 可以省略已有的表示元数据（RFC 9110 15.3.7；
        # 内部续传不带 If-Range，只有重放调用方自己带 If-Range 的请求时才是这种情况）。
        answers_if_range = status == 206 and "if-range" in self._request_headers
        initial_encoding = initial.get("content-encoding", "identity").strip().lower() or "identity"
        encoding = headers.get("content-encoding", initial_encoding if answers_if_range else "identity").strip().lower() or "identity"
        if encoding != initial_encoding:
            raise HttpRangeError(f"续传响应的 Content-Encoding 发生变化，期望 {initial_encoding}，实际 {encoding}: {self.url}")
        length = self._length(headers)
        offset = self.response_start + self._received_bytes
        self._truncate_at_end = False
        if self._multipart:
            # multipart 的正文偏移不是文件偏移：只重放原请求，边界（写在 Content-Type 里）和长度都要相同，
            # 而且重放的开头与已交出的字节逐一相同（读取时核对，见 _recover_chunk）。
            same_framing = self._content_type(headers.get("content-type", initial.get("content-type", ""))) == self._content_type(
                initial.get("content-type", "")
            )
            if status != 206 or not same_framing or (length is not None and self.content_length is not None and length != self.content_length):
                raise HttpRangeError(f"multipart 重放改变了原始响应: {self.url}")
            start = 0
            self._replayed_digest = sha256()
        elif status == 206:
            start, end, total = self._range(headers)
            # 内部 Range 应从剩下的位置开始；重放原请求应仍从原响应的起点开始。
            expected_start = offset if self._request_mode == "range" else self.response_start
            if start != expected_start or (self.response_end is not None and end != self.response_end):
                raise HttpRangeError(
                    f"续传范围不匹配: 请求 {self._request_headers.get('range')}, 实际 {headers.get('content-range')}, 期望起点 {expected_start}: {self.url}"
                )
            if self.total_length is not None and total != self.total_length:
                raise HttpRangeError(f"续传响应的资源总长度发生变化，期望 {self.total_length}，实际 {total}: {self.url}")
            if self.response_end is None:
                # 原响应的终点未知（没有 Content-Length）：只有这一段明确到了资源结尾才算读完；总长度是 * 时无从确认。
                if total is None or end != total - 1:
                    raise HttpRangeError(f"续传响应无法确认覆盖了原响应的剩余范围: {headers.get('content-range')}, {self.url}")
                self.response_end = end
                self.content_length = end - self.response_start + 1
                self.total_length = total
        else:
            # 上游忽略内部 Range 返回完整 200，也不能把整个正文直接追加。
            start = 0
            if length is not None and self.total_length is not None and length != self.total_length:
                raise HttpRangeError(f"完整重取的资源总长度发生变化，期望 {self.total_length}，实际 {length}: {self.url}")
            if length is not None and self.response_end is not None and length <= self.response_end:
                raise HttpRangeError(f"完整重取没有覆盖原响应的范围: {self.url}")
            # 原响应是 206 时只输出它的区间，不能把完整 200 的后续部分发给调用方。
            self._truncate_at_end = self.status_code == 206 and self.response_end is not None
            if self._request_mode == "range":
                self.supports_range = False
        # 例：原区间 1000-1999 已输出 300 字节，完整 200 重取时从 0 读到 1300，0-1299 全部跳过，之后才继续输出。
        # 1000-1299 不逐字节核对，只要有一样对得上就认定是同一份：完整内容的长度和原来的总长度相同（上面已核对），
        # 或者没有长度可比、但强 ETag 和首次相同。两样都没有就无从确认，明确失败。
        if status == 200 and offset > self.response_start:
            same_length = length is not None and self.total_length is not None
            same_etag = self._strong_etag is not None and headers.get("etag", "").strip() == self._strong_etag
            if not same_length and not same_etag:
                raise HttpRangeError(f"上游重新发送了已输出的内容，但长度无从比对、也没有相同的强 ETag，无法确认是同一份内容: {self.url}")
        self._read_offset = start
        self._skip_until = offset

    def _recover_chunk(self, chunk: bytes) -> bytes:
        """跳过恢复连接上已交出过的部分，只返回还没交给调用方的字节。"""

        if self._read_offset >= self._skip_until:
            return chunk
        skipped = min(len(chunk), self._skip_until - self._read_offset)
        if self._multipart:
            # multipart 正文每次临时拼出，按字节数跳过会拼出错误的内容：重放的这一段必须和已交出的字节完全相同。
            # 校验通过才推进位置，失败后不会因为位置越过了这一段而绕过检查。
            self._replayed_digest.update(chunk[:skipped])
            if self._read_offset + skipped >= self._skip_until and self._replayed_digest.digest() != self._output_digest.digest():
                raise HttpRangeError(f"multipart 重放的已输出部分发生变化，无法安全续传: {self.url}")
        self._read_offset += len(chunk)
        return chunk[skipped:]
