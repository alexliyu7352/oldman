# 页面消息、反馈与通知

| 用户看到的东西 | 使用入口 | 保存位置 |
| --- | --- | --- |
| 跳转后页面顶部提示 | `oldman.web.messages.success/error/add_message` | 签名 Cookie，短期 |
| Form 顶部 message 与字段错误 | Form/DefaultApiFormResponse | 当前响应 |
| 当前响应要求 toast/弹框 | `FeedbackAction` | 当前有序 actions |
| 有已读状态的个人通知 | `notifications.create()` | 数据库，再尽力 SSE 推送 |
| 在线临时 toast/弹框 | `notifications.push()` | 只 SSE，不入库 |

任务进程控制消息和 NATS 不在此表中，它们见[后台任务](background.md)与 [provider](providers.md)。前端 Feedback 不会自动创建数据库通知。

## Cookie 页面消息

设置 `web.messages.enabled: true`，并通过服务 `settings sync` 准备 `web.security.secret_key`。WebApplication 内部安装中间件和 Jinja `messages`；通常不要自己再调用 `messages.init_app()`。Web 服务已安装 Admin 且 YAML 尚未填写该开关时，settings init/sync 会补为 true；显式 false 保留，单纯加载配置不会自动启用。

EPG [apps/examples/views/messages.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/messages.py) 的实际四条消息入口：

```python
@app.post("/examples/messages/page/multiple", name="example_message_multiple")
@csrf_protect()
@admin_required()
async def example_message_multiple(request: Request):
    """Store all four levels in insertion order, then redirect."""
    success(request, str(_("The database changes were saved.")))
    info(request, str(_("The background import is still running.")))
    warning(request, str(_("Two optional records were skipped.")))
    error(request, str(_("One required record could not be imported.")))
    return redirect_response("/examples/messages/page", status=303)
```

这是现有视图中的完整函数，不是独立模块。app 来自 `get_app()`，success/info/warning/error 来自 `oldman.web.messages`，`_` 是 gettext_lazy，`str()` 在当前请求中取得最终译文；Request、redirect_response、CSRF 及 Demo staff 装饰器也在原文件导入。页面 [messages/page.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/messages/page.html) 使用带 CSRF 的原生 POST，再跟随303。这里的四段文字用于展示等级和顺序，并没有真的执行导入或写库，不能把文案当作业务结果。

四个快捷函数 `success/info/warning/error(request, content)` 都接收**最终字符串**；需要翻译时先在当前请求中调用 gettext。强类型等级 `MessageLevel` 为 success/info/warning/error。

默认文本转义。相同 Demo 模块中的可信 HTML 入口为：

```python
@app.post("/examples/messages/page/trusted-html", name="example_message_trusted_html")
@csrf_protect()
@admin_required()
async def example_message_trusted_html(request: Request):
    """Store one fixed server-authored HTML message, never browser input."""
    content = "<strong>{}</strong> {}".format(
        escape(str(_("Trusted server HTML"))),
        escape(str(_("Only fixed server markup uses this mode."))),
    )
    add_message(
        request,
        MessageLevel.INFO,
        content,
        format=MessageFormat.HTML,
    )
    return redirect_response("/examples/messages/page", status=303)
```

其中 escape 来自 markupsafe；只保留服务器编写的标签，动态文本先转义。下列是模板扩展的 API 示例，不是另一套 Demo 模板：可以一次显示全部消息，自行决定布局。

```jinja
{% if messages %}
  {% for message in messages %}
    <div role="alert" class="om-alert om-alert-{{ message.level }}">
      {% if message.format == "html" %}{{ message.content | safe }}{% else %}{{ message.content }}{% endif %}
    </div>
  {% endfor %}
{% endif %}
```

默认片段为 `oldman/messages/flash_message.html`，共享 Dashboard base 已引入。覆盖该模板即可改显示，不要求写 Jinja tag，也不需要 `get_messages(request)`。它不是 toast、不进入通知中心。

### 消费与限制

