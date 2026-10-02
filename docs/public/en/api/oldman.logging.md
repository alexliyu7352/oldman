# `oldman.logging`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Stable public logging API for Oldman applications.

Import with `from oldman.logging import <name>`.

## `ChildLoggingContext`

class · defined in `oldman.logging.runtime`

```python
class ChildLoggingContext
```

Pickleable instructions for process-local writers without a coordinator.

Members:

- `log_config: dict[str, Any]`
- `def install() -> LoggingRuntime` — Replace inherited handlers before the child emits its first record.

## `ColorPolicy`

value · defined in `oldman.logging.config`

```python
ColorPolicy = Literal['auto', 'always', 'never']
```

## `get_active_runtime`

function · defined in `oldman.logging.runtime`

```python
def get_active_runtime() -> LoggingRuntime | None
```

Return the active process-local runtime when logging is initialized.

## `get_logger`

function · defined in `oldman.logging.runtime`

```python
def get_logger(name: str) -> logging.Logger
```

Return a standard-library logger without introducing a wrapper type.

## `init_logging`

function · defined in `oldman.logging.runtime`

```python
def init_logging(app_name: str='DefaultApp', logger_path: str | os.PathLike[str] | None=None, logger_level: int | None=None, config: Mapping[str, Any] | None=None, *, color: ColorPolicy | None=None) -> LoggingRuntime
```

Install main-process writers and return their lifecycle owner.

## `logger`

value · defined in `oldman.logging.runtime`

```python
logger = logging.getLogger('default')
```

## `LOGGING_CONFIG_DEFAULTS`

value · defined in `oldman.logging.config`

```python
LOGGING_CONFIG_DEFAULTS: dict[str, Any] = {'version': 1, 'disable_existing_loggers': False, 'formatters': {'generic': {'()': 'oldman.logging.…
```

## `LoggingRuntime`

class · defined in `oldman.logging.runtime`

```python
class LoggingRuntime
```

Own handlers and optional main-process rotation for one process.

Constructor:

```python
LoggingRuntime(*, runtime_id: str, log_config: dict[str, Any], handlers: set[logging.Handler], child_context: ChildLoggingContext, coordinator: RotationCoordinator | None=None, installed_from_context: bool=False) -> None
```

Members:

- `property closed: bool` — Return whether this process-local runtime released its resources.
- `property owns_rotation: bool` — Return whether this runtime created the main-process coordinator.
- `def matches(log_config: Mapping[str, Any], *, owns_rotation: bool) -> bool` — Return whether repeated initialization describes the same local runtime.
- `def close() -> None` — Stop local rotation when owned, then close this process's handlers once.

## `resolve_child_logging_context`

function · defined in `oldman.logging.runtime`

```python
def resolve_child_logging_context(override: ChildLoggingContext | None=None) -> ChildLoggingContext | None
```

Return the logging context a child process should inherit.

## Module `oldman.logging.config`

Pure logging configuration generation for Oldman runtimes.

Import with `from oldman.logging.config import <name>`.

### `build_sink_config`

function · defined in `oldman.logging.config`

```python
def build_sink_config(app_name: str, logger_path: str | os.PathLike[str], logger_level: int, color: ColorPolicy, overrides: Mapping[str, Any] | None=None, *, rotation: RotationSettings | None=None) -> dict[str, Any]
```

Build one independent sink configuration without opening any handlers.

### `RotationSettings`

class · defined in `oldman.logging.config`

```python
class RotationSettings
```

How the file sinks roll over, mirroring the fields on LoggingConfig.

Members:

- `when: str | None = 'D'`
- `interval: int = 1`
- `max_bytes: int = 0`
- `backup_count: int = 3`

## Module `oldman.logging.formatters`

Oldman-owned console and plain-text logging formatters.

Import with `from oldman.logging.formatters import <name>`.

### `AccessConsoleFormatter`

class · defined in `oldman.logging.formatters`

```python
class AccessConsoleFormatter(ConsoleFormatter)
```

Render Sanic access fields safely and fall back to a generic console line.

Constructor:

```python
AccessConsoleFormatter(fmt: str | None=None, datefmt: str | None=None, style: Literal['%', '{', '$']='%', validate: bool=True, *, color: ColorPolicy='auto', stream: Any=None, defaults: dict[str, Any] | None=None) -> None
```

