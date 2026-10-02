# `oldman.processes`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Process execution primitives with explicit lifecycle ownership.

Import with `from oldman.processes import <name>`.

## `AsyncProcessManager`

class · defined in `oldman.processes.executor`

```python
class AsyncProcessManager
```

管理按请求创建的短生命周期异步任务进程。

Constructor:

```python
AsyncProcessManager(workers: int=1, logging_context: ChildLoggingContext | None=None) -> None
```

Members:

- `async def run_with_timeout(target, args=(), _timeout: int=30) -> dict | None` — Run one import-safe, pickleable callable and enforce its timeout.
- `async def shutdown()` — 优雅关闭所有活动进程

## `CompletedSubprocess`

class · defined in `oldman.processes.subprocess`

```python
class CompletedSubprocess
```

Immutable result returned by the one-shot execution helper.

Members:

- `args: tuple[str, ...]`
- `pid: int`
- `supervisor_pid: int`
- `process_group: int`
- `returncode: int`
- `stdout: bytes | None`
- `stderr: bytes | None`
- `def check_returncode() -> None` — Raise a result-bearing error when the command did not succeed.

## `create_subprocess_exec`

function · defined in `oldman.processes.subprocess`

```python
async def create_subprocess_exec(program: CommandArgument, *args: CommandArgument, stdin: Any=None, stdout: Any=None, stderr: Any=None, cwd: str | os.PathLike[str] | None=None, env: Mapping[str, str] | None=None, limit: int=2 ** 16, terminate_grace_period: float=_DEFAULT_TERMINATE_GRACE_PERIOD, kill_timeout: float=_DEFAULT_KILL_TIMEOUT) -> ManagedSubprocess
```

Start one command behind an owner-death-aware Linux group supervisor (see the module for when to use it).

## `ManagedSubprocess`

class · defined in `oldman.processes.subprocess`

```python
class ManagedSubprocess
```

Own one external command, its supervisor and same-group descendants.

Constructor:

```python
ManagedSubprocess(*, command: tuple[str, ...], pid: int, supervisor: asyncio.subprocess.Process, process_group: int, terminate_grace_period: float, kill_timeout: float) -> None
```

Members:

- `property stdin: asyncio.StreamWriter | None` — Return the command's inherited supervisor stdin pipe.
- `property stdout: asyncio.StreamReader | None` — Return the command's inherited supervisor stdout pipe.
- `property stderr: asyncio.StreamReader | None` — Return the command's inherited supervisor stderr pipe.
- `property returncode: int | None` — Return the mirrored command status after the supervisor exits.
- `def send_signal(selected_signal: signal.Signals) -> None` — Send an application signal only to the actual command PID.
- `async def wait(timeout: float | None=None) -> int` — Wait asynchronously, cleaning the whole group on timeout or cancellation.
- `async def communicate(input: bytes | None=None, timeout: float | None=None) -> tuple[bytes | None, bytes | None]` — Drain both pipes while retaining the same timeout/cancellation cleanup.
- `async def terminate() -> int` — Gracefully stop the complete group and escalate after the grace period.
- `async def kill() -> int` — Immediately SIGKILL the complete group and reap the supervisor.

## `ManagedSubprocessError`

class · defined in `oldman.processes.subprocess`

```python
class ManagedSubprocessError(RuntimeError)
```

Base error for managed subprocess startup, execution and cleanup.

## `ProcessTimeoutError`

class · defined in `oldman.processes.executor`

```python
class ProcessTimeoutError(Exception)
```

Because every timeout deserves its moment in the exception spotlight

## `run_foreground`

function · defined in `oldman.processes.foreground`

```python
async def run_foreground(program: CommandArgument, *args: CommandArgument, input: bytes | str | None=None, capture_output: bool=False, text: bool=False, timeout: float | None=None, check: bool=False, cwd: str | os.PathLike[str] | None=None, env: Mapping[str, str] | None=None) -> subprocess.CompletedProcess[Any]
```

Run one command in the foreground, on the caller's terminal, and wait for it to finish.

## `run_subprocess_exec`

function · defined in `oldman.processes.subprocess`

```python
async def run_subprocess_exec(program: CommandArgument, *args: CommandArgument, input: bytes | None=None, capture_output: bool=False, timeout: float | None=None, check: bool=False, stdin: Any=None, stdout: Any=None, stderr: Any=None, cwd: str | os.PathLike[str] | None=None, env: Mapping[str, str] | None=None, limit: int=2 ** 16, terminate_grace_period: float=_DEFAULT_TERMINATE_GRACE_PERIOD, kill_timeout: float=_DEFAULT_KILL_TIMEOUT) -> CompletedSubprocess
```

Run one command to completion with optional capture and return checking.

## `SubprocessCleanupError`

class · defined in `oldman.processes.subprocess`

```python
class SubprocessCleanupError(ManagedSubprocessError)
```

Report live process-group members after bounded SIGKILL cleanup.

Constructor:

```python
SubprocessCleanupError(process_group: int, remaining_pids: tuple[int, ...]) -> None
```

## `SubprocessError`

class · defined in `oldman.processes.subprocess`

```python
class SubprocessError(ManagedSubprocessError)
```

Report a completed non-zero command while preserving its full result.

Constructor:

```python
SubprocessError(result: CompletedSubprocess) -> None
```

## `SubprocessStartError`

class · defined in `oldman.processes.subprocess`

```python
class SubprocessStartError(ManagedSubprocessError)
```

Report a command that could not start behind the private supervisor.

Constructor:

```python
SubprocessStartError(command: tuple[str, ...], message: str) -> None
```

## `SubprocessTimeoutError`

class · defined in `oldman.processes.subprocess`

```python
class SubprocessTimeoutError(TimeoutError, ManagedSubprocessError)
```

Report a timeout only after the complete owned process group is gone.

Constructor:

```python
SubprocessTimeoutError(*, command: tuple[str, ...], pid: int, supervisor_pid: int, process_group: int, timeout: float, stdout: bytes | None=None, stderr: bytes | None=None) -> None
```
