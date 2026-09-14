# SSE 与 WebSocket

SSE 是浏览器接收服务器事件的单向连接，不是可靠消息队列，也不是通知业务本身。`oldman.web.sse` 同时支持当前请求直接产生数据、以及其他进程通过 Redis 发布数据。普通通知只是其消费者之一。

## 当前请求直接输出

实际例子是 EPG Demo 的 `/examples/tables/realtime`，路由在 [apps/examples/views/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tables.py)。WebApplication 已初始化公开实例 `sse`，不要为每个请求新建 extension。下面是该模块的完整路由方法；`app=get_app()`、`asyncio`、`itertools.cycle`、`apps.examples.services`、`apps.auth.decorators.admin_required` 和 SSE 类型都由该文件提供：

```python
@app.get("/examples/tables/realtime/events", name="example_realtime_table_events")
@admin_required()
@sse.streaming(queue_mode=SSEQueueMode.LATEST, session_guard=True, login_url="/login")
async def example_realtime_table_events(request: Request, stream: SSEStream) -> None:
    """Replay database-backed server samples through one page-owned SSE stream."""
    del request
    snapshots = await services.list_server_metric_snapshots()
    for samples in cycle(snapshots):
        if stream.is_closed:
            return
        # Viewing the demo replays stored samples; only explicit publishing writes data.
        await stream.send(services._realtime_payload(samples), event="examples.table.metrics")
        await asyncio.sleep(1)
```

`services._realtime_payload()` 返回 Demo 自己的 `_RealtimeTablePayload(MsgspecModel)`，包含 `rows: list[_RealtimeTableRow]`，每行有 `id: int` 和 `cells: dict[str, str]`。完整负载、DOM 与页面组件在[实时页面任务指南](../agents/realtime.md)。循环回放已有数据库样本，不因打开页面写库；只在连接开始查询，循环里不持有数据库 Session。

直接 `stream.send()` 不经过 Redis Pub/Sub，不要求 `web.sse.enabled=true`；该开关只启用**跨进程**发布订阅。但这条实际 Demo 路由启用了 Session 身份检查，因此仍需要 Session 的 Redis。不能把“不使用 Redis transport”说成“整个 Demo 无需 Redis”。

`@sse.streaming(*, preflight=None, queue_mode=SSEQueueMode.FIFO, queue_size=None, retry=None, session_guard=False, login_url="/login")` 在路由处理器的 request 后注入 `SSEStream`，不负责路由注册。`preflight(request)` 是可选异步检查，在发送 HTTP 响应头前执行；一般权限校验直接使用已有权限装饰器，并放在 streaming 外层。

`stream.send(payload, *, event, id=None)` 接收 `MsgspecModel`，输出 JSON 字符串作为 SSE data。`event` 使用稳定名称，如 `server.metrics`；`id` 是可选字符串。`retry` 在 streaming 装饰器设置，单位毫秒，影响原生 EventSource 重连间隔。`id` 不会让框架自动保存或补发事件。

只有一个 writer 写 HTTP 响应，业务 send 只入队；handler 正常结束会发送完已排队数据再关闭，断线会取消 handler。业务资源放 `try/finally`，不要捕获并吞掉 `CancelledError`。不要同时使用 `request.respond()` 自己写同一个响应。

## 跨进程配置

接收和发布服务配置相同 Redis alias 与项目/环境 channel 前缀。以下为 Demo [web_settings.example.yaml](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/web_settings.example.yaml) 中 SSE 所需节点，其他服务配置保留：

```yaml
redis:
  SSE:
    redis_url: redis://127.0.0.1:6379/6
web:
  sse:
    enabled: true
    redis_alias: SSE
    channel_prefix: oldman_epg_dashboard
    heartbeat_interval: 15.0
    session_check_interval: 30.0
    queue_size: 100
    max_message_size: 65536
```

合并到服务现有 YAML，再执行服务的 `settings sync/check`。SimpleApplication 的配置工具不会主动补齐 Web 子树；后台发布需要它时，显式写入所需节点。Redis Pub/Sub 不按 Redis DB 数字隔离，隔离依赖 channel_prefix；不同项目/环境不要复用同一前缀。

Web 初始化只检查本地配置。服务器启动后，每个 Sanic worker 启动一个订阅协程，第一次访问 Redis 才连接。Redis 失败记录 ERROR 并按退避重连，不关闭整个 Web 服务；恢复时记录日志。订阅建立前及断线期间的消息可能丢失。

## 发布对象从哪里来

实际发布入口是 [views/charts.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/charts.py) 的 `example_realtime_chart_publish()`。以下是完整路由方法，不是另一个后台采集服务；`db_manager` 来自 `oldman.db`，`SSEPublisher` 来自 `oldman.web.sse`，响应类型/函数来自 `oldman.web.api/response`，`_` 是 `gettext_lazy`。`_server_id`、`CHART_EVENT="examples.chart.metric"` 及全部导入在同文件，业务查询/负载在 services.py：

