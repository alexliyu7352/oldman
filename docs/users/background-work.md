# 在后台运行工作

先区分“浏览器等一次结果”和“服务一直在后台运行”。不需要 HTTP 的采样、消费任务使用 SimpleApplication；手工执行一次统计或导入使用 App Command，不必再建一个长期服务。

## Demo 的当前边界

持久排队与定时任务已有完整[Taskiq Demo](distributed-tasks.md)：数据库摘要/导出、两队列、在线广播、计划与结果。它使用独立 task_worker/task_scheduler，下面的原有本地协程和固定 Worker 接口不因此变成持久队列。

本页四个本地执行示例都由有限 App Command 展示，运行完就回收资源，不要求额外启动常驻采集服务。需要查看 SimpleApplication 的实际常驻接线时，参考 [NATS 接收服务](service-communication.md)；它们负责接收事件/RPC，不采集监控数据。实时表格在 Web 请求中回放已有数据库样本，实时图表由显式发布按钮写入样本，不会因为每个浏览器打开页面而重复启动后台采集器。

### 实际运行一个本地后台协程

EPG Demo 已提供 `background-stats`，不需要新增 collector 服务。完成 Demo 配置、迁移和可选的 `loaddata demo` 后，在 Demo 根目录运行：

```bash
./run.sh web background-stats
./run.sh web background-stats --team-id 1
```

命令注册并启动一个 BackgroundTaskManager 协程，每秒从数据库读取一次项目总数，拿到两次样本就停止。它不启动 Web、不写数据库，也不从浏览器连接启动采集器。若 YAML 启用 NATS/Taskiq，App 命令生命周期仍会先连接这些设施；只试本项时可在本机 YAML 关闭 `nats_bus.enabled`、`taskiq.enabled`，不需要 Worker/Scheduler。

输出包含 `samples`、`running`、`stopped` 和 `cleanup_completed`。预设数据未改时全表样本是 `[120, 120]`，团队 1 为 `[15, 15]`；以自己的数据库为准，不应硬编码这些数量。`running.is_alive=true` 表明协程确实还在运行；显式停止后 `stopped.is_alive=false`，`cleanup_completed=true` 表明协程 finally 已执行。最后停止监控、移除登记，再关闭数据库。

`--team-id 0` 是参数错误，退出码 2；合法但不存在的 ID 是协程中的真实查询失败，退出码 1，也会清理资源。存在但没有项目的团队返回 `[0, 0]`，不是错误。只等待本次两次采样，最多 10 秒；超时同样结束并清理，不输出假结果。

完整源码为 [background.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/background.py)，由 [commands.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/commands.py) 公开导入 Command 类，App Registry 自动发现。这个独立 CLI 进程拥有整个管理器，**不要把 Command.handle 复制到正在处理请求的 Web 服务并调用 start_all/stop_all**，那会操作同进程其他任务。

SimpleApplication 的 `main()` 也可以直接编写异步循环。只有需要多个独立协程及状态/重启管理时才使用 `self.task_manager`。它不会自动启动登记的全部任务，应用负责 `start_all()`，在退出时等待 `stop_all()`；不要在没有事件循环的 `prepare()` 中调用 `asyncio.create_task()`。

## 选择执行方式

### 实际运行短期 Python 子进程

EPG 的 `python-process` 从数据库读取项目状态列表，传给同步子进程汇总，再输出真实 PID 和状态数量。它只是展示“父进程读数据、子进程算纯数据”的接线；普通简单统计仍优先 `project-stats` 的 SQL，不声称进程开销能使简单计数更快。

准备与 `background-stats` 相同，在 Demo 根目录运行：

```bash
./run.sh web python-process
./run.sh web python-process --scenario error
./run.sh web python-process --scenario timeout
./run.sh web python-process --scenario cancel
```

- success：子进程 stdout 显示 PID/输入数，父进程显示 `counts`，最后 `child_pid=... reaped=true`，退出 0。
- error：演示函数故意抛 ValueError，框架打印其堆栈并返回 None；命令把这个缺失结果判为失败，退出 1，**不是原异常自动跨进程抛出**。
- timeout：演示函数等待 30 秒，但本次调用上限 1 秒；实际抛 ProcessTimeoutError，退出 1，并回收子进程。
- cancel：等子函数真正写出 PID 后取消等待，观察 CancelledError；这是主动选择的取消演示，正常退出 0，不输出项目统计。

四条路径都在 finally 关闭管理器/数据库，确认子 PID 不再存在，再自动删除 `/tmp` 下自己的 PID 文件。它们不改项目记录、不使用 Worker 队列。可运行 `.venv/bin/python scripts/verify-process-demos.py` 串行复核 Python 与下面外部命令的各四条路径；脚本要求已准备好 Demo 配置和数据库，不会偷偷迁移或导入 fixture。

源码：[process_jobs.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/process_jobs.py) 是只依赖标准库的可导入顶层 target；[process_examples.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/process_examples.py) 是 Command 所有者，经 commands.py 公开。不要把 target 移到 stdin/局部函数里，也不要把 Session、Request 或活连接传给子进程。

