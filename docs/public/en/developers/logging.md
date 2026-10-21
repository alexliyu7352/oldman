# Logging

Applications use standard-library Logger objects without `await` or a separate asynchronous logging API:

```python
from oldman.logging import get_logger, logger

log = get_logger(__name__)
log.info("Imported %s records", 12)
try:
    raise ValueError("example")
except ValueError:
    log.exception("Import failed")
```

`logger` is the framework's default Logger; `get_logger(name)` returns a named Logger. Prefer parameterized logs rather than formatting large objects in advance. Use `exception()` or `exc_info=True` for tracebacks. Do not log passwords, tokens, complete Cookies, or credential-bearing connection URLs.

## Initialization and shutdown

WebApplication, SimpleApplication, and ordinary service commands manage their logging lifecycles. One-off App commands display only warnings and errors in the terminal, with complete logs in their own log files. At DEBUG, the terminal also displays everything; see [CLI reference](cli.md#command-lifecycle). Business modules only obtain Loggers rather than calling `init_logging()` during import.

Standalone Python programs can manage logging explicitly:

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

`init_logging(app_name="DefaultApp", logger_path=None, logger_level=None, config=None, *, color=None)` returns `LoggingRuntime`. Omitted directory, level, and color use current `settings.logging`. An unset level follows `core.debug`: DEBUG when enabled, otherwise INFO. Before configuration initialization, schema defaults apply with INFO. `color` accepts `auto`, `always`, or `never`. `config` is a nested mapping overriding the framework's default logging dictionary, not another configuration-file path.

`get_active_runtime()` returns the current runtime or `None`. Reinitializing with identical settings can reuse it; different settings replace it. `close()` synchronously releases handlers and rotation-coordination threads created by this process and is idempotent. Close after the last cleanup log.

## Output and rotation

By default, logging writes to both terminal and files. Filenames use the application name lowercased with spaces replaced by underscores as their prefix:

- `<prefix>.log`: ordinary and error logs.
- `<prefix>_access.log`: Sanic access logs.
- `<prefix>_database.log`: SQLAlchemy logs.

Files rotate daily by default, retaining three backups. At ordinary INFO level, SQLAlchemy engine/pool/orm thresholds rise to WARNING. Detailed internal SQL logs appear only at DEBUG. Terminal output can use color; file output strips color-control sequences.

Linux file handlers write directly with `O_APPEND`. Each process owns its descriptor, the main process coordinates rotation, and children reopen files after detecting changes. **This is not a queued logging system** and requires no Redis/NATS/consumer process. Synchronous writes still cost formatting and file I/O; zero blocking is not promised. Do not log complete payloads item by item in high-frequency data loops.

Each application should use its own log prefix/directory to prevent independent main processes competing over one rotation target. Do not let another rotation tool manage the same files without reconciling policies.

## Child processes

`runtime.child_context` is a serializable `ChildLoggingContext`. Framework Sanic workers, `AsyncProcessManager`, and `BaseManager` already pass and install it, so applications need no duplicate wiring.

When using multiprocessing yourself, explicitly pass it to the top-level child function, call `context.install()` at the start of the child, and close the returned runtime before exit. Children do not take rotation ownership. Do not pass parent Logger handlers, file descriptors, or thread objects as logging configuration.

Raw `print()` differs from structured logging. Short-lived Python child processes forward stdout/stderr through pipes to the parent terminal; arbitrary external-command output does not automatically become application logs. Callers decide how to capture, decode, and log external commands; see [Processes and background tasks](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/background.md).

<!-- source: zh/developers/logging.md @ ad8aee01 -->