Members:

- `def format(record: logging.LogRecord) -> str` — Fall back instead of leaking a formatter exception into Sanic logging.

### `ConsoleFormatter`

class · defined in `oldman.logging.formatters`

```python
class ConsoleFormatter(logging.Formatter)
```

Color a copied record according to policy without mutating other handlers' input.

Constructor:

```python
ConsoleFormatter(*args: Any, color: ColorPolicy='auto', stream: Any=None, **kwargs: Any) -> None
```

Members:

- `def format(record: logging.LogRecord) -> str` — Render a shallow copy so message, args and level metadata stay unchanged.

### `PlainTextAccessFormatter`

class · defined in `oldman.logging.formatters`

```python
class PlainTextAccessFormatter(PlainTextFormatter)
```

Render Sanic access fields as UTF-8-safe plain text for file handlers.

Constructor:

```python
PlainTextAccessFormatter(fmt: str | None=None, datefmt: str | None=None, style: Literal['%', '{', '$']='%', validate: bool=True, *, defaults: dict[str, Any] | None=None) -> None
```

Members:

- `def format(record: logging.LogRecord) -> str` — Fall back to a generic plain line for incomplete or malformed records.

### `PlainTextFormatter`

class · defined in `oldman.logging.formatters`

```python
class PlainTextFormatter(logging.Formatter)
```

Render a copied record and remove terminal-only markup from the result.

Members:

- `def format(record: logging.LogRecord) -> str` — Keep the source record reusable by console and queue handlers.

### `strip_terminal_markup`

function · defined in `oldman.logging.formatters`

```python
def strip_terminal_markup(text: str) -> str
```

Remove ANSI control sequences and paired Rich markup from file output.

## Module `oldman.logging.handlers`

Linux direct-file handlers and rollover metadata for Oldman logging.

Import with `from oldman.logging.handlers import <name>`.

### `AtomicAppendFileHandler`

class · defined in `oldman.logging.handlers`

```python
class AtomicAppendFileHandler(logging.Handler)
```

Append formatted records through a Linux ``O_APPEND`` file descriptor.

Constructor:

```python
AtomicAppendFileHandler(filename: str | os.PathLike[str], mode: str='a', encoding: str='utf-8', errors: str | None=None, *, when: str | None=None, interval: int=1, backupCount: int=0, maxBytes: int=0, utc: bool=False, atTime: datetime.time | None=None, reopen_check_interval: float=1.0) -> None
```

Members:

- `def emit(record: logging.LogRecord) -> None` — Format, encode and append one record without a Python text buffer.
- `def flush() -> None` — Expose the logging handler contract; writes already enter kernel buffers.
- `def close() -> None` — Close only the descriptor owned by this process and handler instance.

### `RotationPolicy`

class · defined in `oldman.logging.handlers`

```python
class RotationPolicy
```

Describe rollover metadata without giving a writer rollover ownership.

Members:

- `kind: Literal['time', 'size']`
- `when: str | None = None`
- `interval: int = 1`
- `backup_count: int = 0`
- `max_bytes: int = 0`
- `utc: bool = False`
- `at_time: datetime.time | None = None`
- `classmethod def time(when: str, interval: int, backup_count: int, *, utc: bool=False, at_time: datetime.time | None=None) -> RotationPolicy` — Build a time-based policy using stdlib rotating-handler names.
- `classmethod def size(max_bytes: int, backup_count: int) -> RotationPolicy` — Build a size-based policy for coordinator-owned numbered backups.

## Module `oldman.logging.rotation`

Main-process rollover coordination for direct multiprocess log writers.

Import with `from oldman.logging.rotation import <name>`.

### `RotationCoordinator`

class · defined in `oldman.logging.rotation`

```python
class RotationCoordinator
```

Poll Oldman-managed handlers and rotate their paths only in the owner PID.

Constructor:

```python
RotationCoordinator(runtime_id: str, *, check_interval: float=1.0) -> None
```

Members:

- `property is_alive: bool` — Return whether this process owns a currently running coordinator thread.
- `def run_once(now: float | None=None) -> None` — Perform one owner-only discovery and rollover pass synchronously.
- `def start() -> None` — Start exactly one owner thread after validating current path policies.
- `def close(timeout: float=2.0) -> None` — Stop the owner thread and close delayed helper handlers within a bound.