- 支持匿名浏览器，不依赖 Session Redis、用户 ID 或数据库；只复用 Session 配置里的 Cookie 安全属性。
- Cookie 名 `oldman_messages`，path `/`，最长 3600 秒；未消费且没新增消息不续期，新增待显示消息才重写/续期。
- `if messages`、`len(messages)` 不消费；开始迭代即标记本次快照已消费，响应中间件删除或重写 Cookie。迭代后新增的消息留到后续响应。
- **没有“HTML 确实显示成功”的浏览器确认**。模板迭代后再发生渲染错误，消费标记不会自动回滚；中间件也不按响应状态恢复消息。不要用它承载必须送达的信息。
- Cookie 值上限 2048 字节，解压上限 64 KiB；超限丢弃最旧的完整消息并记 warning，单条过大也可能被丢弃，不截断 HTML。
- HMAC 防篡改但不加密，不能保存秘密。失效/篡改 Cookie 忽略并清理。
- 多 worker 共享相同密钥即可读写，但同一浏览器并发响应仍可能覆盖 Cookie；不是跨请求事务或 exactly-once 队列。
- 未启用而调用消息函数会明确抛出初始化错误，不静默丢失。

## Form 与当前响应的反馈

Form 顶部专用 `data-om-form-message` 和字段错误由 Form 负责，先显示，再执行 actions；字段只显示第一条错误。`feedback` Action 按顺序调用当前 Page 的 Feedback。业务错误不阻止动作执行，网络错误不伪造成 Form message。完整协议见[响应参考](responses.md)，不要把这些临时结果改成数据库通知。

`DashboardActivityAction` 是浏览器壳内临时操作记录；它也不是持久个人通知。其当前 DOM 与个人通知预览分区不同，不使用数据库 read_at。

## 安装持久通知

服务的 `apps` 至少包含 `oldman.auth`、`oldman.web.messages.notifications`，然后按[数据库迁移](migrations.md)执行已提供的迁移。Admin 再安装 `oldman.apps.admin`；通知 App 不会因为需要 User 就替你自动安装 Auth。

通知表 `oldman_notification.recipient_id` 是指向 `oldman_user.id` 的真实外键，用户删除会级联删除其通知。标题/正文与展示参数用 MsgPack bytes 保存于 LargeBinary，不是 JSON 字符串列。业务负载上限 32 KiB，不在启动阶段偷偷建表。

实际发送入口是 EPG [example_notification_send](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/notifications.py)，POST `/examples/notifications/send`。它从 dashboard_session 读取当前用户，而不是接收浏览器 user_id。先检查 mode/level/presentation/content_mode/title 等字段，再进入以下持久分支原文：

```python
        if mode == "persistent":
            row = await notifications.create(
                user_id=user_id,
                title=title,
                body=body,
                level=level,
                format=message_format,
                presentation=presentation,
                href=href,
                icon=icon,
            )
            data: dict[str, object] = {"mode": mode, "notification_id": row.id}
```

notifications/NotificationPresentation 从 `oldman.web.messages.notifications` 导入，MessageLevel/MessageFormat 从 `oldman.web.messages` 导入。其余变量都来自该函数前面的输入校验；不要复制这段分支后自行信任未校验的字典。`trusted_html` 模式使用文件内固定 `_TRUSTED_BODY`，忽略浏览器 body；`text` 模式保留用户正文并按文本显示。对应[生成器模板](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/notifications/generator.html)明确显示两种选择。

同一函数 temporary 分支调用 `notifications.push` 并返回 `data={"mode": mode, "delivered": delivered}`。这里 delivered 只是 Redis 发布布尔结果，不是用户送达确认。两分支最终都返回 DefaultApiResponse，由页面通用 data-om-action 提交；实际 toast/modal 来自用户 SSE 事件，不是这个 HTTP 响应伪造的提示。

对象 `notifications` 是公开进程级服务，内部按需取得 publisher。必须已完成服务 bootstrap、安装通知 App 并加载模型；后台进程不需要 Sanic request。读取用户语言发生在 SSE 或页面渲染时，不在后台 create 时。

`create(*, user_id, title, body=None, level=INFO, format=TEXT, presentation=NONE, href=None, icon=None)` 返回已提交的 Notification。它使用**自己的数据库事务**，不会加入调用者手中的其他 Session。先完成相关业务事务再调用；没有 outbox/跨数据库与 Redis 原子事务。

title/body 支持普通未翻译源字符串或 `LazyTranslation`。普通字符串也会包装成延迟翻译；用于提取的固定词条应显式写 `_('literal')`。Lazy 参数仅支持 JSON 标量。`presentation` 为 NONE/TOAST/MODAL：NONE 仍入中心，只是不打断在线用户。

