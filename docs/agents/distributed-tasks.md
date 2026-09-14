# Agent：给应用接入分布式任务

目标是使用现有 Taskiq 接线完成用户的耗时工作，不新造消息总线、任务执行器或通用任务后台。先读[用户教程](../users/distributed-tasks.md)确认操作，再按需要查[生命周期与精确合同](../developers/distributed-tasks.md)。

## 先确认工作对象

在应用仓库检查 Git、services、已注册 Apps、实际 YAML 和数据库/存储。不要改用户运行中的配置、队列或数据库来做实验。先决定任务是否确实要持久排队：页面内短协程、固定常驻 Worker、SSE 推送与分布式任务不是同一用途。

需要用户确定的业务信息是参数/授权范围、执行的副作用、是否需要结果、队列分工、计划时区和外部设施。Taskiq/NATS/Redis 组合已经是框架能力，不重新选择或同时加入 Celery/RabbitMQ。普通 App 无需定义一套 TaskSettings 或从 app.ctx 找 broker。

## 直接对照 Demo 文件

| 文件 | 可复用的真实做法 |
| --- | --- |
| `services/task_worker.py` | TaskiqWorkerApplication 的直接子类，无复制的进程循环 |
| `services/task_scheduler.py` | TaskiqSchedulerApplication 的直接子类，不承担任务执行 |
| `data/task_worker_settings.example.yaml`、`task_scheduler_settings.example.yaml` | 同 namespace、两队列、真实数据库/User App、明确 NATS/Redis alias |
| `apps/examples/tasks.py` | 数据库摘要、Storage 导出、显式重试、条件 UPDATE、进程缓存广播、project_rpc |
| `apps/examples/views/tasks.py` | 已登录 staff/CSRF、固定操作集合、记录 ID 校验、用户归属、投递与查询分开 |
| `templates/pages/examples/tasks/` | 普通 Form 和有序 Response Actions，不增加 Taskiq 专属 TS/表单协议 |
| `apps/examples/views/__init__.py`、侧栏模板 | 三个示例页面和正常动态页面生命周期 |
| `tests/test_examples_tasks.py` | 隔离真实 SQLite/Storage 的函数结果与失败验证，不代替实际 Worker/Chrome |

