# 进程与后台任务

`oldman.runtime` 管生命周期；`oldman.processes` 执行短期 Python 进程或受控外部命令；`oldman.tasks` 管同进程协程和长期 Worker。另有显式启用的 oldman.tasks.distributed 管持久队列；本地接口不向 NATS 投递，也不共用一个含糊的 MessageBus。

| 需求 | 入口 |
| --- | --- |
| 同一事件循环周期采样 | `BackgroundTaskManager`，或 SimpleApplication 自己的 `main()` |
| 限并发执行同步 Python 计算 | `AsyncProcessManager` |
| 启动外部程序、处理超时及子进程组 | `run_subprocess_exec` / `create_subprocess_exec` |
| 多个长期 Worker 接收启动/停止任务指令 | `BaseManager`、`BaseWorker`、`BaseTask` |
| 异步函数持久排队、多个执行进程、结果和定时投递 | [Taskiq](distributed-tasks.md) |
| 不同独立服务之间的消息/RPC | [NATS provider](providers.md#nats-连接与发布) |

## 同进程协程

实际例子是 EPG [background.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/background.py) 的 `BackgroundStats` 和 `sample_project_counts`；运行方法及错误见[本地协程教程](../users/background-work.md#实际运行一个本地后台协程)。不是只有 sleep 的占位函数：每次采样都创建只读 Session，查询 ExampleProject 数量，可按真实团队过滤。

`BackgroundStats.handle()` 中的登记节选如下；manager 是本次 CLI 进程的 `BackgroundTaskManager()`，counts 是结果列表，ready/cleaned 是 asyncio.Event，team_id 已经过 CLI 类型校验：

```python
        manager.add_task(name, sample_project_counts, counts, ready, cleaned, team_id,
                         task_type=TaskType.PERSISTENT)
```

完整文件导入 `asyncio`、SQLAlchemy `select/func`、框架 `db_manager`、`Command`、`BackgroundTaskManager/TaskType` 和已加载的 Demo 模型。命令在 `commands.py` 公开导入，由已注册 examples App 发现；调用者不用手工创建事件循环。不要把这个节选当成缺少参数来源的独立脚本。

启动后，采样协程每秒读一次，第二个样本完成时设置 ready，仍继续等待下一次采样。异常/取消则在 finally 设置 cleaned 和 ready，确保父协程不一直等待根本不会产生的结果。命令最多等 10 秒，然后检查 `manager.tasks[name].task`；已经结束时 await 该 Task，传播真实错误，而不是仅凭事件、名称或登记状态说成功。

成功路径先保存 `get_task_status` 的运行快照，再 await stop_task，输出停止状态和协程 finally 标记。无论成功失败，finally 都停止监控、移除自身任务、最后关闭数据库。此例为展示取消而用 PERSISTENT；它不让一个页面请求无限占用服务，也不承诺数据库统计是持久结果。

`BackgroundTaskManager()` 是**进程级单例**，Web/SimpleApplication 的 `self.task_manager` 也使用它。不要在同进程为不同业务反复调用 `start_all()`；应由一个生命周期所有者启动一次。`add_task()` 接收协程函数及其参数，不是已创建的 coroutine。

- `add_task(name, coro_func, *args, restart_delay=30, max_restarts=-1, task_type=PERSISTENT, auto_remove_on_complete=None, **kwargs)` 注册但不自动启动。
- `start_task(name)`、`stop_task(name)`、`remove_task(name)`、`restart_task(name)` 是异步方法，返回是否成功。
- `start_all()` 启动已注册任务和监控协程；`stop_all()` 取消并等待；`stop_all_sync()` 只发出取消，不能代替需要等待的异步资源清理。
- `get_task_status(name)` 返回状态字典，未知名称返回 `{}`；`get_all_status()` 返回全部注册项。

`PERSISTENT` 指协程正常结束后也应重启；不是数据持久化。`ONE_TIME` 正常完成后默认移除。状态由默认每 60 秒运行一次的监控器更新，所以任务刚完成时可能仍显示 `running`，同时 `is_alive=False`。

当前自动重启不是可靠重试队列：重启延迟/次数条件不满足时，不保证以后自动再次尝试。`max_restarts` 的当前判断只限制正数，不能把 `0` 当作明确的禁用重启选项。同名 `add_task()` 会覆盖登记，不负责先停止旧任务；替换前显式 `remove_task()`。不要依赖此组件实现需要重放、确认或精确调度的作业。

## 短期 Python 进程

目标函数必须来自可导入的业务模块，不放在启动脚本的 `__main__` 中。实际 EPG [process_jobs.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/process_jobs.py) 导入 Counter、os、Path、time，完整 target 如下：

```python
def inspect_projects(statuses: list[str], scenario: str, marker: str) -> dict:
    """Summarize real input, or deliberately exercise a documented failure mode."""
    pid = os.getpid()
    Path(marker).write_text(str(pid), encoding="utf-8")
    print(f"Python child {pid}: received {len(statuses)} project statuses", flush=True)
    if scenario == "error":
        raise ValueError("Demonstration: child calculation failed")
    if scenario in {"timeout", "cancel"}:
        time.sleep(30)
    return {"pid": pid, "counts": dict(sorted(Counter(statuses).items()))}
```

调用者是 [process_examples.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/process_examples.py) 的 PythonProcessDemo，不需要再写 calculate.py 或服务。运行[四种路径](../users/background-work.md#实际运行短期-python-子进程)时，CLI 已加载配置/模型并准备异步命令生命周期。Command 创建 `AsyncProcessManager(workers=1)`，父进程只读数据库得到 statuses，TemporaryDirectory 提供本次 marker；启动的原文：

```python
                job = asyncio.create_task(manager.run_with_timeout(
                    inspect_projects, (statuses, scenario.value, str(marker)),
                    _timeout=1 if scenario == ProcessScenario.TIMEOUT else 10,
                ))
```

取消分支等待 target 写出 PID 后 `job.cancel()` 并 await，确认它真在运行而不是仅取消尚未 spawn 的调用。其余分支 await 返回值；本例必须有 counts，None/空结果不能输出成功统计。finally 等待尚未结束的 job、shutdown 管理器、关闭数据库，确认 PID 回收，然后退出 TemporaryDirectory。PID 文件只是本例的可观察证据，不是框架结果 backend。

每次调用创建一个 Billiard **spawn** 进程，`workers` 限制并发，不是预热进程池。目标是同步、可序列化的模块顶层函数；参数及返回值必须能通过进程 IPC。不要从 stdin 执行入口，或传 lambda、局部函数、启动脚本中定义的 target。父进程等待不阻塞事件循环；不要把异步函数直接当 target，也不要传数据库 Session、Redis/HTTP 连接或请求对象。

`run_with_timeout(target, args=(), _timeout=30)` 超时抛 `ProcessTimeoutError`。子函数异常会打印堆栈并返回 `None`，不是原异常跨进程重抛；异常退出/关闭中也可能返回 `None`，结果队列读取失败可能返回 `{}`。需要区分业务失败时，在目标函数返回自己的明确结果字典，不把 `None` 解释成成功。

取消、超时和关闭会回收本次子进程；调用取消仍是 CancelledError，不延迟转换成任务超时。结果 Queue 每次独立，stdout/stderr 使用另一条管道。结果读取线程在清理时被通知结束并等待退出，不把空队列等待留到事件循环关闭；父进程释放未使用的 Queue 写端，异常死亡的子进程可产生 EOF。构造可选 `logging_context=...`；不传时启动前取活动日志 runtime。Linux 父进程死亡信号只是进程生命周期保护，不使业务操作具备事务或幂等性。

## 外部命令

实际 EPG Command 是 [SubprocessDemo](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/process_examples.py)，运行方式见[外部命令教程](../users/background-work.md#实际运行受控外部命令)。模块已导入 sys、json、asyncio 和框架 create_subprocess_exec/run_subprocess_exec、结果与异常类型。program 固定为 sys.executable，参数为 `-m apps.examples.external_job` 和经过枚举校验的 scenario。data 是父进程 `_project_statuses()` 查询后经 json.dumps(...).encode("utf-8") 得到的 bytes。

success/error/timeout 使用下面这段真实调用：

```python
                    result = await run_subprocess_exec(
                        *command, input=data, capture_output=True, check=True,
                        timeout=1 if scenario == ProcessScenario.TIMEOUT else 10,
                    )
```

外部程序 `external_job.py` 打印启动信息并从 stdin 读 JSON，正常打印 Counter 汇总，error 写 stderr 后退出 7。Command 捕获 SubprocessError 时先显示 error.result 的 stdout/stderr/进程标识，再抛出；捕获 SubprocessTimeoutError 时同样显示已保留输出。不把失败返回码解释为成功或转换成另一套框架结果对象。

cancel 分支演示低层句柄：await create_subprocess_exec 指定 stdin/stdout/stderr=PIPE，随后进入 `async with process`；先读取一行启动信息，再创建 communicate(data) 的 Task、取消并 await。Task 取消时框架清理进程组并读完管道，退出上下文再确保清理。本例 startup 行很小且 stderr 不会不断输出；一般程序要并行消费两个输出流，不能照抄“先读一行”来处理任意高输出程序。父进程所有路径 finally 关闭数据库，不在子模块 bootstrap 或复制连接。

`run_subprocess_exec(program, *args, input=None, capture_output=False, timeout=None, check=False, stdin=None, stdout=None, stderr=None, cwd=None, env=None, limit=2**16, terminate_grace_period=..., kill_timeout=...)` 使用参数列表，不启动 shell。不要自己拼接用户输入后交给 `sh -c`。

`input` 是 bytes，自动使用 PIPE，不能再传 stdin；`capture_output=True` 捕获 stdout/stderr，不能同时指定这两个流。默认输出继承，捕获结果为 bytes 或 `None`。`env` 是传给子进程的环境映射；需要保留环境时由调用者显式合并，不假定它只覆盖几个键。

结果 `CompletedSubprocess` 提供 `args`、实际命令 `pid`、`supervisor_pid`、`process_group`、`returncode`、`stdout`、`stderr` 和 `check_returncode()`。默认非零返回码仍返回结果；`check=True` 抛 `SubprocessError`，其 `result` 保留输出。启动失败为 `SubprocessStartError`，超时为 `SubprocessTimeoutError`，清理不完全为 `SubprocessCleanupError`；共同的操作错误基类是 `ManagedSubprocessError`。

长输出使用 `create_subprocess_exec()` 获得 `ManagedSubprocess`，通过其 `stdout`/`stderr` StreamReader 持续读取；支持 `async with`，以及 `wait(timeout=None)`、`communicate(input=None, timeout=None)`、`terminate()`、`kill()`。PIPE 两端都可能填满，不要只读 stdout 却无人消费大量 stderr，也不要用 `capture_output` 无上限缓存无限日志。

Linux supervisor 持有受控进程组：超时/取消/退出会清理组内剩余进程，正常命令退出也不会留下同组后台程序。它不是允许任意命令运行的安全沙箱，主动脱离进程组等行为不能当作受保护业务模式。

## 长期 Worker：真实项目快照

运行入口是 EPG `./run.sh web worker-demo --scenario success|error|stop`，不是另建 worker_example.py。[用户教程](../users/background-work.md#实际运行固定-worker)说明三种结果与清理。实际 [worker_jobs.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/worker_jobs.py) 只依赖标准库和 oldman.tasks，定义 ProjectSnapshotTask、创建器和 Worker：

```python
def create_snapshot(task_id: str, data: dict[str, Any]) -> BaseTask:
    """The existing Worker creator contract is synchronous, even for async tasks."""
    return ProjectSnapshotTask(task_id, data)


class ProjectSnapshotWorker(BaseWorker):
    """Register one task creator; no custom queue, ACK or result backend."""

    async def initialize(self) -> None:
        """Registration happens in this spawned Worker, not in the Web process."""
        self.register_task_creator("project_snapshot", create_snapshot)
```

这是源文件节选；Any 来自 typing，BaseTask/BaseWorker 来自 oldman.tasks，ProjectSnapshotTask 在同文件定义。任务 execute 对传入的项目记录转换 id，生成包含 task_id、真实 worker_pid 和 projects 的报告。转换失败时保存 error，父命令把它判为业务失败；不是依赖任务内部 TaskStatus 或捕获跨进程原异常。报告先写临时文件再原子替换，父进程不会读取半份 JSON。

管理器所有者是 [worker_examples.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/worker_examples.py) 的 WorkerDemo：CLI 初始化后父进程只读 SQL，创建 BaseManager(ProjectSnapshotWorker, num_workers=1) 和自己的 TemporaryDirectory，再 start/add_task。只传普通记录和目录字符串，不传 ORM 实例、Session、Request 或客户端。结果文件是这个业务例子的实际输出，不是新框架 result backend。

success/error 使用 ONE_TIME；stop 使用 PERSISTENT，输出报告后 await Event().wait() 保持任务运行。父命令读取报告才调用管理器的 stop_task，再等待 execute finally 写出的 `.stopped` 文件；两个文件各最多等 10 秒，失败一样走 finally。Worker 内部的 `_handle_task_stop` 接收指令后先调用 task.cleanup，再取消执行协程，因此 **cleanup 钩子被调用不等于 execute 已退出**；需要保证协程资源释放时，放在 execute 的 try/finally。本例的最终标记写在那里。应用调用 BaseManager.stop_task，不直接调用这个内部 handler。

最后先 await manager.shutdown，关闭父数据库，再核对捕获的 Worker PID 不存在，退出 TemporaryDirectory 删除全部本次输出。命令独占一个管理器，临时目录不接受用户任意路径；不写入项目数据、不新增服务/表/结果查询端点。`scripts/verify-worker-demo.py` 从实际 CLI 串行执行三模式，检查结果/失败及 PID 回收。

`BaseManager(worker_class, num_workers=4, max_worker_restarts=-1, worker_restart_delay=5, monitor_interval=60, logging_context=None, process_start_method="spawn")` 轮询健康 Worker 分配任务。`start()` 启动子进程及监控，`shutdown()` 停止并回收。可指定 forkserver/fork，但默认 spawn 不复制已启动线程、事件循环与连接池；通常保持默认。

`add_task(task_data, task_type=PERSISTENT, restart_delay=5, max_restarts=-1, auto_remove_on_complete=None)` 返回任务 ID 或 `None`。字典的 `task_type` 是业务创建器名称；方法参数的 `task_type` 是 `TaskType` 生命周期枚举，两者不是同一个字段含义。任务 ID 表示指令放入本地队列，**不是 Worker 已执行成功的确认**。

`BaseTask.execute()` 是异步业务入口，`cleanup()` 是任务级清理。任务协程自己的资源仍应使用 `try/finally`：不要依赖同步状态字段或 cleanup 顺序推断所有协程已停止。`BaseWorker.initialize()` 注册同步创建器，资源在该子进程内初始化并关闭；spawn 不自动绑定父进程服务 Settings，若业务确实依赖配置，在 Worker 初始化中调用统一 `bootstrap_service()`，不要带入父进程已打开的连接。

父进程 `get_manager_status()` 只报告 Worker 进程健康情况；Worker 的 `get_task_status()` 是其本地状态，不是父进程 RPC。控制消息 `TaskMessage`/`MessageType` 使用 multiprocessing Queue 与 MsgPack，不使用 Redis/NATS。

当前没有作业数据库、完成 ACK、结果 backend、失败队列、断电恢复或 Worker 重启后的任务自动重放。业务需要可靠完成记录，应自行持久化业务状态；跨服务 RPC 用 provider，不能把这套启动/停止控制协议当成可靠任务平台。
