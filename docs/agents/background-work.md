# 任务指南：后台执行与进程

先读取[服务接线](create-service.md#后台示例的当前边界)，再按需求选择[进程与任务](../developers/background.md)的一个入口。持久分布式任务已有独立[Taskiq Demo](distributed-tasks.md)，本地协程也有[background-stats 实例](../users/background-work.md#实际运行一个本地后台协程)，常驻 SimpleApplication 接线可参考 NATS 接收服务。不要因为用户说“后台”就同时引入 Redis、NATS、Worker 和新数据库表。

本地协程先对照 Demo `apps/examples/background.py` 和 `commands.py`：有限 CLI 进程注册并启动项目计数，实际读两次数据库，保存运行快照后停止任务，最后关闭监控与连接。缺失团队测试真实异常和清理。扩展时先决定生命周期所有者；这个命令可拥有整个单例，但活 Web 请求不能借用它的 start_all/stop_all 去停止其他任务。只需一次异步调用时直接 await，不为所有函数强套管理器。

## 文件与资源归属

业务函数放已安装 App 的普通模块；现有例子是 `apps/examples/background.py`。真正需要新常驻服务时，参考 `services/nats_a.py` 的 SimpleApplication 子类：prepare 不联网，main 异步等待，after_stop 关闭本服务拥有的数据库并在 finally 调用 super。NATS 订阅仍归 Registry/Core 生命周期，这只是服务写法参考，不能把接收服务复制后称为已经实现了采集业务。短期进程 target、Worker 类及同步任务创建器定义在可导入模块顶层，避免 spawn 无法序列化 lambda/闭包。

配置文件按实际服务文件名对应 `data/<服务名>_settings.yaml`，只安装该服务需要的 App；现成对照是 `data/nats_a_settings.example.yaml`。需要模型的子进程在自己的初始化中使用 `bootstrap_service(实际服务名)`，不能把父进程的 Session/Redis/HTTP 实例传入。这里是 API 接线规则，不是让本例的纯数据 target 新增配置依赖；只是计算传入列表的函数不需要 bootstrap。

将参考中的 `manager.start()` / `shutdown()` 或 `start_all()` / `stop_all()` 放在同一所有者的 `try/finally` 中。SimpleApplication 已有 `self.task_manager`，不另设第二个“全局管理器”。Web 服务若每个 Sanic worker 都启动同一采样器，就会执行多份；仅需一份的业务使用独立 SimpleApplication 服务。

## 交付检查

短期 Python 进程优先对照 Demo `apps/examples/process_jobs.py` 的纯数据 target 和
`process_examples.py::PythonProcessDemo` 的父进程接线。命令 `python-process --scenario ...` 明确区分
成功、子函数异常返回 None、超时异常和主动取消；相应 `scripts/verify-process-demos.py`
运行真实四条路径并检查 PID 回收。父进程查询完只传普通 list，子模块不导入 ORM/Settings，不创建
父进程连接的“可序列化代理”。本例统计可用 SQL 更高效，不能把示例当成所有计数都应开子进程的建议。

受控外部命令对照同文件 SubprocessDemo 与 `apps/examples/external_job.py`。默认使用
run_subprocess_exec 的 stdin bytes/capture_output/check，取消示例用 create_subprocess_exec 和 async with。
固定程序+argv，不新增任意 shell 参数。错误显示 SubprocessError.result，超时显示异常保留的输出，
不要做统一假成功封装。共用上述验证脚本，等待分支会生成一个真实同组后代，验收要检查整个组消失。

固定 Worker 对照 `worker_examples.py::WorkerDemo` 和 `worker_jobs.py`：父进程查真实项目，子进程的同步创建器创建异步 BaseTask，实际写出项目 JSON 快照；Command 读到报告才认为完成。success/error/stop 三模式见 `scripts/verify-worker-demo.py`，实际失败是非法 id 转换，不写坏数据库。stop 模式输出后仍等待停止指令，执行协程 finally 写标记；不要把更早执行的 cleanup 钩子或任务 ID 当作结束证据。管理器、临时目录、父数据库归同一命令所有，始终 shutdown/关闭/删除；任务结果不变成新框架 ACK 或 backend。

1. 从真实文件运行 spawn 例子，验证结果，不只 mock Process。
2. 验证一个实际失败：外部程序非零返回、超时，或 Python target 异常；按当前 API 判断，不虚构统一异常/结果协议。
3. 退出后检查本任务子进程已回收，临时输出已清理；不结束机器上其他同名服务。
4. Worker 指令成功入队不能当作业务成功；需要完成状态时使用业务真实记录，不添加假的状态查询 API。
5. 不把这里的本地协程/固定 Worker 描述成持久队列。需要持久投递或调度时使用已有 Taskiq，明确业务失败和副作用，而不是改写旧 Worker 协议。

日志调用与子进程上下文见[日志](../developers/logging.md)，独立服务间传消息见 [provider](../developers/providers.md)。
