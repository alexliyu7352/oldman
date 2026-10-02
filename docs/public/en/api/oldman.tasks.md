# `oldman.tasks`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

@author:alex

Import with `from oldman.tasks import <name>`.

## `BackgroundTaskManager`

class · defined in `oldman.tasks.simple`

```python
class BackgroundTaskManager
```

Supervise coroutines in this process: named tasks with restart policies, plus fire-and-forget spawns.

Constructor:

```python
BackgroundTaskManager() -> None
```

Members:

- `def add_task(name: str, coro_func: CoroutineFunction, *args: Any, restart_delay: int=30, max_restarts: int=-1, task_type: TaskType=TaskType.PERSISTENT, auto_remove_on_complete: bool | None=None, **kwargs: Any) -> None` — Register `coro_func(*args, **kwargs)` under `name` without starting it; a taken name is an error.
- `def spawn(coro_func: CoroutineFunction, *args: Any, name: str | None=None, **kwargs: Any) -> asyncio.Task[Any]` — Run `coro_func(*args, **kwargs)` right away as a one-off task that is forgotten once it ends.
- `async def start_task(name: str) -> bool` — Start (or restart from scratch, with a fresh restart budget) the registered task `name`.
- `async def stop_task(name: str) -> bool` — Cancel the task and any pending automatic restart; the registration stays.
- `async def remove_task(name: str) -> bool` — Stop the task and drop its registration.
- `async def restart_task(name: str) -> bool` — Restart the task now; counts against `max_restarts` like an automatic restart does.
- `async def start_all() -> None` — Start every registered task that is not already running or waiting for its restart.
- `async def stop_all() -> None` — Cancel every task and pending restart, waiting for each cancellation to land.
- `def stop_all_sync() -> None` — Request cancellation of everything without waiting; for signal handlers and closed loops.
- `def get_task_status(name: str) -> dict[str, Any]` — Live status of one task; an unknown name gives an empty dict.
- `def get_all_status() -> dict[str, dict[str, Any]]` — Live status of every registered task.

## `BaseManager`

class · defined in `oldman.tasks.manager`

```python
class BaseManager(ABC)
```

极简管理器基类 - 只发送任务，不等待结果

Constructor:

```python
BaseManager(worker_class: type[BaseWorker], num_workers: int=4, max_worker_restarts: int=-1, worker_restart_delay: int=5, monitor_interval: int=60, logging_context: ChildLoggingContext | None=None, process_start_method: Literal['spawn', 'forkserver', 'fork']='spawn')
```

Members:

- `async def start()` — 启动管理器
- `async def add_task(task_data: dict[str, Any], task_type: TaskType=TaskType.PERSISTENT, restart_delay: int=5, max_restarts: int=-1, auto_remove_on_complete: bool | None=None) -> str | None` — 添加任务
- `async def stop_task(task_id: str, worker_id: int=-1)` — 停止任务
- `def get_manager_status() -> dict[str, Any]` — 获取管理器状态
- `async def shutdown()` — 关闭管理器

## `BaseTask`

class · defined in `oldman.tasks.base`

```python
class BaseTask(ABC)
```

简化的任务基类 - 只包含核心功能

Constructor:

```python
BaseTask(task_id: str, **kwargs)
```

Members:

- `async def execute() -> Any` — 执行任务的抽象方法
- `def get_running_status() -> dict`
- `async def cleanup() -> None` — 任务清理（默认实现，子类可重写）
- `def update_status(status: TaskStatus) -> None` — 更新任务状态

## `BaseWorker`

class · defined in `oldman.tasks.worker`

```python
class BaseWorker(ABC)
```

简洁的Worker基类 - 只负责进程间通信和任务执行

Constructor:

```python
BaseWorker(worker_id: int, task_queue: mp.Queue)
```

Members:

- `def register_task_creator(task_type: str, creator: TaskCreator)` — 注册任务创建器 - 不再是async
- `async def start()` — 启动worker
- `async def initialize()` — 子类初始化 - 在这里注册任务创建器
- `def get_task_status(task_id: str) -> dict[str, Any]` — 获取任务状态
- `def get_all_task_status() -> dict[str, dict[str, Any]]` — 获取所有任务状态
- `async def cleanup()` — 清理资源

## `TaskInfo`

class · defined in `oldman.tasks.simple`

```python
class TaskInfo
```

Registration record of one supervised coroutine.

Members:

- `name: str`
- `coro_func: Callable[..., Any]`
- `args: tuple[Any, ...] = ()`
- `kwargs: dict[str, Any] = field(default_factory=dict)`
- `restart_delay: int = 30`
- `max_restarts: int = -1`
- `restart_count: int = 0`
- `last_restart: float = 0`
- `status: TaskStatus = TaskStatus.STOPPED`
- `task: asyncio.Task[Any] | None = None`
- `task_type: TaskType = TaskType.PERSISTENT`
- `auto_remove_on_complete: bool = True`
- `remove_on_failure: bool = False`
- `restart_handle: asyncio.TimerHandle | None = None`
- `restart_task_ref: asyncio.Task[Any] | None = None`

## `TaskStatus`

class · defined in `oldman.tasks.base`

```python
class TaskStatus(StrEnum)
```

## `TaskType`

class · defined in `oldman.tasks.base`

```python
class TaskType(StrEnum)
```

## `WorkerInfo`

class · defined in `oldman.tasks.manager`

```python
class WorkerInfo
```

Worker信息

Constructor:

```python
WorkerInfo(worker_id: int, process: mp.Process, task_queue: mp.Queue)
```