当前 **title 永远为文本**；`format=HTML` 只让正文作为可信 HTML 显示，正文 Lazy 中字符串变量会转义，HTML 模板正文由开发者负责安全。不能把未经检查的用户输入直接作为 HTML 源模板；也不要在普通 TEXT 中塞标签后期待自动变 HTML。`href` 仅允许安全同站绝对路径，icon 使用 `ri-*`、`mdi-*`、`bx-*`、`bxs-*` 或 `bxl-*` 单类名，图标还需进入应用构建，见[资源](assets.md)。

create 在数据库成功后发布 `oldman.notifications.created`。Redis 不可用时保留通知，网络发布失败记日志；SSE 信封超限也记日志而不撤销数据库。浏览器离线不补弹 toast，但后来打开通知中心仍能读取。不能因为没看到 toast 就重复 create 同一通知。

临时推送使用相同参数的 `await notifications.push(...) -> bool`，默认 TOAST，不允许 NONE。它要求 SSE enabled，不写库、不入中心、不提供离线记录；仍要求通知 App 已注册。False 表示发布网络失败，True 不是浏览器确认。

## 查询与已读操作

所有接口按用户隔离。视图应从可信 Session/权限装饰器取得 user_id，不能直接使用请求 JSON 指定的接收者作为当前用户身份。

| 异步方法 | 返回与约束 |
| --- | --- |
| `list_for_user(user_id, *, state=ALL, page=1, page_size=20)` | PageResult，page_size 1–100，按 created_at/id 倒序 |
| `topbar_for_user(user_id, *, limit=5)` | 最新未读预览，limit 1–20，不等于全部未读 |
| `unread_count(user_id)` | 未读数 |
| `get_for_user(user_id, notification_id)` | 当前用户记录或 None |
| `mark_read(user_id, notification_ids)` | 实际改动数量 |
| `mark_all_read(user_id)` | 实际改动数量 |
| `delete(user_id, notification_ids)` | 实际删除数量 |

状态 `NotificationState.ALL/UNREAD/READ` 是 StrEnum。修改方法提交后尽力发布 `oldman.notifications.sync`，其他标签页据此重新取顶栏 HTML；不存在另一套通知专用订阅服务。

## Dashboard/Admin 接线

Admin 已接好：安装通知 App 后提供 `/admin/user-notifications` 及共享操作接口；开启 SSE 后提供 `/admin/user-events`，使用 Admin 登录权限。

业务 Dashboard 使用 `oldman.web.messages.notifications.init_app(app, url_prefix="") -> NotificationRoutes` 安装**通知 HTTP 操作**，不是安装通用 SSE 路由。返回 topbar_url/read_url/delete_url/center_url：

- GET `/user-notifications/topbar` 返回共享预览 HTML。
- POST `/user-notifications/read` 接收 `{"ids":[1,2]}` 或 `{"all":true}`。
- POST `/user-notifications/delete` 只接收 `{"ids":[1,2]}`。
- GET `/user-notifications/<id>/open` 核对当前用户、标已读，再 303 到 href 或中心。

这些接口要求 Session、CSRF 和模板环境，写请求走 CSRF。非法请求当前为 HTTP 400，认证/权限走公共安全路径，不能伪造成功。

**中心外壳路由由应用定义**：在它的登录保护视图中调用 `await render_center_content(request, user_id=user_id)`，将结果传入继承自己 Dashboard base 的模板；`init_app()` 不会替业务选择页面布局。共享主体 `oldman/messages/notifications/center_content.html` 已包含筛选、分页、选中标读、全部标读和删除协议，不复制两套控制器。

顶栏使用共享 `dashboard_topbar` macro 的 `user_notification_urls={"topbar": routes.topbar_url, "center": routes.center_url}`。DashboardPage 初始化时请求最新预览，SSE created/sync 及重连 open 再刷新；预览最多五条、只供点击，不含批量选择框。toast 显示不等于已读，打开或显式标读才更改状态。

用户 SSE 路由和 `<meta name="oldman-user-events-url">` 按 [SSE 参考](sse.md)接入。共用 DashboardPage 的通知/Feedback/连接实现；不用自行监听 Redis、解析二进制、复制通知 DOM 或增加独立 notification subscriber。