这些文件在[独立 EPG Demo](https://github.com/alexliyu7352/oldman-epg-dashboard)，不是框架源码内的 examples 目录。完整启动与页面路径见用户教程；示例节选应说明变量和 helper 的来源，不虚构一个框架自带的 `_result` 函数。

## 实施顺序

1. **复用已有业务 App。** 必要时新建实际有职责的 App，加入所需服务的 settings.apps。AppConfig.tasks_module 默认 tasks，不必重复配置；任务模块不声明数据库表，模型先由 Registry 加载。Web 业务按需显式导入；Worker/Scheduler 自动加载其已安装 App 的 tasks。
2. **声明异步函数。** 从 oldman.tasks.distributed 导入真实 broker，使用原生 @broker.task。传普通可序列化值/记录 ID，函数执行时查询数据；不传 request、数据库 Session、ORM 实例或连接。使用现有 db_manager/Storage/HTTP，保留各自上下文和关闭责任。
3. **声明服务。** 复用已有 Taskiq 服务，或通过 startservice 选择 taskiq_worker/taskiq_scheduler。文件名决定命令和 YAML；不引入 SERVICE_ID。新服务 settings init，已有服务 sync/check；不要让 run.sh 或 Web 自动启动全部服务。
4. **配置共享关系。** Web/Worker/Scheduler 的 namespace、NATS、所用 Redis DB 对齐；后台 App 清单只包含真正需要的模型/任务。检查实际数据库/User 配置；导出存储必须能被需要读取它的服务访问。不要把 Demo 的回环无认证 URL 当生产配置。
5. **接入发布者。** Web、普通 Simple、App 命令使用框架已有 broker 生命周期；不要在每次请求 startup/shutdown。Shell 才在自己的循环内显式 async with broker。`.kiq()` 等投递确认，不等业务完成；不要占住 HTTP 请求等待耗时结果。
6. **结果与权限。** 若要浏览器查结果，在应用层绑定当前用户和 task_id；丢失归属时拒绝，不开放任意 ID 查询。Demo 对 broker.result_backend 直接 get_result 并捕获原生 ResultIsMissingError，不先 is_ready 再读，避免两次命令之间 TTL 到期报错；真正的连接/解码错误仍上抛。缺失不等于运行中，忽略结果和广播不等待结果。不为普通示例建立新任务历史表。
7. **调度与重试。** 固定标签计划随代码，动态计划用同一个公开 schedule_source；使用明确时区。创建由显式业务操作触发，不在 GET/每个 Web worker 启动时反复登记。只部署一个 Scheduler，并提供业务所需的取消入口。取消不能撤回已投递任务。
8. **失败处理。** 不自动重新发送结果未知的任务。根据业务副作用选择已有唯一约束/条件 UPDATE或外部幂等键；不是给每个任务新增一套去重表。普通异常默认不重试，需要时显式 retry_on_error，并确认 Scheduler 实际运行。

## 不能写错的边界

- 两个进程、每进程三个并发、两条队列共用：总上限六个。不是每队列六个。max_prefetch、max_ack_pending、stream_max_bytes 各自含义不同。
- 直接 await 被装饰函数仍是当前任务内的函数调用；另一次 .kiq 才进入队列。父任务占满位置后等待同池子任务会互相等。自行 create_task 不变成可靠任务，也不会自动受 Taskiq 并发限制。
- 广播只送在线且监听对应队列的执行进程，使用独立 Core subject；强制不保存结果、不重试，离线/慢消费者可丢弃。不是执行到所有服务器并收集返回的 RPC。
- 结果默认写入起 24 小时自动过期、读取不续期。结果写入/编码失败时原生 Receiver 仍可能 ACK；不能以没结果决定重做业务。
- 同标识发布去重只有有限窗口。Worker 崩溃、ACK 未送达、窗口外重发、显式异常重试和 Scheduler post_send 失败分别说明，不宣传“任务永不重复”。
- 启动耗尽报错；运行中 Worker 持续补起。stop 一条命令包含等待与到期整组强停。不要新增独立 kill 命令、常驻监控进程或复制 ProcessManager/Receiver/SchedulerLoop。
- namespace/queue 字符串不是权限。只有受信任进程可以写任务设施；浏览器只操作业务白名单，不能指定任意 task_name/参数/计划或读取他人结果。
- 不把 FastStream RPC、Redis SSE、通知持久化、旧固定 Worker 搬进 distributed 模块。没有必要的 Taskiq 私有页面组件或第二套 HTTP client。

需要在任务里询问远端时，直接复用 Demo project_rpc → apps/examples/nats_example.py 的调用方式，导入 oldman.providers.nats.bus；执行子进程在原生 startup 前已打开、shutdown 后才关闭。Worker 父进程不连接，Worker/Scheduler 不自动加载 events，不能靠 consume=true 将它们变为接收集群。Core 的启动计时纳入 Worker 原有总预算，不改 ready/重试/保活协议；Scheduler 仍用自己的原生启动流程。Core 与 Taskiq 只共享地址配置，不共享 Client、subject 或 ACK。任务中不用 async with bus，也不能因为 Taskiq 可靠排队就承诺远端 RPC 不会超时；操作与失败验证见[通信教程](../users/service-communication.md)。

## 最少真实验证与交付

按本次改动选择直接检查，串行运行，避免反复跑全项目门禁。设施使用独立端口/namespace/存储，记录 PID；不使用内存 broker 代替 NATS/Redis。

1. 投递真实任务，确认后台 PID、数据库读写/文件结果；一个业务异常在 Worker 真实出现，不能伪造失败结果。
2. Worker 未运行时可排队；启动后同 ID 完成。需重试/调度时运行实际 Scheduler，确认到期、取消和同一任务的重试，不只查 Redis 中“有计划”。
3. 结果查询、ignore_result、TTL/不可用状态与实际配置一致；多个用户验证归属，不只验正常管理员自己查询。
4. 涉及页面时用真实 Chrome 从侧栏进入，点击投递/查询/失败/取消，再离开和返回；服务不可达时检查 loading/遮罩以及错误提示，两项分开记录。
5. 正常 stop 后核对进程和资源；需要验证强停时先记录命令自己的结果，再兜底清理。测试杀干净不算优雅退出。
6. 分别提交框架/应用文件，不提交实际 YAML、数据库、结果文件、凭据和临时产物；用户已有修改保持原状。更新操作命令、配置和源码索引，明确未覆盖的集群/生产负载或现存无关问题。

如果真实页面暴露与本任务无关的 Form/HTTP 回归，先核对公共根因和授权，不加 Taskiq 专属错误补丁求绿灯。交付说明不能把“按钮恢复”写成“请求失败提示已通过”。
