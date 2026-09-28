# 提示用户与实时更新

不要把所有消息都放进通知中心。选择取决于用户之后是否还需要找到它，而不是它看起来像 toast 还是页面文本。

先按[EPG Demo 运行步骤](getting-started.md)准备配置、迁移、fixture、账号和前端，登录自己的 Demo。以下页面都已经存在；不需要为阅读本章另写一个报告服务。源码与后端调用见[消息参考](../developers/messages.md)。

## 保存后跳转：页面提示

启用 `web.messages.enabled`，在业务成功后调用 `messages.success(request, "保存完成")`，再返回 303 跳转。共享 Dashboard 页面自动显示；普通模板显式 include `oldman/messages/flash_message.html`，或自己循环 `messages`。

可以添加多条，一次渲染全部。它用签名 Cookie，不用 Redis，不要求登录；容量有限、并发响应可能覆盖，也没有送达确认。长篇报告或重要记录不适合放这里。完整 HTML/翻译/消费规则见[页面消息](../developers/messages.md#cookie-页面消息)。

表单不跳转时使用 Form 的 message/errors。当前请求需要 toast 或弹框则返回 `FeedbackAction`，按[响应协议](../developers/responses.md)处理，不必写入数据库通知。

打开 `/examples/messages/page`：提交单条输入，标签按文本显示；点“显示四条消息”，下一页顶部按顺序显示四种等级；再刷新不重复出现。可信 HTML 按钮只发送服务器固定标签，显示粗体。四条文字是等级演示，不会真的导入数据。对应 `/examples/messages/feedback` 才是当前请求的 toast、alert、确认和输入示例，两类展示互不替代。

## 后台完成任务：个人通知

在接收和发送通知的服务中安装 `oldman.auth` 与 `oldman.web.messages.notifications`，同步配置、执行 `oldman db migrate`。需要在线提醒时再按 [SSE 配置](../developers/sse.md#跨进程配置)设置 Redis 与 channel 前缀。

业务提交成功后调用 `notifications.create(user_id=..., title=..., body=...)`。默认进入通知中心，不弹窗；在线顶栏仍会更新。加 `presentation=NotificationPresentation.TOAST` 或 MODAL 才在用户在线时额外提示。接收者 ID 必须来自业务允许的对象，不允许匿名调用者任意向他人发送。

后台使用延迟翻译 `_('Report ready')`，不要猜用户语言提前翻译。HTML 仅用于显式 HTML 正文；标题是文本。

Admin 已接好中心、顶栏与用户事件路由。业务 Dashboard 使用共享通知接口、模板主体和 DashboardPage，不复制 Admin 私有实现。按[通知接线](../developers/messages.md#dashboardadmin-接线)添加宿主中心页面、顶栏 URL 与用户 SSE meta。

验证应包含：用户离线时创建通知，再登录能在中心找到；在线时创建带 toast 的通知，出现提示且顶栏更新；点击通知标读；另一个用户看不到它。只看到一条 Redis publish 日志不算验证成功。

实际操作从 `/examples/notifications/generator` 开始：选择持久、展示方式及级别，填写标题；文本模式使用输入正文，可信 HTML 模式改用固定服务端正文。图标选择使用单个类名，例如 `mdi-check-circle-outline`、`bx-error-circle`，不是带空格的两段 class。发送后打开 `/user-notifications` 可找到真实记录；`/examples/notifications/center` 是操作说明页，不是第二套通知中心。`/notifications` 则是 EPG 自身的业务记录页面，也不是这个个人通知中心。

## 只提醒当前在线用户

使用 `notifications.push()`。它不入数据库、不出现在中心，离线即丢失。适合短暂状态提示，不适合必须保存的错误报告或待办。它仍使用同一用户 SSE 连接，无需另建路由或通知 subscriber。

在生成器选择临时且选择 toast/modal；临时配“仅通知中心”会返回可见的业务错误，不会偷偷保存。`/examples/notifications/realtime` 另有现成的“持久并投递”和“仅在线推送弹窗”按钮；后者显示后不增加数据库记录或未读数。示例接收者固定为当前登录用户，没有授权浏览器任意给别人发送；验证离线接收或其他用户隔离时，需要自己的第二个账号/后台调用，不能假称生成器提供这些输入。

## 实时数值不是通知

服务器带宽、任务状态或图表数值使用普通 `MsgspecModel` 事件，通过 SSE 到达页面。Page 按业务字段更新 DOM/图表，不创建 Notification。后台独立进程使用 `SSEPublisher`，当前请求内计算的简单数据直接 `stream.send()`。

先看[最小 SSE 例子](../developers/sse.md#当前请求直接输出)，需要更新 Table 时使用[实时页面任务指南](../agents/realtime.md)。Table 已输出稳定主键和列名，不需要为了改一个数字重刷整表，也没有另一套 SSE Table 组件。

SSE 是尽力投递，重连要获取当前快照；不要使用它传递唯一一份重要业务结果。打开多个相同连接、给每行分别建立 EventSource 都是不必要的开销。
