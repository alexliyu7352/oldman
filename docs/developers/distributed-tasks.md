# Taskiq 接口与运行时

先从[用户教程](../users/distributed-tasks.md)运行 EPG Demo。本页说明对象从哪里来、谁打开和关闭连接，以及维护时不能改变的边界；不是另一个执行引擎。

## 公开对象和导入时机

```python
from oldman.runtime import TaskiqWorkerApplication, TaskiqSchedulerApplication
from oldman.tasks.distributed import broker, schedule_source
```

前一行可用于配置尚未加载时的服务声明；后一行必须在服务 bootstrap 后，且 `settings.taskiq.enabled=true`、namespace 已配置。`broker` 是当前进程唯一的真实 TaskiqBroker 实例，`schedule_source is broker.schedule_source`；不是代理，不从 request.app.ctx 取得，不在每次发布时新建。

broker 继承已安装的 PullBasedJetStreamBroker，保留原生 `task` 装饰器、kicker、`.kiq()`、任务依赖与结果对象。schedule_source 继承 ListRedisScheduleSource，保留原生 ScheduledTask 格式。应用不直接实例化这些内部子类来建立第二套全局对象。构造只创建对象/池，不连接网络；连接必须由下面的生命周期打开。

## App 与服务加载

AppConfig 的 `tasks_module` 默认 `"tasks"`，语义与 models/views 一致：没有默认模块可跳过；存在但内部 import 失败原样报错；不能设 None。Registry 的 `load_tasks()` 只精确导入已注册 App 的模块，要求模型阶段已完成，重复调用不重复导入，拒绝任务模块另外声明数据库表。不扫描所有项目文件，不自动安装额外 App。

| 所属进程/入口 | Taskiq 行为与关闭责任 |
| --- | --- |
| Worker 管理进程 | 静态发现/配置/模型后启动原生 ProcessManager；自己不打开 broker、数据库或 HTTP |
| Worker 执行子进程 | spawn 后 bootstrap 自己的服务；先设置 is_worker_process，再初始化 Storage、加载 tasks；创建原生事件循环、startup、报告 ready、执行原生 Receiver；退出关闭 broker 和框架 DB/Cache/Redis |
| Scheduler | TaskiqSchedulerApplication 继承 SimpleApplication，标记 is_scheduler_process、加载 tasks；原生标签来源和公共 Redis 来源交给原生 SchedulerLoop；只投递，不执行任务 |
| 普通 Web | 每个 Sanic worker 的异步生命周期启动/关闭 broker，不自动扫描全部 tasks；业务视图按需显式 import 任务 |
| 普通 SimpleApplication | 在已有 before_start/main/停止链路外包住 broker 生命周期，不替应用创建 Worker；业务显式 import |
| 一次性 App Command | bootstrap、模型、命令阶段之后，异步命令执行的生命周期负责 broker；不启动 Web/Worker/Scheduler |
| Shell/IDE | bootstrap 只准备配置和模型；调用者在实际事件循环中 `async with broker`，退出后关闭。干净关闭后可在新循环再用；不能嵌套或并发重复 startup |

Worker/Scheduler 默认只自动加载自己的任务 App，Web 不会为了发送一个任务导入所有未用任务。普通 Web、Simple 和 App 命令的既有业务资源责任不因此转移；业务自行创建的 HTTP/NATS Client 仍由业务关闭。覆盖 Web 的异步生命周期必须保留 super。专用 Worker 的共享 DB/Redis/Cache 由框架收尾，不能每条任务关闭全进程池。

### 任务内 Core NATS 通信

启用 settings.nats_bus 后，Worker **执行子进程**在 Taskiq broker.startup 及 WORKER_STARTUP 之前打开 Core，原生任务和 WORKER_SHUTDOWN 结束后才关闭；管理父进程不连接。Core 与 Taskiq 建连共用该次 taskiq.startup_timeout 总预算，不叠加两个 30 秒；Core 自己较短的 startup_timeout 仍生效。首次失败依旧受原有启动尝试控制，运行保活与任务协议不变。

