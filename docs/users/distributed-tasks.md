# 分布式后台任务

Taskiq 用来把一个异步函数交给后台执行。Web 请求负责投递，Worker 负责执行，Scheduler 负责到期投递。它与进程内 `asyncio.create_task()`、固定的长期 Worker、浏览器 SSE 是不同能力。

当前组合是 **Taskiq + NATS JetStream + Redis**：JetStream 保存待处理任务；Redis 保存结果和动态计划。无需安装 Celery、RabbitMQ 或另一个 Redis 任务 broker。Python 依赖随 Oldman 安装；NATS 和 Redis 是需要单独部署的服务。

本章直接对应 EPG Demo 的 [tasks.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/tasks.py)、[任务视图](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tasks.py)、[Worker 服务](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/task_worker.py)和 [Scheduler 服务](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/task_scheduler.py)。先完成[Demo 安装与数据准备](getting-started.md)，不要在框架仓库运行这些业务命令。

## 1. 配置三个独立服务

Demo 已提供 `web`、`task_worker`、`task_scheduler` 的 example YAML。先按运行教程从样本准备包括两个 Core 接收服务在内的五份配置，再执行项目迁移；本章只启动需要的三个任务相关服务。已有文件用 sync 补字段，不能覆盖原有数据库、密钥或连接：

```sh
./run.sh task_worker settings sync
./run.sh task_scheduler settings sync
./run.sh web settings sync
```

配置已从样本创建，不对已存在文件重复 init。sync 保留已有值，因此原来 taskiq.enabled=false 的服务不会被自动开启。

下面以 Worker example 的连接和 Taskiq 部分为例，不是整个文件。Web/Scheduler 使用同一 namespace 和连接别名；workers、max_async_tasks、max_prefetch、consume_queues 是 Worker 的消费设置，不要求只发布的服务复制它们：

```yaml
nats:
  TASKIQ:
    nats_url: nats://127.0.0.1:4222
redis:
  TASKIQ:
    redis_url: redis://127.0.0.1:6379/7
taskiq:
  enabled: true
  namespace: epg_demo
  nats_alias: TASKIQ
  redis_alias: TASKIQ
  consume_queues: [reports, exports]
  workers: 2
  max_async_tasks: 3
  max_prefetch: 0
```

`TASKIQ` 是这里显式新增的连接别名，不是框架自动猜出来的连接。三者必须连接同一个 NATS、使用相同 namespace；需要互读结果和计划时，Redis 的地址、数据库编号也必须一致。框架默认 disabled、没有 namespace；启用时必须填写 namespace，只允许英文字母、数字、下划线和连字符。

Worker/Scheduler 的实际 App 清单是 `oldman.auth`、`apps.auth`、`apps.examples`；Auth 选择 `apps.auth.models.OldmanUser`，数据库与 Web 相同。完整文件分别是 [task_worker_settings.example.yaml](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/task_worker_settings.example.yaml)、[task_scheduler_settings.example.yaml](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/task_scheduler_settings.example.yaml)。不要复制 Web 的所有 App 和 views 作为后台任务前置。导出任务使用 Worker 配置的 `storages.default`；不同机器需要按业务选择可共享的存储，不会自动同步本机 media。

检查后分别在三个终端启动：

```sh
./run.sh task_worker settings check
./run.sh task_scheduler settings check
./run.sh web settings check
```

```sh
./run.sh task_worker start
```

```sh
./run.sh task_scheduler start
```

```sh
./run.sh web start
```