```python
@app.post("/examples/charts/realtime/publish", name="example_realtime_chart_publish")
@csrf_protect()
@admin_required()
async def example_realtime_chart_publish(request: Request):
    """Commit one metric, then publish it through the configured SSE Redis channel."""
    server_id = _server_id(request)
    async with db_manager.get_session() as session:
        try:
            payload = await services.create_server_metric(session, server_id)
        except ValueError as exc:
            raise BadRequest("Unknown example server") from exc
    published = await SSEPublisher.from_settings().publish_stream(
        stream=services.realtime_chart_stream(server_id),
        event=CHART_EVENT,
        payload=payload,
    )
    if not published:
        return api_response(
            DefaultApiResponse(
                error_code=ApiErrorCode.INVALID_REQUEST,
                message=_("The metric was saved, but Redis delivery failed."),
            )
        )
    return api_response(
        DefaultApiResponse(
            message=_("A new database metric was published."),
            actions=[
                FeedbackAction(title=_("Realtime metric published."), icon="success")
            ],
        )
    )
```

这里先退出数据库上下文完成提交，再发布；失败不能声称数据库没有写入，也不回滚已提交样本。浏览器在同文件的 `example_realtime_chart_events()` 先收到最近最多6条历史样本，再 `await stream.subscribe(services.realtime_chart_stream(server_id))` 接收新指标。页面按钮就是这个真实 POST，不是浏览器自行模拟计数。

发布对象没有独立连接池；Demo每次请求调用 `from_settings()` 创建轻量对象，底层连接仍复用 Redis provider。普通后台进程在完成 `bootstrap_service()`/Application 初始化后也可创建并复用一次。API参考还支持显式 `SSEPublisher(config: SSEConfig, *, registry=None)`，默认使用全局 provider。它不是 Sanic extension，不需要 request 或 `app.ctx.sse`；没有另一套 close API，连接由 provider/Application 生命周期关闭。

- `publish_stream(*, stream, event, payload) -> bool` 发到已授权订阅某业务流的连接。
- `publish_user(*, user_id: int, event, payload) -> bool` 发到该用户已订阅的所有在线标签页/设备。
- 成功返回 True 只表示 Redis 发布命令成功，不表示有人在线或已经显示。Redis 网络失败返回 False；关闭开关、类型/名称非法及过大负载仍抛异常。

事件段为字母开头，后续可含字母、数字、下划线、连字符；点分隔多个段，最长 128 字符。业务 stream 至少含两个段，如 `servers.metrics`；事件可单段。用户 ID 是严格 int，不隐式接受字符串/bool。

publisher 先把强类型 payload 编为 MsgPack bytes，再放入版本化信封；信封也为 bytes，整体默认不得超过 65536 字节。消息不是先转 JSON 再编码。普通 Struct 保持对象形式，不使用 `array_like=True` 作为分发 payload；订阅端要求其解码后为 JSON 对象。

## 接收用户事件与业务流

用户路由复用 Session 中的身份，不接收浏览器随意填写的 user_id。以下为 Demo [apps/auth/views.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/auth/views.py) 的完整条件注册块。`settings` 是项目全局配置，`current_user_id(request)` 是该文件从 `dashboard_session(request).user_id` 读取的辅助方法；`admin_required` 是 Demo 自己的 staff 权限装饰器：

```python
if settings.web.sse.enabled:

    @app.get("/user-events", name="user_events")
    @admin_required()
    @sse.streaming(session_guard=True, login_url="/login")
    async def user_events(request: Request, stream: SSEStream) -> None:
        """Deliver shared low-frequency user events to one authenticated browser."""
        user_id = current_user_id(request)
        if user_id is None:
            raise RuntimeError("Authenticated Dashboard Session has no user id")
        await stream.subscribe_user(user_id)
```

`subscribe_user()` 要求 session_guard=True，并校验 user_id 与该连接已认证用户一致。方法等待到连接关闭，不是登记后立即返回；不必另写永久 sleep。

业务流同样使用 `await stream.subscribe("servers.metrics")`。订阅前由业务校验该用户能否查看该资源；stream 名称只是路由标签，**不是权限**。多租户不要让浏览器通过 query 参数选择任意 stream。需要在同一连接挂多个已授权 stream 时可用 `asyncio.gather()` 并发等待这些 subscribe，关闭时统一清理。

`sse.user_streams(user_id)` 只返回当前 worker 的连接快照，不代表所有进程或“用户在线”的可靠全局状态。跨进程统一使用 publisher。

## Session 过期、翻译与背压

session_guard 在首次写入前及默认每 30 秒检查 Redis 中 SID 和用户 Session 索引是否仍有效，不重新查询 User 数据库。失效时先发送 `oldman.session.invalidated`（title、message、login_url），再关连接。它不因心跳而延长登录；权限变更需要业务同步撤销 Session。Redis 检查异常导致连接失败，不能当作已确认的 Session 过期。

