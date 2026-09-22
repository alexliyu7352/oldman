# Redis 与 NATS provider

Provider 管理外部基础设施连接，不定义业务消息含义。缓存使用 Redis provider；Session、SSE 也可以使用它，但不是缓存子模块。NATS provider 提供服务之间的发布、订阅和请求响应，不是浏览器通知中心，也不是持久任务调度器。

## Redis 连接

公开对象是 `oldman.providers.redis.redis_client`。下面的 METRICS、read_metric 和 YAML 是 **API 参考**，用于说明命名连接的最小接线，不是 Demo 中已注册的命令或服务。实际业务可对照 EPG [缓存示例](cache.md#demo-中的实际使用)和 [tasks.py 的 retry_summary](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/tasks.py)：前者通过 RedisCache 使用 CACHE，后者通过 `redis_client.using(settings.taskiq.redis_alias)` 使用任务服务的实际别名；不要给 Demo 凭空新增 METRICS 作为运行前置。

```python
from oldman.providers.redis import redis_client


async def read_metric() -> str | None:
    """在已 bootstrap 的服务中读取一个明确命名的业务 key。"""
    connection = await redis_client.using("METRICS").async_get_conn()
    return await connection.get("taskboard:metrics:latest")
```

对应服务 YAML：

```yaml
redis:
  METRICS:
    redis_url: redis://127.0.0.1:6379/6
    decode_responses: true
    max_connections: 32
    connection_socket_connect_timeout: 2
    connection_socket_timeout: 5
```

redis_client 是进程级 RedisClientRegistry。using(alias) 校验并缓存区分大小写的 alias 对象，不建连接池；首次 async_get_conn 创建 redis-py 异步客户端及池，真正网络连接由命令触发。打印 connecting 不等于服务启动时已经完成 Redis ping。

async_get_conn 按 decode_responses 配置返回字符串或 bytes；async_get_bin_conn 强制 bytes，适合 msgspec、Pickle 和 Pub/Sub 二进制消息。同 alias/解码模式复用客户端，不同模式可持有两个池。返回的是 redis-py asyncio Redis，直接 await get/set/pipeline 等公共方法，不再造一层 Redis 命令全集。

### 配置字段

内置 alias 默认值如下；它们是配置默认值，不保证机器上已启动相应 Redis：

| alias | 默认 redis_url |
| --- | --- |
| DEFAULT | redis://localhost:6379/3 |
| CACHE | redis://localhost:6379/2 |
| SESSION | redis://localhost:6379/5 |

三个默认值都走 TCP：Redis 默认不开 unix socket，socket 路径又随发行版和版本变化，所以默认值不能依赖它。已经开启 unix socket 的环境把 `redis_url` 写成 `unix:///path/to/redis.sock?db=3` 即可，TLS 用 `rediss://`。

`redis_client.async_get_conn()` 等不指定 alias 的便捷方法使用 DEFAULT；业务最好明确 using。自定义 alias 必须提供 URL；内置 alias 可只覆盖部分选项。

RedisConnectionConfig 还包括 decode_responses=True、max_connections=1024、health_check_interval=30、protocol=2（可选 3）、retry_attempts=3、retry_on_timeout=True、backoff_base=0.1、backoff_cap=2.0、socket_keepalive=True，以及 TCP keepalive 的 idle=60、interval=10、count=3。池是每进程、每实际客户端的池，不是全项目连接总上限。

其他 redis-py 连接参数使用 connection_ 前缀，例如上述 socket timeout；传给连接池前去掉前缀。不能用它重复声明已有字段或注入另一个 connection_pool/retry 对象。配置检查不代替服务器的地址、凭据和 TLS 连接验证。

### 关闭与独立使用

WebApplication/SimpleApplication 的默认收尾会关闭全局 redis_client。自定义收尾仍须调用父类；不要在每个请求后关闭共享池。PubSub 和自己启动的读取协程先由其拥有者结束，再关闭 provider。

不使用全局 Settings 的独立脚本可以显式创建：

```python
from oldman.conf.schemas import RedisConfig
from oldman.providers.redis import RedisClientRegistry


async def ping_redis(url: str) -> bool:
    """调用者给出地址，本函数拥有并关闭独立 Registry。"""
    registry = RedisClientRegistry(RedisConfig.model_validate({"DEFAULT": {"redis_url": url}}))
    try:
        connection = await registry.async_get_conn()
        return await connection.ping()
    finally:
        await registry.close()
```

也公开低层 AsyncRedis(redis_url=..., ...)，方法为 async_get_conn/close，配置项与上面一致；不需要同时创建 AsyncRedis 和 Registry 两套连接。Registry.close 关闭所有已建客户端，后续使用可重新建池；它不重新加载配置。关闭失败可抛 BaseExceptionGroup。缺 alias 抛 RedisAliasNotConfiguredError，普通连接/命令错误保留 redis-py 异常。

### 锁与发布订阅

alias 对象提供三种已有锁入口，不混用其所有权规则：

- get_db_lock(key, expire_timeout=60) 使用 SET NX EX 返回 bool；is_db_lock 只检查占位，不提供 token 所有权或安全续期。
- acquire_lock(lock_name, acquire_timeout=10, retry_interval=0.001, expire_timeout=None) 返回 token 或 False。`acquire_timeout` 是等多久，`expire_timeout` 是拿到之后持有多久；不传 `expire_timeout` 时沿用 `acquire_timeout`，保持旧行为。临界区可能超过租约时显式给 `expire_timeout`，不要靠把等待时间调长来延长租约。release_lock(name, token) 用原子比较删除，失败返回 False，也可能代表释放时连接失败。
- `await get_locker(key, blocking_timeout=10, expire_timeout=60, sleep=0.01)` 返回 redis-py Lock 对象，尚未获取锁；可使用其异步上下文及原生锁接口。

普通 Pub/Sub 直接通过二进制连接的 pubsub()/publish() 操作，并显式管理 PubSub 的关闭。它不持久保存消息、没有离线补发；**不同 Redis DB 编号不会隔离 Pub/Sub channel**，应用/环境必须通过 channel 名隔离。[Redis Pub/Sub 投递与隔离规则](https://redis.io/docs/latest/develop/pubsub/)

这不是要求浏览器应用自己操作 Pub/Sub：页面实时投递应使用 oldman.web.sse；这里说明的是需要直接调用 Redis 原生命令的 provider 边界。

## NATS 连接与发布

一般 Oldman 应用使用进程级的具体对象：

```python
from oldman.providers.nats import bus
```

它是 NATSConnection 的具体子类实例，不是代理，不来自 request/app.ctx。导入与声明装饰器不联网、不读取尚未初始化的 Settings；第一次异步启动才绑定本服务配置并创建 Client。一个运行进程复用一条 Core 连接，不在每次请求里创建或关闭。独立脚本还可自行持有 NATSConnection，见下文。

实际使用从[Demo 通信教程](../users/service-communication.md)进入。其共享消息/发送方法在 apps/examples/nats_messages.py、nats_example.py，接收函数在 apps/communication/events.py，服务在 services/nats_a.py 和 nats_b.py。下列方法是接口参考，不是另一套虚构 Demo。

### 配置与默认值

`settings.nats` 定义可复用的命名连接，`settings.nats_bus` 决定是否启用 Core 通信。仅填写地址不会自动联网。二者都是通用根配置，不依赖 Web，也不放进 Admin 或某个业务 App。

| nats_bus 字段 | 默认 | 含义 |
| --- | --- | --- |
| enabled | false | 是否由运行入口管理 Core 连接 |
| nats_alias | DEFAULT | settings.nats 中区分大小写的 alias |
| consume | false | 常驻 Web/Simple 是否加载并运行已安装 App 的 events |
| namespace | None | 启用时必填；相互通信的项目/环境必须一致 |
| peer_id | None | 显式本地身份，用于来源 header 和定向订阅 |
| serializer_mode | msgpack | msgpack 或 msgspec_json，两端一致 |
| startup_timeout | 30 | 首次建立发送连接的总预算，秒 |
| graceful_timeout | 10 | 停止时所有 handler 共用的正常完成等待时间，秒 |

namespace/peer_id 不改大小写，非空值只允许 ASCII 字母、数字、下划线、连字符。不从服务名、连接日志名或 PID 推断身份。启用时校验 alias 存在；关闭时可保留配置，但非法字段值仍要修正。

命名连接 DEFAULT 默认 nats://localhost:4222；新增 alias 必须填写 nats_url。NATSConnectionConfig 的其余字段：

| 字段 | 默认 / 约束 |
| --- | --- |
| connect_timeout | 2 秒，一次原生连接尝试的超时 |
| reconnect_time_wait | 2 秒，原生重连间隔 |
| tls_ca_file | None；指定时信任该 CA，否则 TLS 使用系统信任 |
| tls_cert_file / tls_key_file | 均 None；双向 TLS 时必须成对提供 |
| credentials_file | None；原生 .creds 文件，与 URL 身份互斥 |

URL 接受 nats://、tls://，不接受 query、fragment 或业务路径。可以写百分号编码的 user:password@host，或 token@host；框架将身份从服务器地址拆出后传给 nats-py，不以地址日志打印凭据。不要把带凭据 URL 或配置 dump 到日志。配置检查不读证书、不连接服务器；实际启动才读取部署提供的证书/creds。

tls:// 或证书配置启用验证证书/主机名的 TLS，不提供关闭验证的兜底；若服务器只支持明文，在发送含身份的 CONNECT 前拒绝，重连同样不能降级。命名连接可以同时供 Taskiq 和 bus 读取，但各自持有 Client 和资源；不是复用 Taskiq 私有 socket。

### 精确 API

```python
def __init__(
    self,
    servers=("nats://localhost:4222",),
    name="nats-service",
    serializer_mode="msgpack",
    *,
    namespace=None,
    peer_id=None,
    startup_timeout=30.0,
    graceful_timeout=10.0,
    **broker_kwargs,
) -> None:
    ...
```

构造时允许先不填 namespace，连接或寻址前必须填写；name 只用于连接/日志标签。超时必须为有限正数。独立对象不自动读取 Settings，也不由 Application 关闭。默认重连 allow_reconnect=True、max_reconnect_attempts=-1、reconnect_time_wait=2；显式 broker_kwargs 可覆盖默认原生参数，包括回调，重复参数不会在两套 kwargs 中相撞。FastStream 未直接暴露的 Client.connect 参数（例如 tls、user、password）也传给真实 Client；业务不应为传一个选项复制 broker。

| 方法 | 合同 |
| --- | --- |
| await publish(message, subject, *, peer_id=None, **kwargs) | message 为 MsgspecModel 或已编码 bytes；返回 None，不等接收业务完成 |
| await request(message, subject, reply_type, *, peer_id=None, request_timeout=5.0) | 等一个回复，按指定 MsgspecModel 子类解码；不汇总多个节点 |
| subscriber(subject, *, peer=False, **kwargs) | 装饰异步 handler；queue、max_workers、Depends、原生路径参数等交给 FastStream |
| publisher(subject, **kwargs) | 装饰异步函数；返回非 None 时 await publish，再返回同一对象；None 不发布 |
| peer_id(nats_msg) | 静态方法，从原始消息 header 取来源；没有则空字符串 |
| connection_info | servers/name/is_connected 快照，读真实 Client 状态；不是消息回执 |
| await start() | 连接并启动此前声明的订阅 |
| await stop() | 停止收件、等待 handler 退出，再结束连接 |
| async with connection / bus | 只连接以便发送/RPC；退出关闭，不启动接收声明 |

publish 原生 headers 会复制；框架独占 x-nats-peer-id 来源键，调用方不能用 headers 冒充另一来源。reply_to 等其他发布参数透传，不另建消息 envelope。

注册必须在接收启动前完成；嵌套/并发启动同一对象报错。一个已开启的连接允许并发 publish/request。正常关闭后同一对象可在新事件循环重新使用；失败清理的对象不再重开，应结束所属进程。运行中的应用不要再包一层 async with bus。

### 寻址、来源与 queue

两端使用相同 namespace。例如 Demo 的 epg_demo：

| 调用或声明 | 实际 NATS subject |
| --- | --- |
| publish(message, "demo.events.compete")；默认 subscriber 同业务名 | oldman.bus.epg_demo.shared.demo.events.compete |
| request(..., "project.status", ..., peer_id="monitor_a") | oldman.bus.epg_demo.peer.monitor_a.project.status |
| monitor_a 的 subscriber("project.status", peer=True) | oldman.bus.epg_demo.peer.monitor_a.project.status |

peer=True 使用接收方配置的 peer_id，未配置会启动失败；发送的 peer_id 参数是**目标**。handler 的顶层参数 peer_id 是**来源**，由本方发送配置写入，不取目标或 name。消息正文里的同名字段保持原数据，不被注入覆盖。

普通 subject 由非空点分 token 构成；不能有空白/控制字符，发布不能含通配符。订阅允许原生完整 token 的 *、末尾 > 以及 FastStream 路径参数。不要手工重复拼 oldman.bus 前缀。

- 同 subject、同 queue 的接收者竞争一份；不是每人一份，也不保证均分。
- 同 subject、不填 queue：所有在线订阅者各收到一份。
- 不同 queue group 各获得一份，同组内部竞争。
- 同 peer 多副本仍是多个订阅者。需要一次 RPC 只由其中一个处理，就配置同 queue；不加 queue 可能每个都执行，而调用者只拿第一个回复。
- namespace 是命名隔离；peer header 是来源信息。都不能替代 NATS 账号/ACL、连接认证或业务授权。

### 强类型消息与原生能力

消息继承 `oldman.serializers.MsgspecModel`，不是动态 dict 协议；调用者直接交模型，不先 to_json_str。msgpack 使用 to_msgpack 的 MessagePack bytes，msgspec_json 使用 to_json_bytes 的 UTF-8 JSON bytes。手工传 bytes 表示调用者已经按所选 codec 编码，不会再包一层。其他语言可互通，但必须约定字段、类型与 MessagePack 扩展类型，不能仅凭“都是 JSON/MessagePack”保证业务兼容。

接收端先解出 bytes，再按 handler 参数类型做 msgspec 转换。参数模型在声明阶段创建；现有 Depends、keyword-only、NatsMessage 注入及原生路径参数保留，不把所有参数当正文字段。未知格式 bytes 不会凭空成为合法业务模型；request 坏回复保留解码异常。handler 的返回模型作为 RPC 回复；若同时需要发布返回值，subscriber 放在 publisher 外层。

Demo 实际共享方法（nats_example.py 节选）：

```python
from oldman.providers.nats import bus
from apps.examples.nats_messages import ProjectStatusRequest, ProjectStatusReply

async def query_project_status(project_id: int, peer_id: str) -> ProjectStatusReply:
    """The selected receiving service, not this caller, queries the database."""
    return await bus.request(
        ProjectStatusRequest(project_id=project_id), "project.status", ProjectStatusReply,
        peer_id=peer_id, request_timeout=3,
    )

@bus.publisher("project.status.read")
async def query_and_publish_status(project_id: int, peer_id: str) -> ProjectStatusReply:
    """Publish the real RPC reply, then return that same reply to the caller."""
    return await query_project_status(project_id, peer_id)
```

函数本身异常不会发布；发布异常也向调用者传播，不悄悄创建后台 Task。publisher 不是数据库提交钩子；需要数据库事务完成后再发事件，业务自己在事务上下文结束后调用。

### App 与运行生命周期

AppConfig.events_module 默认 "events"，只从 settings.apps 显式安装的包加载，不扫描工程目录。默认模块不存在正常跳过；模块内部缺依赖等真实异常上抛。模型先加载，events 不声明新表，不连接服务；应用发送方法/消息定义放在可独立导入的普通模块中，不能为调用一个 RPC 先导入全部接收函数。

| 入口 | 连接与接收顺序 | 退出顺序 |
| --- | --- | --- |
| 普通 Simple | init/模型、events 声明（启用且 consume）、prepare；异步 Core 连接 → Taskiq 发布连接 → before_start → Core 接收 → main | 停止 Core 收件并等 handler 退出 → before_stop/after_stop → Taskiq shutdown → Core 关闭 |
| Web | 初始化阶段仅声明 events；实际 Sanic worker 内 Core → Taskiq → before_server_start；after_server_start 返回后才开始 Core 接收 | 实际 worker 内先结束 Core handler → before_server_stop/after_server_stop → Taskiq shutdown → Core 关闭 |
| 普通异步 App Command | Storage → Core → Taskiq → before_command → handle；不自动加载 events、不接收 | after_command → Taskiq shutdown → Core 关闭 → 日志收尾 |
| Taskiq Worker 执行子进程 | Core → Taskiq 原生 startup/WORKER_STARTUP → ready/Receiver；仅发送 | 原 Taskiq 执行/收尾及 WORKER_SHUTDOWN 完成后关闭 Core |
| Taskiq Scheduler | Core → 原生 Taskiq startup/CLIENT_STARTUP → SchedulerLoop；仅发送 | 原 Scheduler/Taskiq CLIENT_SHUTDOWN 后关闭 Core |
| bootstrap/Shell/IDE | bootstrap 只配配置和模型；用户的 async with bus 才连接 | 退出上下文关闭；其他所用资源由调用者负责 |

Taskiq 管理父进程不连接 Core；Worker/Scheduler 即使配置 consume=true 也不自动加载 events。需要后台接收服务时用独立 Simple，不把每个执行 Worker 变成 RPC 接收者。

Worker 内 Core 与 Taskiq 建连共用原有 taskiq.startup_timeout 总预算，不能两个默认 30 秒相加；Core 自己的较短预算仍有效。Scheduler 没有 Worker 首次 ready 父进程预算，先执行 Core 自己的连接预算，再保留原 Taskiq 启动尝试。启动或业务钩子失败仍尝试关闭本入口已建立的通信资源；原始异常保留，额外清理失败另记日志。

启用的连接初次失败是该入口的启动失败，不会伪装可用。禁用 bus 不加载 events、不新增 Core Client。Web 子类继续保留既有 super 调用；框架不会发现并关闭任意自建业务资源。尤其 handler 使用数据库/HTTP 时，其资源不能在 handler 退出前关闭。业务停止钩子仍可通过 Core 向其他尚在线的节点发送，但已停止的本地 subscriber 不再接收。

### 停止、失败与保证范围

graceful_timeout 是所有在途 handler **共用**的正常完成等待期，不是每个订阅各等一遍。到期后原生订阅停止并取消未完成 handler，框架等待其异步 finally 结束；然后做最终 Client drain/close。最终 drain 另有 10 秒等待，超时会取消并等待该清理任务，不留下 shield 的悬空任务。

这不是“整个服务一定 10 秒退出”：Python 是协作取消，业务不能阻塞事件循环或吞掉 CancelledError，自建 I/O 也要有超时。本 API 不给普通 Simple/Web 增加 Taskiq 的进程组强杀协议。

| 情况 | 调用者应理解的结果 |
| --- | --- |
| 初连拒绝、认证/TLS 失败、启动超时 | 启动异常；超时尽量保留最后的原生连接原因，清理部分 Client |
| 连接建立后断线 | 使用原生重连与缓冲；不代表每条消息已处理 |
| 重连发送缓冲满 / 连接永久关闭 | publish 上抛 OutboundBufferLimitError / ConnectionClosedError，不记录后丢弃却返回成功 |
| 无响应者 | request 上抛 NoRespondersError，检查目标、namespace、服务与订阅 |
| RPC 超时或调用者取消 | 原异常/取消向上；远端可能已执行或仍在执行，不自动重发 |
| 接收 handler 程序异常 | 接收日志记录；没有跨进程异常对象协议，调用端可能只看到超时 |
| 坏回复 | msgspec 解码/验证异常，不伪装空结果 |
| 停止时发送失败 | 仍尝试清理连接，不把资源关闭误称为消息已送达 |

Core 是在线事件/RPC，不持久保存离线消息，没有处理 ACK、重试队列、群体 RPC、节点目录或重放；publish 返回只表示本地发送步骤完成。需要可靠排队、延迟/周期执行和任务结果使用 [Taskiq](distributed-tasks.md)；浏览器实时投递使用 [SSE](sse.md)。

原生扩展实际经 FastStream 0.7.1、fast-depends 3.0.8、nats-py 2.15.0 检验；nats-py 依赖固定版本。关闭、请求 Future 清理、TLS 防降级修补只安装到 Oldman 持有的 Client，不修改原生类/其他客户端。升级时必须复核相应私有扩展点与真实连接专项。已知原生 TLS 失败清理仍可能产生超时及旧 StreamWriter 警告；不承诺所有失败对象都可无警告优雅重用。实际验收版本及限制见[本轮报告](../internal/2026-09-11-nats-events-rpc-validation.md)。

### Shell、IDE 与独立连接

在 Demo 根目录的解释器中，先启动 nats_a，按教程准备本服务 YAML；交互使用真实消息类型：

```python
import asyncio
from oldman import bootstrap_service
from oldman.providers.nats import bus
from apps.examples.nats_messages import ProjectStatusRequest, ProjectStatusReply

context = bootstrap_service("web")  # 配置/模型，不联网

async def query(project_id: int) -> ProjectStatusReply:
    """调用方选取 Demo 中实际存在的项目 ID。"""
    async with bus:
        return await bus.request(
            ProjectStatusRequest(project_id=project_id), "project.status", ProjectStatusReply,
            peer_id="monitor_a",
        )
```

普通 Shell 执行 asyncio.run(query(实际项目ID))；已有事件循环的 IDE 用 await query(实际项目ID)，不要嵌套 asyncio.run。上下文只发送，不因为 web/nats_a 配置有 consume 就自动接收。bootstrap 也不为你关闭后来自行使用的 DB、Redis、HTTP 或 Storage 资源。

不需要全局 Settings 的独立脚本只替换上例的持有对象：

```python
from oldman.providers.nats import NATSConnection

connection = NATSConnection(
    servers=["nats://127.0.0.1:4222"],
    namespace="epg_demo", peer_id="manual_reader",
)
```

在同一 query 函数改用 async with connection、connection.request 即可；Demo 接收服务与消息结构不变，不要求为通信独立脚本 bootstrap Web。需要自己接收则在连接启动前声明 @connection.subscriber，业务资源准备好后 await connection.start()，finally 中先 await connection.stop()、再关闭 handler 依赖。不能用 async with 代替接收启动，也不能让 Application 误以为独立对象由全局 bus 代管。