NATS 必须开启 JetStream，并为其文件存储配置持久目录和容量。生产环境按实际地址设置认证/TLS，不能把 Demo 的无认证回环地址用于公网。Taskiq 启用后，服务会在自己的生命周期中检查所需 NATS 和 Redis；不是直到第一条任务才发现配置不可连接。只想看其他页面时，可显式关闭 Web 的 Taskiq；任务页会显示启用说明。Demo 也启用了独立的 nats_bus，仅关闭 Taskiq 仍需要 NATS；不试用两种通信能力时同时关闭。任务内 RPC 的接收服务与操作见[通信教程](service-communication.md#5-从-taskiq-任务中调用-rpc)。

`run.sh` 只是命令入口，Web 不会替你启动 Worker/Scheduler。同一个 namespace 只部署一个 Scheduler；仅添加更多 Worker 不需要添加 Scheduler。

## 2. 操作真实页面

默认 Web 地址 `http://127.0.0.1:17998`，使用 active staff 账户登录。数据来自 Demo fixture，不是临时拼出来的固定返回值：

| 页面 | 真实操作与观察 |
| --- | --- |
| `/examples/tasks/results` | 选项目，投递摘要，再点查询；导出写入 Storage；故意失败展示 Worker 异常；忽略结果展示不保存结果的任务 |
| `/examples/tasks/schedules` | 20 秒后执行一次、取消计划、60 秒周期、每两分钟 cron、首次故意失败后重试 |
| `/examples/tasks/queues` | reports/exports 共用执行进程；普通刷新只在一个进程执行，广播看每个在线进程 PID 日志；重复完成同一业务记录时第二次 changed 为 false |

页面 GET 不创建任务或计划。动态计划只由按钮创建，最多保留十个属于当前用户的演示计划；用页面取消不再需要的计划。固定的 `refresh_project_counts` 每 300 秒刷新进程内统计，无数据库写入；Scheduler 启动后 interval 首轮可能立即执行。

可以先停止 Worker、保留 Web，投递后记录 ID，再启动 Worker 并查询同一 ID，观察真实排队。不要停止共享设施或其他人的服务来试故障。页面不会持续轮询，也没有全局任务历史表；刷新页面可能丢掉上次结果面板，任务本身不会因此取消。

## 3. 函数、投递和结果

Demo 的任务函数使用真实 `from oldman.tasks.distributed import broker`，通过 `@broker.task(queue_name="reports")` 装饰 `async def project_summary(...)`。它在 `db_manager.get_read_session()` 中读取 ExampleProject 和关联任务数，返回普通字典。完整函数见本章开头的 tasks.py；参数传记录 ID，不传 request、ORM 实例、连接或上传对象。

下面是 Demo `example_task_run()` 内实际投递语句的节选，不是一个可单独执行的脚本。`tasks` 来自 `apps.examples`，`identifier` 是本次生成并已登记当前用户归属的 UUID，`project_id` 已经校验并确认存在：

```python
await tasks.project_summary.kicker().with_task_id(identifier).with_labels(ignore_result=ignored).kiq(
    project_id, fail=operation == "fail"
)
```

没有这些定制需求时，原生简写是 `job = await project_summary.kiq(project_id)`。**这个 await 等的是投递确认，不是函数执行结果。** 普通任务一次由一个监听该队列的 Worker 执行，不是每个 Worker 都执行。

查询视图直接使用 broker 的原生结果 backend。下面节选中的 task_id 已通过当前用户归属检查；broker 已由 Web 生命周期启动：

```python
from taskiq_redis.exceptions import ResultIsMissingError
from oldman.tasks.distributed import broker

try:
    result = await broker.result_backend.get_result(task_id)
except ResultIsMissingError:
    return await _result(request, outcome="unavailable", **owned)
```

`_result` 和 `owned` 是 Demo 视图中的渲染助手与归属数据，不是框架 API。它随后检查 `result.is_err`，分别显示 `return_value` 或 `error`。非 HTTP 调用需要等结果时，也可以用原生 `await job.wait_result(timeout=...)`；Demo 的浏览器请求不这样等待耗时业务。

结果默认从写入起保留 86400 秒（24 小时），由 Redis TTL 自动删除；查询不续期。查不到可能是尚未完成、已过期、明确忽略结果、结果写入失败，或用错 namespace/Redis。**不能据此判断任务仍在运行，也不能自动重新投递。** Demo 一次读取并处理不存在，不使用先 EXISTS 再 GET 的过期竞态；真正的 Redis/解码错误仍上抛。

`ignore_result=True` 可声明在装饰器，或像上面一样针对一次 kicker 设置；它只跳过结果存储，不取消函数执行。不要等待这种任务的返回值。任务失败仍记录日志；普通业务异常默认不自动重试。

## 4. 队列、并发和广播

Demo 两个 Worker 进程各允许三个并发任务，总执行上限是六个，reports 和 exports 共享这个上限，不会每条队列各有六个。没有空闲位置时，任务继续排队；空队列不会阻塞另一条队列。

不要混淆三个量：

- `max_async_tasks`：每个进程同时执行多少个 Taskiq 函数。
- `max_prefetch`：原生 Receiver 额外接纳的等待任务数，默认零；各订阅还最多有一个合并读取槽，广播另有有界收件缓冲。它不是队列总容量。
- `stream_max_bytes`：JetStream 保存任务的字节上限，默认 -1，最终仍受服务器/账户容量限制。满时拒绝新投递并报错，旧积压不会为了新任务被删除。`max_ack_pending` 则限制一条队列尚未确认的任务数，默认 1000，不是执行并发。

直接 `await project_summary(project_id)` 是普通函数调用，占用父任务当前的执行位置；Demo 的 export_project 就这样复用摘要。`await project_summary.kiq(project_id)` 则是另投递一个任务，子任务也要排队。所有位置都被等待子任务结果的父任务占住时会互相等，避免这种设计；可拆队列对应不同 Worker 服务，或不在父任务内等待。

任务内部自行创建 asyncio task 或框架后台协程，不受 Taskiq 的并发上限单独管理，也不是持久任务；业务应等待和清理自己创建的协程，不能借此绕过容量或认为进程退出会自动补执行。

Demo 的普通刷新与广播使用同一个已注册函数，以下是视图的实际调用；operation 已被限定为 local 或 broadcast：

```python
await tasks.refresh_project_counts.kicker().with_task_id(identifier).with_labels(broadcast=operation == "broadcast").kiq()
```

广播使用独立 Core NATS subject，不写任务 Stream，没有队列组；每个**在线且监听该 queue_name** 的执行进程取得一份。它强制不保存结果、不自动异常重试。掉线期间不补发，慢消费者缓冲满会丢消息并记录错误。发送成功只表示与服务器的发送/flush 完成，不表示所有 Worker 都执行成功；不适合必须逐个确认的业务。

## 5. 调度、取消和显式重试

Demo 视图通过 `from oldman.tasks.distributed import schedule_source` 使用唯一动态来源，不自己创建 RedisScheduleSource。其实际调用分别是 `schedule_by_time`、`schedule_by_interval`、`schedule_by_cron`；例如一次性计划：

```python
await tasks.project_summary.kicker().with_task_id(identifier).with_schedule_id(identifier).schedule_by_time(
    schedule_source, dt.datetime.now(dt.UTC) + dt.timedelta(seconds=20), project_id,
)
```

这里 dt 是 `import datetime as dt`，时间用明确 UTC。取消是 `await schedule_source.delete_schedule(schedule_id)`；Demo 先校验此计划属于当前用户，再删除自己的归属记录。取消只删除未来计划，不撤回已经投递的任务；Scheduler 刷新之前已经缓存的那一轮也可能发送。默认来源刷新间隔五秒，不保证精确定时到毫秒，也没有补齐停机期间每一个 interval 的承诺。

固定计划写在 task 的 `schedule=[{"interval": 300}]` 标签中，随 Scheduler 启动读取；改代码后重启 Scheduler。动态 interval/cron 保存在 Redis，直到显式取消；一次性发送成功后由来源移除。Redis 的持久化、备份和淘汰策略影响计划是否存在，不能用结果的 24 小时 TTL 理解全部计划。

Demo `retry_summary` 使用 `retry_on_error=True, max_retries=3, delay=5`，第一次在真实 Redis 计数后故意抛错，Scheduler 随后投递重试，第二次读取真实项目。它的计数只用于演示首次失败，不是业务去重锁。中间失败不存最终结果；重试需要 Scheduler，关闭 Scheduler 时计划不会自行执行。普通任务默认不重试，广播始终不自动重试。

## 6. 哪些情况下可能重复，怎样处理

| 情况 | 实际行为与处理 |
| --- | --- |
| 服务端保存了任务，但发布确认在网络中丢失 | 框架用同一个发送标识最多尝试两次；默认 120 秒窗口内 JetStream 去重。两次都超时仍报投递结果未知；不要生成新 ID 盲目重发 |
| Worker 已开始/已写业务数据，尚未确认就崩溃 | 续期停止后 JetStream 重投未确认任务；新 Worker 可能再执行。业务写入用唯一约束或条件 UPDATE，让重复调用不重复产生效果 |
| 完成 ACK 没到服务器 | 一次 ACK 超时会再尝试一次；最终失败停止续期，服务器仍未确认时会重投。仅 ACK 的回复丢失但服务器已确认时，不会因此重新执行 |
| 人工再次点击、调用方重发新 ID，或超过去重窗口重发 | 属于另一条投递或窗口外投递，不保证自动合并；按业务记录的状态/唯一标识处理，而非只依赖 task_id |
| 显式业务异常重试 | 有意再次执行函数，保留任务 ID、改变重试序号，使重试不被发布去重吞掉 |
| 一次性计划已发送，但 post_send 删除计划失败或 Scheduler 随后退出 | 同一计划保留稳定 task_id，恢复后可能重发；窗口内去重，超过窗口仍可能再执行 |

长任务并非一超过 ack_wait 就重投：从接收开始，等待执行时也每 ack_wait/3 续期；事件循环阻塞、连接长期中断或进程崩溃仍可能使续期失败。不要在异步任务里直接 time.sleep 或执行阻塞计算。

Demo 的 `complete_example_task()` 用一条 `UPDATE ... WHERE id = record_id AND is_completed = false` 把记录改成完成，再读取 rowcount。第一次 changed=true，第二次 false；提交由现有数据库上下文完成。这是业务状态的自然约束，不要求每个应用建立通用去重系统，也不要求所有任务必须使用数据库。只读统计允许重算；外部付款/发信等副作用则按外部接口提供的幂等键或业务状态规则处理。

结果与业务不是同一个事务。当前原生 Receiver 在结果编码或 Redis 写入失败后仍可能 ACK：任务可能已执行成功，但没有可查结果。日志必须保留；关键业务是否成功以自己的记录或外部接口为准，不以“Redis 没结果”决定再写一次。

## 7. 停止、排错与范围

```sh
./run.sh task_scheduler stop
./run.sh task_worker stop
```

先停调度可避免继续到期投递；Web 仍运行时也可能继续发布。一个 stop 命令先请求收尾，默认总预算 60 秒，超时后自动强停经过身份验证的整个服务进程组，不要求再执行 kill。资源关闭预算默认五秒，与等待业务任务完成的时间分开。强停后的未确认任务下次可重投，不等于业务回滚。

首次启动默认最多尝试三次；任一初始执行位置耗尽后启动失败。正常运行后的 Worker 崩溃由原生管理器持续补起，不受三次初始预算限制；仍应监控反复崩溃的日志。systemd 是可选的外层服务托管，不再启动第二套内部 Worker 管理器；托管时通过 systemd 停止服务，否则其重启策略可能又把你停止的命令拉起。

配置冲突会明确报错，不修改已有 Stream/consumer，更不会自动清空积压。检查 namespace、队列及 ack_wait/容量等配置是否与现有资源一致，按部署流程处理变更。namespace 是命名隔离，不是用户权限边界；NATS/Redis 应使用可信网络、凭据和权限，不能让外部用户任意发任务名或读取任意结果 ID。

本次真实验收覆盖单节点 JetStream、真实 Redis、两个执行进程、一个 Scheduler 和 Demo Chrome 操作；没有多节点 3/5 副本容错、生产吞吐或掉电恢复的完整部署验收。NATS/FastStream 通用 RPC 封装属于独立能力，不混入这个任务 API。精确配置、生命周期与维护点见[开发者参考](../developers/distributed-tasks.md)。
