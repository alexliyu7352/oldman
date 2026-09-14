# Agent：缓存与外部连接

为应用增加缓存、调用上游 HTTP 或使用 Redis/NATS 时，先确认业务需要的是哪一种能力。不要创建含糊的 MessageBus、重复 HTTP 包装器或额外连接单例。

| 任务 | 公开入口与参考 | 应用通常改哪里 |
| --- | --- | --- |
| 多 worker 共享可重算结果 | [redis_cache / RedisCache](../developers/cache.md) | 本服务 YAML、实际业务查询和写入后的失效位置 |
| 本进程临时结果 | MemoryCache，同上 | 持有缓存的业务对象及关闭位置 |
| Redis 原生命令/锁/PubSub | [redis_client.using](../developers/providers.md#redis-连接) | YAML 中明确 alias、业务方法、订阅任务收尾 |
| 外部 API / 下载 | [MultiHttpClient](../developers/http-client.md) | 业务客户端、服务启动与关闭、上游配置 |
| 服务之间在线事件/RPC | [bus / NATSConnection](../developers/providers.md#nats-连接与发布) | nats/nats_bus 配置、共享消息、App events、接收服务 |

通用缓存和后端 HTTP 的真实 Demo 为 `/examples/cache/redis`、`/examples/http/client`，见[运行与源码说明](../users/cache-and-http.md)。NATS 已有三个真实通信页面和 Taskiq 内 RPC；先按[通信教程](../users/service-communication.md)运行，再查精确接口，不虚构另一套示例服务。

## 缓存

当前可直接参考 EPG 的 `apps/examples/cache_example.py`、`apps/examples/views/cache.py` 和 `templates/pages/examples/cache/`：

- `RedisCache("CACHE", namespace="oldman_epg_dashboard:examples:project-statistics", serializer="json", timeout=5)` 由业务模块持有，使用公开 YAML 的 CACHE 别名；构造不联网。不要为复制本例新增缓存 facade 或配置类型。
- `read_project_statistics(refresh=False)` 只有 get 返回 None 才查询 ExampleProject；显式 refresh 直接查库，然后 set 同一个 key，TTL=30。命中不查询项目表、不重设 TTL；零项目也有完整快照，不用真值判断当作 miss。
- 返回快照与来源元组，来源由当前请求分支产生；时间保存在快照里，命中时不会伪造新的“计算时间”。三个 POST 共用 staff/CSRF 保护，结果片段通过无 target 的 replace_html action 返回，目标由按钮指定。
- 本例是跨 staff 共享、允许短暂陈旧的统计。没有租户/用户私有 key、CRUD 自动失效、锁或后台任务；复制到不同业务时先明确这些需求，不悄悄改变本例行为。
- clear 只删除 counts，不使用 clear/通配删除/FLUSHDB。Redis 故障不静默查库兜底，数据库故障不变成空统计；公共错误链路结束遮罩并提示失败。
- WebApplication 关闭共享 Redis，Demo 的 WebService 关闭数据库；不要每次请求关闭共享连接。专项测试在 `tests/test_examples_cache.py`，真实页面还应点击验证，不能用直接调用函数代替动态页面验收。

内存/两级缓存直接参考 `apps/examples/cache_levels.py` 和 `./run.sh web cache-levels`。同一份 calculate_project_statistics 查询供 Redis 页面和命令复用，不复制 SQL。父命令持有自己的 MemoryCache、UUID namespace 的 RedisCache 和 TwoLevelCache；受控子进程重新 bootstrap 后查库并改 Redis，父进程实际证明旧内存仍命中。之后只清除本地副本并回填，再验证两层 TTL 和 delete。输出含真实父/子 PID、两次计算时间和检查结果；缓存/数据库异常不能变成成功。父子分别关闭自己的连接，命令结束只清理本次 key，无新 Worker、表、全局缓存或失效广播。

函数缓存照 `apps/examples/cache_functions.py` / `./run.sh web cached-stats`：真实查询、1秒 TTL、本次 UUID prefix、命中/到期时间对比、finally 定向删除及连接关闭。不要复制为 import 时执行查询，也不要把装饰器 warning+降级行为写成必然命中。

响应缓存照 views/cache.py 的 GET/POST `/examples/cache/response` 和同页下方分区：GET 权限先于 cache_response，5秒缓存整个 replace_html JSON，vary_by 明确当前 locale，不能缓存 CSRF/个人数据；POST 先过 CSRF/staff 后由同 prefix 装饰器失效全部 query/语言版本。两个按钮目标 #cache-response-result，与原值缓存 #cache-result 分开。沿用公共 Page/Actions，不新增前端请求实现；根 cache 配置和共享池由当前服务管理。复用时验证实际重复点击时间相同、到期/POST后变化、语言隔离、匿名/坏CSRF拒绝及错误后恢复，不能只证明装饰器出现在源码。

应用缓存的一般约束：

1. 明确可接受的陈旧时间、进程范围和 key 归属；不能用 MemoryCache 实现多 worker Session/权限失效。
2. Redis 使用已有服务配置的 cache.client 或显式 alias，namespace 必须非空且属于本业务。跨应用、租户或权限数据要在 key/隔离策略中明确表达。
3. 值用 JSON 等适当格式；Pickle 只读可信 Redis。写明 miss/None 的区别及 TTL。
4. 缓存操作直接抛错；若业务允许缓存故障降级，只处理缓存失败，不吞业务查询异常。现有函数/响应装饰器的降级和 key 规则见参考，不能把它们当无碰撞或防击穿工具。
5. 事务成功后再失效/更新缓存；不声称数据库与 Redis 原子提交。TwoLevelCache 没有跨 worker 本地失效广播。
6. 验证不同进程读写、失效/过期、False/0 命中和 namespace 隔离；只清理本任务 key，不运行共享库 FLUSHDB。

Django 互操作单独使用 oldman.compat.django.cache，双方默认 key/codec、同 Redis DB 必须匹配。它的 lock_timeout=0 删除语义不能套到原生 Cache。实际 Demo 为 `apps/examples/django_cache.py` 的 django-cache：Django 延迟导入，只在 /tmp 可选环境安装；真实 backend 双向读写 SQL 统计和边界值，断言类型、None/miss、TTL/版本/损坏数据。照[用户步骤](../users/cache-and-http.md#可选与-django-交换缓存)运行，不新建 Django 网站、不新增生产依赖。只用随机已知 key，清理 version=1/2，绝不能 Django.clear；特殊 _cache._pools 断开只为本例实际释放 Django 5.2 自有池，不能扩散成框架代理。

图片缓存示例位于 `apps/examples/image_cache.py`，运行 `./run.sh web image-cache`。明确 bytes 来源、Storage 所有者和索引 key：自有 PNG → 显式 FileSystemStorage/TemporaryDirectory → ImageCache.cache_image，不复制下载/Storage 实现。实际命中延长 score，过期读 miss，下一次写入删旧文件；非图片 bytes 只保留 original 并记录 WebP 错误，不能写成自动验证失败。最终只删本次随机集合和文件，不接触上传目录。当前容量清理已调用，但不是严格图片数/字节上限；不要沿用旧文档“方法未调用”的错误结论。

## HTTP


先从 Demo 的 `apps/examples/http_example.py`、`apps/examples/views/http.py`、`apps/examples/settings.py`、`templates/pages/examples/http/` 和 `services/web.py` 取例；[完整实现与生命周期](../developers/http-client.md#demo-中的实际使用)已逐段对应源码。

- ExamplesSettings 由 AppConfig 泛型与 settings_model 注册，`app_settings.examples.http_base_url` 绑定到该 App 的 app.settings。业务函数运行时读取，不在 apps.py 元数据导入期间提前读取，也不新增全局 settings.examples 或 app.ctx.settings。
- 上游默认公共 httpbin，可以部署者配置为兼容实例。浏览器只选固定操作，不传抓取 URL、请求头、凭据或数据库内容。不要把本例变成通用代理。启动和页面 GET 不发上游请求。
- WebService 的 before_server_start 在 super 后 init_client；after_server_stop 先 close_client，再在 finally 中调用 super。原数据库关闭位置保持不变。业务模块持有每 worker 的实例，请求之间复用，不在请求结束时关池。
- run_http_example 使用现有 HTTPX backend，retry_count=0、max_connections=8、content_decoding=True、verify=True；每次不跟随重定向，总预算 5 秒。状态/内容取实际响应；流在异步上下文内消费、统计和计算摘要，超过 1 MiB 即停止。不能伪造 65536 字节或完整摘要。
- 诊断页面用 replace_html_response 返回结果，Demo HTTP 200 只说明诊断响应送达，不表示上游成功。HTTPResult.outcome 决定面板状态；上游错误/超时和 Demo 自己的权限/CSRF/程序错误分开。程序异常与取消不得吞掉，模板不执行上游 JSON 里的 HTML。
- `tests/test_examples_http.py` 使用真实 TCP 和真实 backend 验证资源、失败与取消。页面还要实际点击，检查状态、翻译、遮罩、侧栏动态进入和其他页面仍可使用；不以直接调用 Python 函数代替 Chrome 操作。

以下是应用扩展时仍需遵守的通用合同，不表示本页已经展示所有 backend、Cookie 登录、Storage 下载或续传：

先选现有 ClientType；普通 API 不需要续传流。明确初始化和 close_client 的拥有者；高频服务复用池，短脚本用 try/finally。没有 `async with MultiHttpClient()`，缓冲响应 json() 不需要 await。

正常调用必须按上游合同检查 status_code/is_success，必要时 raise_for_status，再解析正文。HTTP 200 内的业务错误码仍由业务解释，不交给浏览器 Action Runner。写请求设置 retries=0，除非用户明确提供可重试/幂等设计。

外部 URL、代理、TLS、认证和 Cookie 来自可信配置，不将未经约束的前端 URL 交给后端请求；不共用不同用户的认证 CookieJar。验证真实本地上游的成功、4xx/5xx、超时、取消与关闭，不用只返回固定对象的 mock 宣称网络路径通过。

下载使用 stream 的异步上下文并在其中消费；流不能在退出后继续读取，也不随意重复消费。跨 backend 的业务不读 native_response，不复制 Cookie/解压实现。

## NATS：按真实 Demo 接线

入口是 `from oldman.providers.nats import bus`，进程级具体连接对象，不从 request.app.ctx 取，不在每次请求重新创建。只需要独立通信脚本时才自己创建 NATSConnection 并负责生命周期。不要增加 MessageBus facade、连接代理或第二个注册表。

| Demo 源文件 | 可以直接参考的部分 |
| --- | --- |
| apps/examples/nats_messages.py | 双方共享 MsgspecModel 请求/回复/事件；无联网或 ORM 声明 |
| apps/examples/nats_example.py | 指定节点 RPC、普通事件、publisher、固定两节点手动观察 |
| apps/communication/apps.py、events.py | App 注册及 queue/广播/定向接收；只查真实数据库、固定三个内存计数 |
| services/nats_a.py、nats_b.py | 直接 SimpleApplication 子类、正常等待退出、handler 结束后关闭 DB |
| data/nats_a_settings.example.yaml、nats_b_settings.example.yaml | 接收设置、完整 App 清单、相同 User/数据库；运行 YAML 不提交 |
| apps/examples/forms.py、views/communication.py、templates/pages/examples/communication/ | 真实选项、staff/CSRF、部分失败、现有 Form/Actions/loading/翻译 |
| apps/examples/tasks.py::project_rpc | 已开启的 Taskiq 执行子进程中调用同一共享发送函数 |

为应用实现时按以下顺序：

1. **选对机制。** 在线询问/事件用 Core；持久排队、定时和任务结果用 Taskiq；浏览器实时输出用 SSE。不能因为底层同是 NATS 就共用 subject、Client、ACK 或结果协议。
2. **配置当前服务。** nats 定义地址/凭据，nats_bus 显式 enabled、nats_alias、namespace；需要接收才 consume=true，定向接收填 peer_id。普通 Web/Simple 能接收；Worker/Scheduler/命令只发送。禁用不联网；init/sync 不校验服务器是否在线，不改用户已有值。
3. **分开消息与接收声明。** 共享消息继承 MsgspecModel，方法放普通模块。接收函数放已安装 App 的 events（events_module 默认值），使用 @bus.subscriber。Registry 只精确导入这些模块；不要在发送模块手动 import events。模型由模型阶段加载，events 不建表/不建连接。
4. **明确路由。** 默认走 shared，peer=True 接收本地配置身份的定向消息；发布/请求的 peer_id 是目标，handler 顶层 peer_id 是来源。身份保持大小写，不从 name/PID 猜。一个目标有多个副本且不希望全部执行时用相同 queue；无 queue 就是每个在线订阅一份。RPC 只取一个回复，不偷偷实现节点发现/结果汇总。
5. **复用生命周期。** Simple/Web 在业务启动后才接收，结束 handler 后才执行业务资源清理，最后关闭 Core。Taskiq 原生 startup/shutdown 期间 Core 可用，执行父进程不连接。业务不手动调用私有阶段方法；独立脚本 start/stop、Shell async with 的区别见开发者参考。不要在运行中的服务里再次 async with bus。
6. **保持真实失败。** 只把已知通信错误映射为可读 UI；无响应者、超时、缓冲满、永久关闭、解码/程序异常不可变成成功。timeout 不撤销远端副作用，不自动重发写操作。返回 found=False 是业务结果，不能跟服务器离线混为一谈。来源 header 和 namespace 不替代权限/ACL。
7. **不改无关热路径。** 模型/装饰器注册时准备签名，消息直接 bytes；不增加每条消息配置扫描、临时连接、JSON 字符串中转、flush、数据库计数、后台轮询或事件持久化。publisher 只发布非 None 返回值，先等发布完成再返回；不是数据库事件钩子。

最少验收：使用自有 NATS 与两个真实接收进程，验证数据库回复/PID、同 queue 合计一份、广播各一份、不同 namespace 不串收；再测离线/超时/停止时 handler 的依赖仍可用。Web 界面还要真实点击，核对翻译、权限/CSRF、遮罩和结果归属。源码更新后使用当前构建，不能把用户旧 static 的现象直接当源码回归，也不能未经授权覆盖用户 static。

精确默认值、原生透传、关闭等待与 TLS 失败限制见[provider 参考](../developers/providers.md#nats-连接与发布)。正常等待到期不是无条件强退；不得为测试通过吞取消或用清理时强杀代替正式 stop 通过。

## Redis 订阅

Redis Pub/Sub 的 DB 编号不隔离 channel；按环境/项目命名 channel。PubSub 及读取任务先关闭，再关闭 provider。不要为发布示例使用业务现存 channel 或向真实用户发送通知。

验证使用隔离服务器和 subject/channel，检查实际接收、类型、超时或无接收方，确认结束后没有悬挂订阅。没有真实 broker 时明确标注验证限制，不把装饰器存在当作完成投递测试。