Scheduler 先打开 Core，再进入原生 Taskiq startup/CLIENT_STARTUP 和 SchedulerLoop；原生 CLIENT_SHUTDOWN 后才关闭 Core。它没有 Worker 的父进程首次 ready 截止，因此先执行 Core 预算，再按原规则执行 Taskiq 的启动尝试。两种专用服务都**只发送**，不因为 consume=true 自动加载 events；只需接收事件/RPC 的服务使用普通 SimpleApplication。

失败/取消同样尝试关闭；专用服务在原 Taskiq shutdown 之后收尾框架 DB/Cache/Redis/Core，现有 shutdown_timeout 和整组 stop_timeout 仍有效。不是把 bus.stop 注册为业务钩子然后假定它最后执行，也不复制原生 Receiver/ProcessManager。Taskiq 与 Core 即使共用 nats_alias/namespace 字符串，仍使用不同 Client 和 oldman.taskiq / oldman.bus subject，不混用 ACK、续期、结果或缓冲。

实际例子是 Demo apps/examples/tasks.py::project_rpc：任务调用 nats_example.query_project_status，返回真实回复和 worker_pid。Web、Worker 开启 nats_bus，nats_a 在线后，在 /examples/tasks/results 投递并查询；不用 Scheduler，也不在任务中再次启动 bus。该任务无自动重试，远端离线作为任务失败由原结果路径展示。完整准备和源码见[通信教程](../users/service-communication.md#5-从-taskiq-任务中调用-rpc)。

Shell 中可以使用 Demo 的实际任务（交互说明，不是 Demo 另一个脚本文件）：先在 Demo 根执行 `context = bootstrap_service("task_worker")`，再导入 `apps.examples.tasks.project_summary`；在自己的 async 函数中进入 broker 上下文并 `.kiq()`。这只发布，仍需另一进程运行 Worker。不能在已启动的 Web 生命周期内再套 `async with broker`。

## 配置与默认值

类型为 `oldman.conf.schemas.TaskiqConfig`。所有秒数是正数，namespace/queue 为单个安全 subject 片段；完整 YAML 生成和 App 配置仍由现有 SettingsManager 管理，不新增环境变量或任务专用配置系统。

| 字段 | 默认 | 作用 |
| --- | --- | --- |
| enabled / namespace | false / None | 显式启用，启用时 namespace 必填 |
| nats_alias / redis_alias | DEFAULT / DEFAULT | 已配置命名连接；Redis 同时用于结果与动态计划 |
| consume_queues | `["default"]` | 同一组执行进程监听的队列，非空且不重复 |
| workers / max_async_tasks / max_prefetch | 2 / 100 / 0 | 执行进程数、每进程总并发、额外 Receiver 接纳槽 |
| startup_timeout / startup_attempts | 30 / 3 | 单次初始化预算、初始次数含第一次 |
| shutdown_timeout / stop_timeout | 5 / 60 | 资源关闭预算、服务停止总预算 |
| ack_wait / ack_timeout | 60 / 5 | 服务端确认等待/续期依据、单次完成 ACK 等待 |
| publish_timeout / duplicate_window | 5 / 120 | 单次发布确认等待、服务端发布去重窗口；窗口至少覆盖两次 publish_timeout |
| result_ex_time | 86400 | 写入起结果 TTL，读取不续期 |
| stream_max_bytes / stream_replicas | -1 / 1 | 字节上限（-1 使用服务器限制）；只接受 1/3/5，部署须提供实际节点 |
| max_ack_pending | 1000 | 一条队列跨所有监听进程的未确认数量上限 |
| schedule_update_interval | 5 | 原生计划来源刷新间隔 |

普通非 Web 服务和两种 Taskiq 服务都不自动生成 web 节点；nats/taskiq 属于通用根配置。关闭 Taskiq 时不检查其 alias 是否实际可连接，也不自动导入 distributed。

NATSConnectionConfig 接受 `nats_url`、connect_timeout、reconnect_time_wait、credentials_file、tls_ca_file、tls_cert_file、tls_key_file。URL 的 user/password/token 通过标准 URL 解析解码后独立传给 nats-py；creds 与 URL 身份不能混用。指定 TLS 时创建验证证书和主机名的 SSLContext；客户端证书和私钥成对提供。明文服务器会在携带凭据的 CONNECT 之前被拒绝，重连也不降级。证书路径由部署提供，不打印凭据，不创建不验证证书的兜底连接。

Redis 参数复用 provider 的公共转换，包括重试、协议、连接上限等。Taskiq 为原生结果与调度格式使用二进制响应；即使别名 URL 带 decode_responses=true，也不会把整个 provider 改为二进制。结果和来源各持有独立池，不借用 RedisClientRegistry 的池，也不在关闭 Taskiq 时关闭其他消费者。

## 传输和资源名称

对于 namespace `epg_demo`：

| 资源 | 名称/合同 |
| --- | --- |
| Stream | `oldman_taskiq_epg_demo`，FILE、WorkQueue、DiscardNew、不设消息年龄过期 |
| 持久任务 subject | `oldman.taskiq.epg_demo.tasks.<queue>` |
| 每队列 durable consumer | `workers_<queue>`，明确 ACK，ALL，从所有待处理消息开始，max_deliver=-1 |
| 在线广播 subject | `oldman.taskiq.epg_demo.broadcast.<queue>`，Core NATS，无 queue group、不进 Stream |
| 结果 key 前缀 | `oldman_taskiq_epg_demo_results`，具体拼接由原生 Redis backend 管理 |
| 动态计划前缀 | `oldman_taskiq_epg_demo_schedules`，由原生 ListRedisScheduleSource 管理 |

普通发布者可创建/校验 Stream，不创建 consumer；只有 Worker 创建/绑定 consumer 和广播订阅。已有资源只检查，不 update。并发创建只处理已存在的原生冲突，再读回检查；不以覆盖配置解决冲突，不删除积压。持久任务和普通 RPC/Core subject 不混收；namespace 仅为命名隔离，不替代 NATS/Redis ACL。

## 接收、执行和确认

每个订阅最多一个异步读取槽，合并后交给同一个原生 Receiver，所有队列和广播共用执行限额。`max_prefetch=0` 不表示整个客户端从不持有待执行消息：Receiver 的接纳容量仍为 max_async_tasks，合并器还有每来源至多一个槽；广播原生订阅缓冲上限为 100 条/1 MiB。不要把 max_prefetch 写成 Stream 长度或每队列执行上限。

收到持久消息就创建本次 delivery 的续期协程，等待 Receiver 时也续期，每 ack_wait/3 调用原生 in_progress。只接收 WHEN_SAVED 策略，拒绝提前确认标签。任务仍由原生 Receiver 解析、校验参数、调用依赖、执行、写结果和确认；RenewingReceiver 只在 finally 释放本次续期，不复制其执行逻辑。

完成确认用原生 ack_sync，只有超时才再试一次，最终失败也停止续期；解析/回调异常及停止同样释放。不是失败后永久续期，也不是 ACK 错误时在当前位置重新调用函数。

持久发布的 Nats-Msg-Id 是 subject、task_name、task_id、重试序号的稳定摘要；只在原生 NATS 超时时最多重发一次相同 bytes/标识。容量、权限、无 Stream、编码错误等不按确认超时重试。最终失败通过原生 SendTaskError 暴露，保留 cause。确认丢失时不能声称任务没发送。

普通 JSON 数据、中文、原生时间计划使用 Taskiq 的原生格式与 ORJSON。参数先经过原生模型格式化，不可序列化参数可能在进入 ORJSON 前就抛 PydanticSerializationError；不能承诺所有编码失败都是 TypeError。ignore_result 在结果编码前跳过。结果保存失败的原生行为是记录异常后仍可能 ACK，本框架没有改写该行为；准确场景和业务处理见[重复与结果边界](../users/distributed-tasks.md#6-哪些情况下可能重复怎样处理)。

## 调度与运行中恢复

WaitingScheduler 复用 LabelScheduleSource、公共 RedisScheduleSource 和原生 SchedulerLoop.run。只增加实际发送的跟踪/收尾与一次性失败恢复：pre_send→发布→post_send 任一步失败，记录原异常，让该一次性计划重新具备发送资格；不是另写调度循环。

动态一次性计划在保存前补稳定 task_id，不改显式 ID。interval/cron 不借用这个 ID 固定所有轮次。SmartRetry 使用同一来源，默认不启用 retry_on_error；显式标签才产生延迟重试，保留任务 ID并增加重试序号，中间失败不保存最终结果。广播强制 ignore_result=true、retry_on_error=false，仅规范本次消息，不修改被装饰函数的共享标签。

运行中的临时连接错误由原生重连/来源刷新继续恢复并记录。来源刷新有延迟；读失败期间没有“最新计划已生效”的保证。发送后删除计划失败可导致再次发送；稳定 ID 的去重仍有窗口，不能变成 exactly-once。interval 首轮可立即到期，重启也可能立即再执行；不承诺补发所有停机间隔。取消不撤回已排队消息或已经缓存并开始发送的一轮。

停止时先停原生 loop，再等待已开始的来源刷新和发送（包含 post_send），然后关闭来源/broker。只有 broker 关闭 Redis 来源池，不能 scheduler 和 broker 各关闭一次。没有第二套调度状态表、Leader 选举或多个 Scheduler 去重协议；同 namespace 运行一个 Scheduler。

## 进程与异常收尾

Worker 用 Taskiq 原生 ProcessManager.start；只通过 prepare_workers 和原生 action queue 检查首次 ready。初始每执行位置有限次尝试，全部位置真正连接完成才 ready。正常运行使用原生 max_fails=-1 持续补起崩溃进程，不把首次三次预算套到运行保活。

Worker/Scheduler 共用私有进程组生命周期：保留已有数字 PID 文件，另外记录可核对的组身份。start 持有 PID 锁；stop 先核对身份，再请求停止、等待到总截止时间，必要时杀本服务整个组并核对退出；restart 必须先确认旧组结束。终端 Ctrl+C 通过同一截止机制处理，不发送到调用者的 shell 或无关进程。用户只调用一个 stop，不公开要求第二个 kill 命令。

broker 一次 startup 有总预算；启动异常也进入 shutdown 的五秒默认预算。原生 TLS 部分连接的关闭可能卡住，此时保留连接/证书原始异常，不能用最后的清理超时覆盖它。清理正常后可为新循环重新创建底层资源；清理失败标记不可重用，应退出进程，不静默 reset。专用进程最终退出和“每个库对象优雅关闭成功”必须分开记录。

业务任务等待不套五秒资源预算；服务 stop_timeout 才是整组最终退出边界。正常退出、截止强停、初始化失败分别记录；不能把测试 finally 的 kill 当正常关闭验收。

## 维护与直接验收

实际适配文件为 [broker.py](../../oldman/tasks/distributed/broker.py)、[receiver.py](../../oldman/tasks/distributed/receiver.py)、[results.py](../../oldman/tasks/distributed/results.py)、[scheduler.py](../../oldman/tasks/distributed/scheduler.py)、[worker.py](../../oldman/tasks/distributed/worker.py) 和 [runtime/taskiq.py](../../oldman/runtime/taskiq.py)。协议用原生类型；内部私有字段/钩子不是用户扩展 API。

pyproject.toml 固定 Taskiq 0.12.6、taskiq-nats 0.6.0、taskiq-redis 1.2.3、nats-py 2.15.0；Redis 的声明范围是 `>=8,<9`，本轮实际验证版本为 8.1.0，不能把验证版本误称为安装时的精确锁定。升级时重点核对 Receiver 接纳/ACK/结果失败语义、ProcessManager action 扩展、SchedulerLoop 刷新和停止、Redis 来源关闭，以及 nats-py TLS/close 实例修补；不能只通过 import 就升级。

专项入口 `tests/test_oldman_distributed_tasks.py` 使用 NATS_SERVER/REDIS_SERVER 指定真实二进制，创建自己的端口、目录、namespace。`tests/taskiq_fault_checks.py` 是其故障辅助，不是生产运行器。已有 provider、Cache、Session、SSE 测试串行补查共享 Redis 升级。Demo 的任务函数/真实 SQLite/Storage 测试在其 `tests/test_examples_tasks.py`；浏览器另验真正点击、权限、排队、结果、计划、退出和故障反馈。

已验证的单节点与小并发结果不代表集群容错、任意负载或掉电恢复。未完成项记录在实施/验收文档，不将其写成公开保证。
