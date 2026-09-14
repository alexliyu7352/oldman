# 日志

应用使用标准库 Logger，不需要 `await`，也没有另一套异步日志调用接口：

```python
from oldman.logging import get_logger, logger

log = get_logger(__name__)
log.info("Imported %s records", 12)
try:
    raise ValueError("example")
except ValueError:
    log.exception("Import failed")
```

`logger` 是框架的默认 Logger；`get_logger(name)` 返回命名 Logger。优先使用参数化日志，不提前拼接大型对象。异常栈用 `exception()` 或 `exc_info=True`。不要记录密码、Token、完整 Cookie 或带凭据的连接 URL。

## 初始化与关闭

WebApplication、SimpleApplication 和正常服务命令负责自己的日志生命周期。业务模块只取得 Logger，不在 import 时调用 `init_logging()`。

独立 Python 程序可以显式管理：

```python
import logging
from oldman.logging import get_logger, init_logging

runtime = init_logging(
    app_name="report",
    logger_path="logs",
    logger_level=logging.INFO,
    color="auto",
)
try:
    get_logger("report").info("Report complete")
finally:
    runtime.close()
```

`init_logging(app_name="DefaultApp", logger_path=None, logger_level=None, config=None, *, color=None)` 返回 `LoggingRuntime`。省略的目录、级别、颜色取当前 `settings.logging`；尚未初始化配置时取配置模型默认值。`color` 为 `auto`、`always` 或 `never`。`config` 是覆盖框架默认 logging 字典的嵌套映射，不是新的配置文件路径。

`get_active_runtime()` 返回当前 runtime 或 `None`。相同配置的重复初始化可复用现有 runtime；不同配置替换旧 runtime。`close()` 同步释放本进程创建的 handler 和轮转协调线程，可重复调用。应在最后一条清理日志之后关闭。

## 输出与轮转

默认同时输出终端和文件，文件名以应用名小写、空格转下划线形成前缀：

- `<prefix>.log`：普通与错误日志。
- `<prefix>_access.log`：Sanic 访问日志。
- `<prefix>_database.log`：SQLAlchemy 日志。

默认文件按天轮转，保留三份备份。一般 INFO 级别下，SQLAlchemy engine/pool/orm 的阈值提升到 WARNING；DEBUG 才显示详细 SQL 内部日志。终端可着色，文件输出去除颜色控制序列。

Linux 文件 handler 使用 `O_APPEND` 直接写入；各进程拥有自己的描述符，主进程协调轮转，子进程发现文件变化后重新打开。**这不是队列日志系统**，不需要为日志启动 Redis/NATS/消费者进程。同步写入仍有格式化和文件 I/O 成本，不承诺零阻塞；不要在高频数据循环逐项记录完整负载。

每个应用应使用自己的日志前缀/目录，避免多个独立主进程争用同一轮转目标。不要同时让另一套轮转工具管理相同文件而不核对策略。

## 子进程

`runtime.child_context` 是可序列化的 `ChildLoggingContext`。框架的 Sanic worker、`AsyncProcessManager` 和 `BaseManager` 已传递并安装它，应用无需重复接线。

自己使用 multiprocessing 时，显式传给顶层子进程函数，在子进程最初调用 `context.install()`，退出前关闭返回的 runtime；子进程不取得轮转所有权。不要传父进程 Logger handler、文件描述符或线程对象作为日志配置。

原始 `print()` 与结构化日志不同：短期 Python 子进程的 stdout/stderr 会通过管道转发到父终端；这不表示任意外部命令输出会自动转换成应用日志。外部命令的捕获、解码和记录由调用者决定，见[进程与任务](background.md)。