### 实际运行受控外部命令

同一个 Demo 还提供 `subprocess-demo`，只执行项目自己的固定 Python 模块，不是可以输入任意 shell 命令的后台：

```bash
./run.sh web subprocess-demo
./run.sh web subprocess-demo --scenario error
./run.sh web subprocess-demo --scenario timeout
./run.sh web subprocess-demo --scenario cancel
```

默认模式把真实项目状态编码为 JSON bytes，经 stdin 交给外部程序；stdout 包含启动 PID 与统计。这里进程之间是标准输入/输出，不是 Python 对象 Queue。error 模式明确让子程序写 stderr 并退出 7，框架抛出的 SubprocessError 保留输出，Oldman 命令退出 1。timeout 在 1 秒后抛 SubprocessTimeoutError，输出中仍能看到已读取的启动信息。

timeout/cancel 模式还启动一个固定的同进程组 sleep 子进程，用来观察框架是否连后代一起回收。cancel 使用流式句柄，读到启动行后取消 communicate，显示 CancelledError、正常退出 0。输出中的 command_pid 与 process_group 是真实值；验证脚本用系统检查确认整个组以及打印的后代 PID 已消失，不把父程序退出当成全部清理。

源文件是 [process_examples.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/process_examples.py) 的 SubprocessDemo，以及只依赖标准库的 [external_job.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/external_job.py)。与 PythonProcessDemo 共用父进程查询函数和 Scenario 枚举，不新建 Shell 服务。实际业务执行别的程序时，仍使用固定程序/参数列表，不把不可信输入拼进 `sh -c`。

### 实际运行固定 Worker

`worker-demo` 在命令存活期间管理一个长期 Worker；用有限命令演示启动、任务创建与停止，不要求另外启动永久服务。准备好同一 Demo 数据库后运行：

```bash
./run.sh web worker-demo
./run.sh web worker-demo --scenario error
./run.sh web worker-demo --scenario stop
.venv/bin/python scripts/verify-worker-demo.py
```

父命令读取真实项目的 id/name/status，把普通记录交给 Worker。Worker 在自己的临时目录生成 JSON 快照，父命令读取完整文件后输出 `project_count`、`first_project`、`worker_pid`；预设数据是 120 条。输出前的管理器状态只表示进程健康，不表示任务完成。当前管理器启动约需 3 秒，请等待命令返回。

- success：一次性任务导出后结束，命令退出 0。
- error：只在传输副本中加入非法项目 ID，Worker 的实际整数转换失败，写入业务失败报告；父命令读到报告后退出 1。数据库不变，不把这个报告伪称为框架的结果/异常回传 API。
- stop：任务生成快照后仍等待；父命令显式发送停止指令，等任务 execute 的 finally 写出结束标记才继续。`execute_cleanup_completed=true` 是实际清理证据，不是根据 task_id 猜出的状态。

三条路径最后都关闭管理器、回收 Worker、关闭父进程数据库并删除本次临时文件；`worker_pid=... reaped=true` 与验证脚本的系统 PID 检查对应。等不到结果最多等待 10 秒后失败，也进入清理。普通业务不能靠这个临时快照恢复断电任务；需要持久排队/结果时使用 Taskiq。

源码：[worker_examples.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/worker_examples.py) 是 Command 所有者；[worker_jobs.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/worker_jobs.py) 定义可导入的 Worker、同步创建器和任务。子进程不继承父进程的数据库连接，也不需要 Redis/NATS。入口配置若启用 NATS/Taskiq，仍适用上面 App 命令的设施前置条件。

### 按工作性质选择（汇总）

- 同一进程的异步采样：不用额外进程或消息中间件。
- CPU 密集的同步 Python 计算：使用 `AsyncProcessManager`；每次调用有并发和超时限制。
- 外部命令：使用框架受控 subprocess，传程序和参数列表，不拼 shell 字符串。
- 多个长期 Worker：使用 `BaseManager`；需要知道它只传启动/停止指令，不保存可靠任务结果。
- 异步函数持久排队、结果和计划：使用 [Taskiq](distributed-tasks.md)。
- 独立服务器之间发布或 RPC：使用 NATS，而不是把 Worker 内部 Queue 暴露给业务服务。

对应的完整可运行例子、对象来源、限制和关闭方法见[进程与任务参考](../developers/background.md)。无需数据库的计算例子可以直接在安装了 Oldman 的独立目录执行；依赖业务 App 的 Worker 才需要相应服务配置。

## 不要遗漏失败与退出

任务超时或 Worker 停止不等于业务写入被撤销。数据库写入仍受自己的事务管理，调用外部系统也可能已经成功；需要幂等性的业务自行定义操作标识。

使用 `try/finally` 关闭自己创建的进程管理器、HTTP/NATS 客户端以及数据库连接池。先结束任务，再关闭任务仍可能使用的连接，最后关闭日志。普通业务日志使用 `get_logger(__name__)`，不在每个任务中重新初始化日志，详见[日志参考](../developers/logging.md)。
