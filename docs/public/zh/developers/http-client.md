# 后端 HTTP 客户端

`oldman.contrib.http.MultiHttpClient` 用于 Python 服务主动请求其他 HTTP 服务。它不是 Sanic 的入站请求处理，也不解释浏览器 DefaultApiResponse.actions。业务选择一个 backend，但读取统一的 HttpResponse/HttpStreamResponse。

## Demo 中的实际使用

页面 `/examples/http/client` 提供 JSON、上游 404、超时和字节流四个按钮，操作顺序见[用户教程](../users/cache-and-http.md#运行后端-http-示例)。下面完整引用 Demo 的 [http_example.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/http_example.py)：

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

`app` 来自该 Demo 的 [apps/examples/apps.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/apps.py)，在服务 bootstrap 时绑定 [ExamplesSettings](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/settings.py)。调用前必须完成该服务初始化，不能在未初始化的 Shell 中偷用默认 App 配置。HTTPResult 是本例送给 Jinja 的诊断数据，不是框架新响应协议。

这里的 operation 由 [views/http.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/http.py) 校验为固定白名单；不会把浏览器传入的 URL、Cookie 或用户数据转发到上游。JSON 中的 HTML 字符串在结果模板里作为文本显示；不执行上游 HTML。已知网络/解析错误会变成明确诊断，真正的程序异常和取消仍抛出。

## 创建、初始化、关闭

上面模块持有的 http_client 是 **Demo 创建的实例**，不是框架提供的全局单例。[services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py) 同文件导入 `from apps.examples.http_example import http_client`，由 WebService 的两个完整方法负责它：

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

这些是类内方法，不是模块级 listener；WebApp 来自 oldman.web.routing，父类为 WebApplication。缓存、Redis 和数据库由框架在 after_server_stop 之后关闭，HTTP 客户端关闭失败也不影响那一步；这里调用的 super 不做事，留着无害。

构造后须 await init_client 才能调用请求；init_client 幂等，HTTPX 实际连接仍在首次请求时建立。当前 MultiHttpClient 不是 async with 上下文管理器。不要发明 `await response.json()` 用在普通缓冲响应上。

高频调用由服务或业务客户端持有一个实例，不为每个请求重建池；独立短命令在自己的异步调用中 init_client，并用 try/finally 关闭。Application 不会自动替应用关闭自行创建的客户端。内置 atexit 只作兜底，不能代替同一事件循环中的显式关闭。

可用 ClientType.HTTPX、AIOHTTP、CURL_CFFI。公共响应合同相同，不表示所有 backend 私有参数、TLS 指纹、DNS 或 Cookie 实现都完全相同；应用正常路径不通过 native_response 调 backend 私有 API。

## 配置和参数

全局 http_client 只有 max_connections 和 user_agent；Demo 用上面客户端构造的显式值覆盖它们，不需要把业务 URL 塞入这个节点。Demo 的公开 YAML 实际配置节选为：

```yaml
app_settings:
  examples:
    http_base_url: https://httpbin.org
```

这段合入已有配置，不覆盖其他 App 设置。ExamplesSettings 接受 HTTP(S) 基地址及可选路径前缀，拒绝凭据、query 和 fragment；不存在浏览器提交任意 URL 的入口。读取必须通过 Examples App 的 app.settings，而不是 settings.examples。首次默认公共上游，已有配置可用 settings sync 补字段，也可由部署者改为自己的兼容实例。

未 bootstrap 的独立脚本构造 MultiHttpClient 时使用框架 schema 默认值；不是要求为一次 HTTP 请求启动 Web。但本例函数另外读取 App Settings，不能省略其服务 bootstrap。构造 max_connections=0 表示取 Settings 默认值（300），显式正数覆盖；user_agent=None 同样取配置，schema 默认值为 okhttp/3.8.7。

其他构造参数为 connect_timeout=10、read_timeout=30、proxy_url=None、retry_count=3、retry_backoff_factor=0.5、no_retry_statuses=None、keepalive_expiry=300、content_decoding=False、nameservers=None、cookie_jar=None、verify=True。nameservers 当前由 aiohttp backend 消费，不能假定 HTTPX/curl 同样使用自定义解析器。

TLS verify 仅接受构造级 bool，默认验证服务端证书。单次请求传 verify 会在发请求前被拒绝；不能把业务环境证书错误以全局 verify=False 静默处理。代理、CA、凭据等部署行为还须在实际 backend 和部署环境验证。

调用方式：

- get/post/put/delete(url, **kwargs) 是便捷方法。
- PATCH/HEAD/OPTIONS 等用 `request(HttpMethod.PATCH, url, ...)`。
- 常用 kwargs：headers、params、data、json、cookies、timeout、follow_redirects。
- 数字 timeout 由各 backend 转成对应超时对象，细分语义不完全相同。要限制整个重试链的总时长，在外层使用 asyncio.timeout。
- 默认跟随重定向；只接受指定接口时可设 follow_redirects=False，并检查 3xx。框架没有自动 SSRF 地址白名单，不将任意浏览器输入直接转成后端抓取 URL。

## 状态错误和重试

普通 request 收到响应时：2xx 立即返回；非 2xx 在允许重试时继续尝试，最后仍返回 HttpResponse。**它不自动对每个 4xx/5xx 抛错。** 需要异常时调用 response.raise_for_status()；它只对 400–599 抛 HttpStatusError，3xx 仍须按业务检查。

默认 retry_count=3 表示首次加最多三次重试，指数等待从 0.5 秒开始。默认 no_retry_statuses 为 [404]。单次请求可用 retries、no_retry_statuses、retry_backoff 覆盖；构造传空列表仍会使用默认 [404]，不是关闭状态过滤。

当前重试不按 HTTP 方法判断幂等性，POST 也可能重发。写入、付款、创建资源等普通请求应显式 `retries=0`，或给该实例设置 retry_count=0；需要重试时必须由业务确认幂等。error_code 是响应 JSON 的业务字段，HTTP 客户端不会自动解释或据此重试。

aiohttp 对幂等请求另有一次自己的重发（服务器一个响应都没回就断开时换连接再发一次），不计入 retry_count：上游每次都不回响应就断开时，retry_count=N 实际发出 2×(N+1) 个请求，httpx、curl 是 N+1 个。连接和读取异常在预算耗尽后通常原样抛出 backend 异常；取消继续传播。不要只捕获 HTTPClientError 就宣称覆盖所有网络异常，RequestFailedError 本身也不继承它。协议定义的状态、解压、流消费和 Range 错误分别为 HttpStatusError、HttpContentDecodingError、HttpStreamConsumedError、HttpRangeError。reconnect_stream 还有两种：声明直播的流，上游一直按关连接结束、重试用完时抛内置的 ConnectionError；close_client() 之后还在读的流去续传时抛 RuntimeError。

## 两种响应的读取方式

| 内容 | 普通 HttpResponse | HttpStreamResponse |
| --- | --- | --- |
| 状态/地址/头 | status_code、url、headers、reason、http_version | 同左 |
| 状态判断 | is_success 为 2xx；is_redirect 为 3xx；ok 为 <400 | 同左 |
| 完整正文 | content/read()，bytes，已缓冲 | await aread()，会把全体内容放入内存 |
| 未解压正文 | raw_content() 返回未作 Content-Encoding 解码的 bytes | await raw_content() 同上 |
| 文本 / JSON | text 属性 / json() | aiter_text / aiter_lines / await json() |
| 逐块 | 不提供网络逐块读取，正文已读完 | aiter_bytes 或 aiter_raw |
| 关闭 | backend 读取结束已释放响应 | 流上下文退出关闭；底层接口 aclose() |

headers 大小写不敏感，重复 header 使用 get_list(name) 或 multi_items()，尤其不要把多个 Set-Cookie 拼成一条再解析。cookies 是标准库 CookieJar 形式的响应 Cookie 快照，不是后台客户端的整个会话 jar。

流没有被缓存前只能消费一次。逐块读过后再调用 aread/json 会报 HttpStreamConsumedError；先完整 aread 后可从缓冲区重读，但这失去大文件节省内存的意义。不要把已关闭的流返回给另外一个异步任务继续读取。

## 普通流与 Storage

本页已有真实流示例：run_http_example 的 stream 分支在响应上下文内逐块计算字节数和摘要，不将完整文件读入内存。成功只表示本次传输完成；页面显示实际字节数，不把预期的 65536 硬写成结果。超过 1 MiB 时结束读取，部分内容不提供完整摘要。这个上限只属于本例的流分支，不是普通 get 的响应大小限制。

将下载内容直接保存到 Storage 是另一条接口组合流程，当前 Demo 尚无完整示例。接入顺序是：先取得已初始化的命名 Storage；在 client.stream 上下文内检查状态；把 response.aiter_bytes(...) 交给现有 Storage.save 的异步字节迭代器输入；等待保存完成并使用 Storage 返回的实际逻辑名；最后退出响应上下文。不能先关流再调用 save，不能把逻辑名当本机绝对路径；具体输入、命名与保存失败合同见 [Storage](storage.md)。

响应流由 stream 上下文关闭，client 的池仍由其拥有者关闭。stream 主要处理建立响应阶段的重试，不承诺读取中途能透明续传；不要让业务依赖它对已交付部分正文重新执行。

content_decoding=False 是当前默认：请求通常声明 Accept-Encoding: identity，即使服务端仍返回压缩内容也保留原 bytes。设 True 后统一解码 gzip、deflate、br、zstd（请求默认只声明 gzip, deflate；服务端仍回 br、zstd 时同样能解）。curl 用浏览器指纹（User-Agent 的值是 curl_cffi 的指纹名，例如 chrome、chrome124、edge；见[流媒体中转](proxy.md#浏览器指纹与压缩)）时例外：Accept-Encoding 由指纹决定（例如 chrome 的默认指纹是 gzip, deflate, br, zstd，较旧的指纹可能不带 zstd），开不开解压都一样，不开解压时可能拿到压缩过的原始 bytes；需要明文又不解压的请求自己写 Accept-Encoding: identity；raw_content/aiter_raw 仍可读取原始 bytes。其他编码、截断或损坏的压缩体抛 HttpContentDecodingError；一个字节都没有的正文算空，不算截断（204、304、HEAD、Content-Length: 0，也包括靠关连接结束、在第一个字节之前就断开的压缩正文，与不压缩时一样分不出"空"和"截断"）。

## 中断后的续传

`async with client.reconnect_stream(HttpMethod.GET, url, live_stream=False, ...) as stream` 返回 ReconnectStreamResponse，不是普通 HttpStreamResponse。通过 status_code、response_headers 查看首次响应（内部续传不改变它们），通过 aiter_bytes 读取；当前这条连接的底层响应在 current_response，可先调用其 raise_for_status。上下文负责 release。

- 状态码和响应头取首次响应，内部续传不改变它们。aiter_bytes(chunk_size) 收到多少交多少，chunk_size 只是每块的上限（开解压时只限原始块，见下文）；curl 会把 50 毫秒内到的小块攒成一批。
- 调用方带的 Range 被上游用 416 拒绝时，去掉 Range 再请求一次（不扣重试次数），拿完整内容；把 416 写进 no_retry_statuses 则原样返回 416。
- 默认文件模式（live_stream=False）在读取中断后，从已收下的字节位置带 Range 续传，不带 If-Range。接上的条件只看字节：206 的起点、终点、总长度与首次一致；或者上游回完整的 200、总长度与首次相同（首次没有长度时，要求强 ETag 相同），这时跳过已交付的部分；Content-Encoding 不能变。multipart 响应重放原请求，并逐字节比对已交付的部分。ETag、Last-Modified 与首次不同不算失败：很多 CDN 每次换节点，内容相同、这些头不同。
- 首次的 206 必须从调用方要的起点开始（后缀区间：资源最后 n 个字节的开头），落在要的区间之内，并带有效的 Content-Range；否则抛 HttpRangeError。服务器可以只给一部分（例如 CDN 对 bytes=0- 只回前 1MB），这个 206 原样交给调用方，内部续传也只在这一段之内。正文长度以 Content-Range 为准，短了续传，长了报错。没人要求的 206 缺有效 Content-Range 时照常读完，但不续传。
- 接不上就抛 HttpRangeError（错误状态码是 HttpStatusError），不拼接。已接受的风险：同一地址上的内容被换成长度相同的另一份时发现不了；首次没有长度时，换成任何一份都发现不了。
- 正文比 Content-Length 短就算中断，即使连接正常结束；没有长度的正文缺了结束块、续传时上游回 416 且 `bytes */N` 正好是已收到的长度，算完整读完。
- 续传偏移按**原始字节**计算。客户端开了 content_decoding 时，包装器把完整响应（不是 206）解压后输出，并从 response_headers 去掉 Content-Encoding、Content-Length；206、HEAD 和解不了的编码按原始字节输出。chunk_size 只限制底层读到的原始块：解压后的一块可以远大于它（压缩率高的内容一次解出很多），总量也不设上限，给不可信的上游开解压之前要知道这一点。解压后 response_headers 仍带上游的 ETag、Accept-Ranges，它们描述的是压缩后的表示。
- live_stream=True 是重新连接当前实时流，忽略 Range/If-Range，不核对接不接得上；正文靠关连接结束（HTTP/1.x、没有长度也不分块）时，上游关连接按中断处理去重连。不提供无缝回放、丢包恢复或浏览器 SSE 事件重放。
- 重试预算是连续的：连接失败、错误状态码和读取中断共用 retry_count；没有取得新字节的连续重连会把它用完并报错，交出了新字节就恢复。所以上游每次都给一点就断开的直播流会一直重连，直到调用方停止读取。
- 只有 GET 的 200/206 按文件续传、声明直播的按直播重连；POST 等响应读到一半断了直接报错（curl 的错误在响应头之前出现时，会按连接失败重试）。

本入口用于应用确实需要的下载/流转发；普通 JSON API 用 request/get 即可，不为它套续传逻辑。

## Cookie 与扩展

构造 cookie_jar 接收标准库 CookieJar/MozillaCookieJar。单次 cookies 是此次请求的值，不接受 CookieJar，也不能与显式 Cookie header 同时提供。cookie jar 可能包含登录凭据，不在多个不相关用户之间共用同一实例。

aiohttp 在运行时使用自己的 jar，显式 export_cookies、save_cookies 或 close_client 时写回传入的标准库 jar；其他 backend 的细节按适配器处理。save_cookies 只为 MozillaCookieJar 保存文件，覆盖目标前由应用确认权限。多个客户端共享同一个可变 jar 的并发协调不由框架负责。

BaseHttpClient 是统一接口，公开 init_client/reset_client/close_client/request/stream 等；具体 backend 的构造接收 MultiHttpClient。工厂只识别三个 ClientType，没有通过配置路径自动注册任意 backend 的插件接口。应用扩展优先组合现有客户端，不复制其 Cookie、流和重试实现。
