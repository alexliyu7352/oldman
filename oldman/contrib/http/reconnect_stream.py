"""
@author:alex
@date:2025/8/10
@time:13:52
"""

__author__ = "alex"
import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, aclosing
from typing import Any, Protocol

from oldman.contrib.http.contants import StreamReadError
from oldman.contrib.http.exceptions import HttpRangeError, HttpStatusError
from oldman.contrib.http.response import HttpHeaders, HttpStreamResponse
from oldman.contrib.http.schemas import HttpMethod
from oldman.logging import logger

from ._logging import redact_url

_CONTENT_RANGE_PATTERN = re.compile(r"^bytes\s+(\d+)-(\d+)/(\d+|\*)$", re.IGNORECASE)


class _HttpClientParent(Protocol):
    """断点续传所需的 MultiHttpClient 最小配置接口。"""

    retry_count: int
    retry_backoff_factor: float
    no_retry_statuses: list[int]
    timeout_count: int
    proxy_url: str | None


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
    """
    一个通用的流式响应包装类，用于在需要时重新连接流式请求。由于上层业务是流式输出, 所以需要先建立连接并记录response头, 然后读取数据.
    上层业务系统需要先返回header, 然后才能迭代数据, 所以这个类中不能直接使用底层客户端的上下文处理器, 必须显式获取底层的响应对象.
    """

    def __init__(
        self,
        client: _ReconnectClient,
        method: HttpMethod,
        url: str,
        live_stream: bool = False,
        **kwargs,
    ) -> None:
        """保存原始请求和续传边界，网络连接仍延迟到 ``connect``。"""

        self.client: _ReconnectClient = client
        self.method = method
        self.url = url
        self._log_url = redact_url(url)
        self.kwargs = kwargs

        self.transmitted_bytes = 0
        self.retries_left = kwargs.pop("retries", client.parent.retry_count)
        self.retry_backoff = kwargs.pop("retry_backoff", client.parent.retry_backoff_factor)
        self.no_retry_statuses = kwargs.pop("no_retry_statuses", client.parent.no_retry_statuses)
        self.status_code: int | None = None  # 用于跟踪当前响应的状态码
        self.response_headers = HttpHeaders()
        self.supports_range = True  # 默认假设服务器支持断点续传
        self.content_length = 0  # 记录文件总大小
        self.range_tested = False  # 是否已经测试过服务器对Range的支持
        self.live_stream = live_stream  # 是否为实时流式请求
        self.current_response: HttpStreamResponse | None = None
        self._response_context: AbstractAsyncContextManager[HttpStreamResponse] | None = None

        # 保存原始Range头
        self.headers = kwargs.get("headers", {}).copy()
        self._range_header_name = next((name for name in self.headers if name.lower() == "range"), "Range")
        self.original_range_header = self.headers.get(self._range_header_name)
        self._initial_range_start: int | None = 0
        self._initial_range_end: int | None = None
        self._initial_suffix_length: int | None = None
        self._range_total: int | None = None
        self._range_resumable = True
        self._is_resume_request = False
        self._requested_range_start: int | None = None
        self._requested_range_end: int | None = None
        self._expected_response_bytes: int | None = None
        self._received_response_bytes = 0
        self._strong_etag: str | None = None
        self._if_range_header_name = next((name for name in self.headers if name.lower() == "if-range"), "If-Range")
        self._retries_remaining = self.retries_left
        self._recovery_attempt = 0
        if live_stream:
            # 如果是实时流式请求，设置为不支持Range
            self.supports_range = False
            self.original_range_header = None
            self.range_tested = False
            self.headers.pop(self._range_header_name, None)
            self.headers.pop(self._if_range_header_name, None)
        else:
            # 非实时流式请求，检查是否有Range头
            self._parse_initial_range()

    def _parse_initial_range(self) -> None:
        """Parse one initial byte range without changing the caller's first request."""

        if not self.original_range_header:
            return
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", self.original_range_header.strip(), re.IGNORECASE)
        if match is None or (not match.group(1) and not match.group(2)):
            self._range_resumable = False
            logger.warning(f"断点续传只支持单一字节区间: {self.original_range_header}")
            return

        start_text, end_text = match.groups()
        if start_text:
            self._initial_range_start = int(start_text)
            self._initial_range_end = int(end_text) if end_text else None
            if self._initial_range_end is not None and self._initial_range_end < self._initial_range_start:
                self._range_resumable = False
                logger.warning(f"Range 结束位置小于开始位置: {self.original_range_header}")
        else:
            # suffix range 的绝对起点只能从第一次 206 的 Content-Range 得到。
            self._initial_range_start = None
            self._initial_suffix_length = int(end_text)
            if self._initial_suffix_length <= 0:
                self._range_resumable = False
                logger.warning(f"suffix Range 长度必须为正整数: {self.original_range_header}")

    async def connect(self) -> None:
        """建立初始响应，并让连接失败和状态重试共享一个预算。"""

        self._reset_recovery_budget()
        while True:
            try:
                await self._open_response_once()
                response = self.current_response
                if response is None:
                    raise RuntimeError("流响应尚未建立")
                if response.is_success or response.status_code in self.no_retry_statuses:
                    self.incr_timeout(True)
                    return
                if not self._consume_retry():
                    # 初始请求尚未交付正文，最终错误响应仍交给调用方检查。
                    self.incr_timeout(True)
                    return
                logger.warning(f"流式连接收到状态码 {response.status_code}，将重试: {self._log_url}")
                await self.release_response()
                await self._wait_before_retry()
            except HttpRangeError:
                await self.release_response()
                raise
            except TimeoutError:
                self.incr_timeout()
                await self.release_response()
                if not self._consume_retry():
                    raise
                logger.warning(f"流式请求超时，尝试重新连接: [{self._log_url}]")
                await self._wait_before_retry()
            except Exception as exc:
                await self.release_response()
                if not self._consume_retry():
                    raise
                logger.warning(f"流式连接错误，尝试重新连接: {type(exc).__name__}, [{self._log_url}]")
                await self._wait_before_retry()

    async def _open_response_once(self) -> None:
        """只建立一次 backend 响应，不在本方法内部增加重试。"""

        if self.current_response is not None or self._response_context is not None:
            await self.release_response()
        context_manager = await self._get_stream_response()
        response = await context_manager.__aenter__()
        self._response_context = context_manager
        self.current_response = response
        try:
            self.update_response_status(response)
        except BaseException:
            await self.release_response()
            raise

    def _reset_recovery_budget(self) -> None:
        """在新响应真正交付正文后恢复完整的断线重试预算。"""

        self._retries_remaining = self.retries_left
        self._recovery_attempt = 0

    def _consume_retry(self) -> bool:
        """消费一次连续恢复预算。"""

        if self._retries_remaining <= 0:
            return False
        self._retries_remaining -= 1
        self._recovery_attempt += 1
        return True

    async def _wait_before_retry(self) -> None:
        """在已经释放失败响应后执行一次指数退避。"""

        wait_time = self.retry_backoff * (2 ** (self._recovery_attempt - 1))
        if wait_time > 0:
            await asyncio.sleep(wait_time)

    async def _prepare_retry(self) -> bool:
        """消费一次重试预算，并在下一次网络尝试前完成退避。"""

        if not self._consume_retry():
            return False
        await self._wait_before_retry()
        return True

    async def _get_stream_response(
        self,
    ) -> AbstractAsyncContextManager[HttpStreamResponse]:
        """获取流对象，处理断点续传逻辑"""
        # 准备当前请求的headers
        current_headers = self.headers.copy()
        # 直播断线后重新建立当前直播流，不属于字节区间续传。
        self._is_resume_request = not self.live_stream and self.transmitted_bytes > 0
        self._requested_range_start = None
        self._requested_range_end = None

        if self._is_resume_request:
            if not self.supports_range:
                raise HttpRangeError(f"上游不支持 Range，无法从 {self.transmitted_bytes} 字节处续传: {self.url}")
            if not self._range_resumable or self._initial_range_start is None:
                raise HttpRangeError(f"原始 Range 无法安全换算续传位置: {self.original_range_header}")

            start = self._initial_range_start + self.transmitted_bytes
            end = self._initial_range_end
            if end is not None and start > end:
                raise HttpRangeError(f"续传位置 {start} 已超过原始 Range 结束位置 {end}: {self.url}")

            range_value = f"bytes={start}-{'' if end is None else end}"
            current_headers[self._range_header_name] = range_value
            if self._strong_etag is not None:
                current_headers[self._if_range_header_name] = self._strong_etag
            self._requested_range_start = start
            self._requested_range_end = end
        elif self.original_range_header and self._range_resumable:
            self._requested_range_start = self._initial_range_start
            self._requested_range_end = self._initial_range_end

        # 更新请求参数中的headers
        kwargs = self.kwargs.copy()
        kwargs["headers"] = current_headers

        return self.client.reconnect_stream(
            self.method,
            self.url,
            live_stream=self.live_stream,
            **kwargs,
        )

    def incr_timeout(self, reset: bool = False) -> None:
        """更新父客户端记录的连续超时次数。"""

        if self.client:
            if reset:
                # 重置超时计数
                self.client.parent.timeout_count = 0
            else:
                self.client.parent.timeout_count += 1

    async def aiter_bytes(self, chunk_size: int = 512 * 1024) -> AsyncIterator[bytes]:
        """迭代正文，并用一个连续预算处理读取失败和后续重连。"""

        if self.current_response is None:
            await self.connect()

        last_exception: BaseException | None = None
        while True:
            response = self.current_response
            if response is None:
                try:
                    await self._open_response_once()
                except HttpRangeError:
                    raise
                except TimeoutError as exc:
                    last_exception = exc
                    self.incr_timeout()
                    if not await self._prepare_retry():
                        raise
                    continue
                except Exception as exc:
                    last_exception = exc
                    if not await self._prepare_retry():
                        raise
                    continue
                response = self.current_response
                if response is None:
                    raise RuntimeError("流响应尚未建立")

            # 初始错误响应尚未污染任何实体，可以由调用方显式读取；已经交付正文后则禁止拼接。
            if self.transmitted_bytes > 0 and not response.is_success:
                status_error = HttpStatusError(response)
                await self.release_response()
                if response.status_code in self.no_retry_statuses or not await self._prepare_retry():
                    raise status_error
                logger.warning(f"流式重连收到状态码 {response.status_code}，继续重试: [{self._log_url}]")
                continue

            delivered_from_response = False
            try:
                response_error: HttpRangeError | None = None
                # 提前 break 时显式关闭正文迭代器，不把挂起的生成器留给 GC 终结钩子。
                async with aclosing(response.aiter_raw(chunk_size)) as body:
                    async for chunk in body:
                        expected = self._expected_response_bytes
                        if expected is not None and self._received_response_bytes + len(chunk) > expected:
                            response_error = HttpRangeError(
                                f"206 正文超过 Content-Range 声明长度，期望 {expected} 字节: {self.url}"
                            )
                            break
                        self._received_response_bytes += len(chunk)
                        self.transmitted_bytes += len(chunk)
                        if not delivered_from_response:
                            # 取得新实体字节才代表本次恢复成功，后续再次断线获得完整预算。
                            delivered_from_response = True
                            self._reset_recovery_budget()
                        yield chunk
                if response_error is not None:
                    last_exception = response_error
                    break
                expected = self._expected_response_bytes
                if expected is not None and self._received_response_bytes != expected:
                    last_exception = HttpRangeError(
                        f"206 正文短于 Content-Range 声明长度，期望 {expected} 字节，"
                        f"实际 {self._received_response_bytes} 字节: {self.url}"
                    )
                    logger.warning(f"Range 正文提前结束，尝试从已交付位置续传: [{self._log_url}]")
                    await self.release_response()
                    if not await self._prepare_retry():
                        break
                    continue
                self.incr_timeout(True)
                return  # 正常完成
            except StreamReadError as e:
                last_exception = e
                if not self.supports_range and self.transmitted_bytes > 0 and not self.live_stream:
                    # 没必要进行重试了, 直接退出
                    logger.error(
                        f"流式请求读取错误且不支持断点续传，无法继续: "
                        f"{type(e).__name__}, [{self._log_url}]"
                    )
                    break
                else:
                    logger.warning(f"流读取中断，尝试续传: [{self._log_url}]")
                    await self.release_response()
                    if not await self._prepare_retry():
                        break
            except TimeoutError as e:
                self.incr_timeout()
                last_exception = e
                if not self.supports_range and self.transmitted_bytes > 0 and not self.live_stream:
                    # 没必要进行重试了, 直接退出
                    logger.error(
                        f"流式请求读取错误且不支持断点续传，无法继续: "
                        f"{type(e).__name__}, [{self._log_url}]"
                    )
                    break
                else:
                    logger.warning(f"流式请求超时，尝试续传: [{self._log_url}]")
                    await self.release_response()
                    if not await self._prepare_retry():
                        break
            except StopAsyncIteration:
                break
            except Exception as e:
                logger.error(f"流式请求错误: {type(e).__name__}, url is {self._log_url}")
                last_exception = e
                break

        if last_exception:
            raise last_exception
        raise Exception(f"流式请求失败，已重试 {self.retries_left} 次, [{self.url}]")

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

    async def release(self) -> None:
        """清理当前断点续传响应。"""

        await self.release_response()
        self.client = None  # type: ignore[assignment] -- release 后对象与来源实现一样不可复用

    @staticmethod
    def _parse_content_range(value: str) -> tuple[int, int, int | None] | None:
        """Parse a single byte Content-Range response header."""

        match = _CONTENT_RANGE_PATTERN.fullmatch(value.strip())
        if match is None:
            return None
        start, end, total = match.groups()
        parsed_start = int(start)
        parsed_end = int(end)
        parsed_total = None if total == "*" else int(total)
        if parsed_end < parsed_start:
            return None
        if parsed_total is not None and (parsed_total <= 0 or parsed_end >= parsed_total):
            return None
        return parsed_start, parsed_end, parsed_total

    def _validate_partial_response(self, *, require_partial: bool) -> None:
        """Validate the range actually sent for an initial or resumed response."""

        if self.status_code != 206:
            if require_partial:
                raise HttpRangeError(
                    f"续传请求要求 206，但上游返回 {self.status_code}: Range={self._requested_range_start}-{self._requested_range_end}, {self.url}"
                )
            return

        content_range = self._parse_content_range(self.response_headers.get("content-range", ""))
        if content_range is None:
            raise HttpRangeError(f"206 响应缺少有效 Content-Range: {self.url}")
        start, end, total = content_range

        if self._range_total is not None and total != self._range_total:
            raise HttpRangeError(f"Content-Range 总长度不匹配，期望 {self._range_total}，实际 {total}: {self.url}")
        if self._range_total is None and total is not None:
            self._range_total = total

        suffix_length = self._initial_suffix_length
        if suffix_length is not None and self._initial_range_start is None:
            if total is None:
                raise HttpRangeError(f"suffix Range 缺少资源总长度，无法验证范围: {self.url}")
            expected_start = max(total - suffix_length, 0)
            if start != expected_start or end != total - 1:
                raise HttpRangeError(
                    f"suffix Content-Range 不匹配，期望 {expected_start}-{total - 1}，实际 {start}-{end}: {self.url}"
                )

        requested_start = self._requested_range_start
        if requested_start is not None and start != requested_start:
            raise HttpRangeError(f"Content-Range 起点不匹配，期望 {requested_start}，实际 {start}: {self.url}")
        if self._initial_range_start is None:
            self._initial_range_start = start

        requested_end = self._requested_range_end
        if requested_end is not None:
            expected_end = min(requested_end, total - 1) if total is not None else requested_end
            if end != expected_end:
                raise HttpRangeError(f"Content-Range 终点不匹配，期望 {expected_end}，实际 {end}: {self.url}")
        elif total is not None and end != total - 1:
            raise HttpRangeError(f"开放 Range 没有返回到资源结尾，期望 {total - 1}，实际 {end}: {self.url}")
        self._expected_response_bytes = end - start + 1

    def _adopt_unsolicited_partial_response(self) -> None:
        """Adopt a valid unsolicited 206 interval without inventing missing bytes."""

        content_type = self.response_headers.get("content-type", "")
        if content_type.partition(";")[0].strip().lower() == "multipart/byteranges":
            self.supports_range = False
            self._range_resumable = False
            logger.warning(f"初始 multipart 206 当前正文可读，但无法换算单一区间续传: {self._log_url}")
            return

        content_range = self._parse_content_range(self.response_headers.get("content-range", ""))
        if content_range is None:
            # 常见客户端会把这种非标准 206 正文交给调用方；只有后续断线时才因无安全偏移而失败。
            self.supports_range = False
            self._range_resumable = False
            logger.warning(f"初始 206 缺少有效 Content-Range，当前正文可读但不可续传: {self._log_url}")
            return

        start, end, total = content_range
        self._initial_range_start = start
        self._initial_range_end = end
        self._range_total = total
        self._expected_response_bytes = end - start + 1

    def update_response_status(self, response: HttpStreamResponse) -> None:
        """Update response metadata and reject unsafe resume responses."""

        self.status_code = response.status_code
        self.response_headers = response.headers.copy()
        self.range_tested = True
        self._expected_response_bytes = None
        self._received_response_bytes = 0

        # 直播重连只建立新的当前流，不执行任何 Range 或实体校验。
        if self.live_stream:
            return

        # 错误响应只参与状态重试，不能按续传实体执行 Range/ETag 校验。
        if not response.is_success:
            return

        # 只有可交付的实体响应才有资格建立或校验续传 validator；错误页的 ETag 必须忽略。
        if self.status_code in {200, 206}:
            etag = self.response_headers.get("etag")
            normalized_etag = etag.strip() if etag is not None else None
            if self._is_resume_request:
                if self._strong_etag is not None and normalized_etag is not None and normalized_etag != self._strong_etag:
                    raise HttpRangeError(f"续传响应 ETag 已变化，期望 {self._strong_etag}，实际 {normalized_etag}: {self.url}")
            elif normalized_etag is not None:
                # If-Range 只使用语法有效的强实体标签；弱标签不能证明两段正文属于同一表示。
                if normalized_etag.startswith('"') and normalized_etag.endswith('"'):
                    self._strong_etag = normalized_etag

        if self._is_resume_request:
            self._validate_partial_response(require_partial=True)
            return

        if self.status_code == 200:
            content_length = self.response_headers.get("content-length")
            if content_length:
                try:
                    parsed_length = int(content_length)
                except ValueError:
                    parsed_length = -1
                if parsed_length >= 0:
                    # 200 的 Content-Length 是后续 Content-Range 总长度的已知基线。
                    self._range_total = parsed_length

        accept_ranges = self.response_headers.get("accept-ranges", "")
        if accept_ranges.lower() == "none":
            self.supports_range = False
            logger.warning(f"服务器明确不支持断点续传: {self._log_url}")

        if self.original_range_header:
            if self.status_code == 206:
                self._validate_partial_response(require_partial=False)
            elif self.status_code == 200:
                # 初次请求可以接受服务器忽略 Range，但之后不能把完整正文用于续传拼接。
                self.supports_range = False
                logger.warning(f"服务器忽略初始 Range 并返回完整内容: {self._log_url}")
        elif self.status_code == 206:
            self._adopt_unsolicited_partial_response()
        if self.status_code == 416:
            self.supports_range = False
            logger.warning(f"服务器不接受请求的范围: {self._log_url}")
