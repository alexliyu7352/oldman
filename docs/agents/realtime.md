# 任务指南：用 Demo 的 SSE 更新实时界面

先确认需求是当前页面的数据更新、后台跨进程发布，还是用户通知。不要为一个实时表格新建通用行缓存、表格消息总线或通知订阅体系。

可运行基准是 EPG Demo 的：

- `/examples/tables/realtime`：只读回放数据库样本，局部更新单元格。
- `/examples/charts/realtime`：初始数据与历史样本，加显式写库后经 Redis 发布的新样本。
- `/examples/notifications/generator`：用户通知，不与监控指标混用。

运行前按[Demo 教程](../users/getting-started.md)准备配置、Redis、迁移、fixture、账号和资源。完整协议见 [SSE 参考](../developers/sse.md)；不要从一个 EventSource 标签推测整条链路已接好。

## 一：直接输出的实时表格

相关文件都在 EPG Demo：

| 职责 | 源码 |
| --- | --- |
| 页面与 SSE 路由 | [apps/examples/views/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tables.py) |
| 样本查询、强类型负载与显示格式 | [apps/examples/services.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/services.py) |
| 初始 HTML 与稳定 DOM 标记 | [tables/realtime.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/tables/realtime.html) |
| 接收与局部更新 | [realtime-table.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/components/examples/realtime-table.ts) |
| 页面私有 loader | [pages/examples.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/pages/examples.ts) |

后端实际使用的 MsgspecModel 子类：

```python
class _RealtimeTableRow(MsgspecModel, kw_only=True):
    """One visible server row update for the private Demo stream."""

    id: int
    cells: dict[str, str]


class _RealtimeTablePayload(MsgspecModel, kw_only=True):
    """Current metric values keyed by the Table's stable DOM attributes."""

    rows: list[_RealtimeTableRow]
```

它们在 services.py，属于 Demo 私有负载，不是 oldman 的公开 Table API。`_realtime_payload()` 用 server.id 和 sampled_at、cpu_percent、memory_percent、upload_mbps、download_mbps 生成格式化文本。

实际 SSE 路由：

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

这段位于已有视图模块，app 来自 get_app；asyncio、cycle、services、SSE 类型及权限装饰器已在该文件导入。不要把路由模块导入后台进程来取得负载。

查询只在连接开始时读取最近最多 60 个完整时间批次，先筛选批次完整性再限制数量，随后按时间回放。不在发送循环中持有数据库 Session，也不因每打开一个浏览器就生成记录。

这是**样本回放**：循环回到较早时间是预期行为，不是实时采集时钟。连接建立之后不会再自动加载新写入的样本；刷新/重新连接才重新读取。不能因此承诺它能取代真正的生产监控采样器。

## 二：DOM 与组件如何对应

模板直接输出普通 HTML table，并标记：

- 行：`data-om-table-row-id="{{ server.id }}"`。
- 列：`data-om-column="cpu_percent"` 等，名称与负载 cells 的键对应。
- 组件：外层 `data-om-component="realtime-table"`。
- 数据源：`data-om-realtime-url="/examples/tables/realtime/events"`。

这个示例不是 TanStack Table 实例；稳定属性与共享 Table 协议一致，不代表页面使用了插件的全部功能。使用框架生成的 Table 时，行 ID 默认由主键生成，列名映射见 [Table 参考](../developers/tables.md)；不要在前端依赖“第几行第几列”。

RealtimeTable 组件的实际挂载方法：

```typescript
  override async mount(): Promise<void> {
    const url = this.root.dataset.omRealtimeUrl;
    if (!url) throw new Error("Realtime Table requires data-om-realtime-url");

    const client = new EventStreamClient(url);
    client.on<unknown>("examples.table.metrics", (payload) => this.apply(payload));
    this.cleanup(() => client.close());
  }
```

文件从 `oldman-web/core` 导入 Component，从 `oldman-web/sse` 导入 EventStreamClient。`apply()` 先校验 rows/id/cells，再用 CSS.escape 处理选择器，通过行 ID 找行、字段名找列，使用 textContent 更新。缺少的行和列忽略，不增加额外缓存或 updateCell API。

这里只更新显示，不修改数据库、排序、筛选或 TanStack 内部状态。页面私有 loader 位于 ExamplesPage；离开 Page 时组件清理关闭连接，不放进全局永续订阅。

## 三：已经存在的 Redis 发布示例

需要看 publish/subscribe 时，使用 [views/charts.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/charts.py)，不是在文档发明一个不存在的 collector 服务：

1. 浏览器在实时图表页选择服务器，连接 `/examples/charts/realtime/events`。
2. 路由先直接输出最多 6 条数据库样本，再订阅 `services.realtime_chart_stream(server_id)`。
3. 发布按钮 POST 到 `/examples/charts/realtime/publish`，校验 CSRF 和 staff 权限。
4. `create_server_metric()` 在写事务内创建样本；退出上下文提交。
5. 之后调用 `SSEPublisher.from_settings().publish_stream(...)`，事件为 `examples.chart.metric`，负载为 RealtimeChartPayload。
6. Redis 发布失败时明确返回“样本已保存，但投递失败”的业务结果，不撤销已经提交的数据库记录，也不伪报全部成功。

当前 Demo 的发布入口仍是 Web 请求，不是假称已经有独立后台服务。真正移到后台时，业务普通模块可以复用模型/负载，发布端不需要 request.app.ctx.sse；服务生命周期、Redis alias/channel 和权限范围必须显式接好，按 [SSEPublisher 合同](../developers/sse.md)实现，不新增第二套发布 API。

Pub/Sub 不提供离线可靠重放。周期快照、重连后重新读取当前数据、用户通知持久记录是不同选择，不能把缺失消息全部塞进通知表。

## 四：用户通知仍用现有共享链路

EPG 的 `/user-events` 位于 apps/auth/views.py，校验登录后 subscribe_user 当前 Session 的用户 ID。服务的通知初始化与顶栏 meta 位于 services/web.py 和 templates/base.html。

使用 [用户通知指南](../users/messages-and-live-updates.md)中的公开入口；不要把高频监控指标持久化成未读通知，也不增加 notification subscriber。接线见 [Demo 示例索引](../users/demo-examples.md#消息通知身份与语言)。

## 本任务验证

- 初始 HTML 使用数据库数据；观察 sampled_at、CPU、带宽实际变化，不能只看一个 Live 标签。
- 同时打开两页不应导致监控记录增长；只有显式图表发布按钮才新增样本。
- 从普通业务页经侧栏进入实时表格，检查 ExamplesPage 的私有 loader；直接打开正常不能代替 Turbo 验证。
- 离开时连接关闭，重进时连接与组件重新创建，不累积定时器或重复更新。
- 空 fixture、断线、Session 失效分别验证；未授权用户不能得到指标。LATEST 表示允许保留较新数据，不是可靠消息队列。
- 测图表发布时核对真实数据库和 Redis，不能只模拟 client.on 回调就声称验证完链路。
- HTML/JSON 动态项目表格另在其页面测试；不要把静态实时表格的通过误报为 TanStack 分页/排序/内部数据同步已覆盖。

只执行相关场景的检查。临时服务、Redis、数据库、浏览器和文件应由本任务创建并清理，不改变用户正在运行的 Demo。