检查与心跳都由同一 writer 调度；繁忙连接也检查 Session。这个间隔不是网络堵塞下的硬实时保证，实际送出仍取决于可写连接。默认心跳是 SSE comment，不是业务消息。

有延迟翻译文本时，继承 `oldman.i18n.TranslatableMsgspecModel`，字段使用 `LazyTranslation`，值使用 `gettext_lazy()`。普通 `MsgspecModel` 不支持该专用 MsgPack 扩展。通用 SSE 订阅端恢复延迟文本，并按每条连接持有的 request 翻译目录输出 JSON；不需要通知专用 subscriber 或业务手动 decode。直接 `stream.send()` 则在当前请求翻译上下文内序列化。

连接持有建立时的语言，用户改语言后要重建连接。延迟文本参数只允许 JSON 标量；不要把数据库对象/函数放入翻译变量。通知数据库也保存同样的 bytes，见[消息与通知](messages.md)。

`FIFO` 默认容量 100，队列满会断开慢客户端，不阻塞其他连接；不是无限缓存。`LATEST` 容量固定为 1，新消息覆盖尚未发送的旧消息，适合**完整最新快照**。它不是按行/事件名分别保留一条：逐行发送服务器指标时不能假定每行都保留，必要时一次发完整批次或使用 FIFO。

## 浏览器 API 与恢复

实际浏览器消费者在 [realtime-chart.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/components/examples/realtime-chart.ts)，`ExampleChart` 继承 `oldman-web/core` 的 Component，并从 `oldman-web/sse` 导入 EventStreamClient。下面是类中的完整方法：

```typescript
  private connect(url: string): void {
    const client = new EventStreamClient(url);
    client.on<unknown>("examples.chart.metric", (payload) => this.applyRealtime(payload));
    client.onOpen(() => this.setRequestState(this.i18n.t("SSE connected")));
    client.onError(() => this.setRequestState(this.i18n.t("SSE reconnecting")));
    this.cleanup(() => client.close());
  }
```

`mount()` 在图表首次 `om:chart:render` 后调用此方法；URL来自组件根节点的 `data-om-realtime-chart-url`。`applyRealtime()` 先校验负载，再调用同 Page 已挂载 ApexChart 的 `appendData()` 更新 CPU/内存序列。`setRequestState()` 更新示例状态文字，不创建新Feedback。组件由 ExamplesPage 私有 loader 挂载，离页时 cleanup 关闭连接；不要把这段方法移到模块顶层常驻执行。

`EventStreamClient(url, options: EventSourceInit={})` 封装原生 EventSource；`on<T>()` 解析命名 JSON 事件并返回取消监听函数，T 是静态类型，不是运行时数据校验。`onOpen()` 包含重连后的 open，`onError()` 不关闭原生重连。`close()` 永久关闭并移除监听，可重复调用。

监听失效事件后，客户端会在交给业务处理前关闭连接，停止重连；自定义 Page 仍需显示提示。DashboardPage 已监听并调用壳 Feedback，用户确认后跳转登录。其 `<meta name="oldman-user-events-url" content="/user-events">` 必须唯一且为同站绝对路径。没有此 meta 就不创建用户连接。

Dashboard 扩展已有用户连接使用 `protected bindUserEventStream(client): StopEventStreamHandler[]`，返回自己的取消监听函数，不重新创建一条相同用户连接。局部页面专用指标流可以独立建立，卸载时 close；不强制整个产品只有一条连接，也不为每种事件新建连接。

断线期间无离线队列、无重放、无 ACK、无 exactly-once。直接 send 的 id 与 retry 只是 SSE 协议字段；当前 publisher 不携带事件 ID，服务也不根据 Last-Event-ID 恢复。重连时用已有 API/数据库重新获取当前状态，通知顶栏已这样处理。高频数据页面尽量复用连接，反向代理不能缓冲 SSE，见部署指南。

## 需要双向通信时用 WebSocket

`oldman.web.websocket` 只提供路由 helper 和原生连接的结构类型，不把 WebSocket 塞进 SSE publisher。以下是独立的 API 参考，不是 Demo 已提供的页面或已注册路由：

```python
from oldman.web.request import Request
from oldman.web.websocket import WebSocket, websocket

@websocket("/examples/echo")
async def echo(request: Request, ws: WebSocket) -> None:
    async for message in ws:
        await ws.send(message)
```

在 App views 加载时注册。`websocket(path, *, name=None, subprotocols=None, strict_slashes=None)` 转交 Sanic；连接支持 recv/send/close、异步迭代及 ping/pong。WebSocket 大小与 ping 参数在 `settings.web`。上例仅为 echo，不包含业务权限；真实入口在握手前验证身份、Origin 和资源权限，输入仍须校验。它没有内置 Redis 路由、可靠离线投递或 SSE 的 Session 定时检查。
