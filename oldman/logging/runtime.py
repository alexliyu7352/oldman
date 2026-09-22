"""Lifecycle ownership for Oldman's direct multiprocess logging runtime."""

from __future__ import annotations

import logging
import logging.config
import os
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from oldman.logging.config import ColorPolicy, RotationSettings, build_sink_config
from oldman.logging.rotation import RotationCoordinator

logger = logging.getLogger("default")
_active_runtime: LoggingRuntime | None = None
_runtime_lock = threading.RLock()


def _clone_config_value(value: Any) -> Any:
    """Clone configuration containers while retaining opaque user objects."""
    if isinstance(value, Mapping):
        return {key: _clone_config_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clone_config_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_clone_config_value(item) for item in value)
    return value


def get_logger(name: str) -> logging.Logger:
    """Return a standard-library logger without introducing a wrapper type."""
    return logging.getLogger(name)


def _iter_loggers() -> list[logging.Logger]:
    """Return root and every currently materialized logger exactly once."""
    loggers = [logging.getLogger()]
    loggers.extend(entry for entry in logging.root.manager.loggerDict.values() if isinstance(entry, logging.Logger))
    return loggers


def _detach_runtime_handlers(runtime_id: str | None = None) -> set[logging.Handler]:
    """Detach handlers owned by one runtime, or all inherited Oldman runtimes."""
    detached: set[logging.Handler] = set()
    for configured_logger in _iter_loggers():
        for handler in tuple(configured_logger.handlers):
            marker = getattr(handler, "_oldman_runtime_id", None)
            if marker is None or (runtime_id is not None and marker != runtime_id):
                continue
            configured_logger.removeHandler(handler)
            detached.add(handler)
    return detached


def _close_handlers(handlers: set[logging.Handler]) -> None:
    """Flush and close each shared handler object at most once."""
    for handler in handlers:
        try:
            handler.flush()
        finally:
            handler.close()


def _configure_objects(
    log_config: Mapping[str, Any],
    runtime_id: str,
) -> tuple[logging.config.DictConfigurator, dict[str, logging.Handler]]:
    """Construct dictConfig objects without clearing unrelated global handlers."""
    configurator = logging.config.DictConfigurator(_clone_config_value(dict(log_config)))
    config = configurator.config
    if config.get("version") != 1:
        raise ValueError("logging configuration version must be 1")
    if config.get("incremental", False):
        raise ValueError("Oldman runtime logging does not support incremental dictConfig")

    formatters = config.get("formatters", {})
    for name in formatters:
        try:
            formatters[name] = configurator.configure_formatter(formatters[name])
        except Exception as exc:
            raise ValueError(f"unable to configure formatter {name!r}") from exc

    filters = config.get("filters", {})
    for name in filters:
        try:
            filters[name] = configurator.configure_filter(filters[name])
        except Exception as exc:
            raise ValueError(f"unable to configure filter {name!r}") from exc

    configured_handlers: dict[str, logging.Handler] = {}
    deferred: list[str] = []
    handlers = config.get("handlers", {})
    try:
        for name in sorted(handlers):
            try:
                handler = configurator.configure_handler(handlers[name])
            except Exception as exc:
                if " not configured yet" in str(exc.__cause__):
                    deferred.append(name)
                    continue
                raise ValueError(f"unable to configure handler {name!r}") from exc
            handlers[name] = handler
            configured_handlers[name] = handler

        for name in deferred:
            try:
                handler = configurator.configure_handler(handlers[name])
            except Exception as exc:
                raise ValueError(f"unable to configure handler {name!r}") from exc
            handlers[name] = handler
            configured_handlers[name] = handler
    except Exception:
        _close_handlers(set(configured_handlers.values()))
        raise

    for handler in configured_handlers.values():
        handler.__dict__["_oldman_runtime_id"] = runtime_id
    return configurator, configured_handlers


def _configure_logger_preserving_handlers(
    configurator: logging.config.DictConfigurator,
    logger_name: str,
    logger_config: Mapping[str, Any],
) -> None:
    """Apply one named logger route and reattach every unrelated handler."""
    configured_logger = logging.getLogger(logger_name)
    preserved = tuple(configured_logger.handlers)
    configurator.configure_logger(logger_name, cast(Any, logger_config))
    for handler in preserved:
        if handler not in configured_logger.handlers:
            configured_logger.addHandler(handler)


def _configure_root_preserving_handlers(
    configurator: logging.config.DictConfigurator,
    root_config: Mapping[str, Any],
) -> None:
    """Apply the root route and reattach every unrelated handler."""
    root_logger = logging.getLogger()
    preserved = tuple(root_logger.handlers)
    configurator.configure_root(cast(Any, root_config))
    for handler in preserved:
        if handler not in root_logger.handlers:
            root_logger.addHandler(handler)


def _install_sink_config(
    log_config: Mapping[str, Any],
    runtime_id: str,
) -> set[logging.Handler]:
    """Install process-local sinks while preserving third-party logger ownership."""
    configurator, configured_handlers = _configure_objects(log_config, runtime_id)
    with _runtime_lock:
        try:
            # Fork children must close copied file descriptors before reopening paths.
            _close_handlers(_detach_runtime_handlers())
            for name, handler in configured_handlers.items():
                handler.name = name

            config = configurator.config
            for name, logger_config in config.get("loggers", {}).items():
                _configure_logger_preserving_handlers(configurator, name, logger_config)
            root_config = config.get("root")
            if root_config:
                _configure_root_preserving_handlers(configurator, root_config)
        except Exception:
            _close_handlers(set(configured_handlers.values()))
            raise
    return set(configured_handlers.values())


def _ensure_file_directories(log_config: Mapping[str, Any]) -> None:
    """Create parents for every configured filename before handlers open them."""
    handlers = log_config.get("handlers")
    if not isinstance(handlers, Mapping):
        return
    for handler in handlers.values():
        if not isinstance(handler, Mapping) or "filename" not in handler:
            continue
        Path(os.fspath(handler["filename"])).parent.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True, slots=True)
class ChildLoggingContext:
    """Pickleable instructions for process-local writers without a coordinator."""

    log_config: dict[str, Any]

    def install(self) -> LoggingRuntime:
        """Replace inherited handlers before the child emits its first record."""
        return _replace_active_runtime(
            _clone_config_value(self.log_config),
            owns_rotation=False,
            installed_from_context=True,
        )


class LoggingRuntime:
    """Own handlers and optional main-process rotation for one process."""

    def __init__(
        self,
        *,
        runtime_id: str,
        log_config: dict[str, Any],
        handlers: set[logging.Handler],
        child_context: ChildLoggingContext,
        coordinator: RotationCoordinator | None = None,
        installed_from_context: bool = False,
    ) -> None:
        """Capture only resources created for the current process."""
        self.runtime_id = runtime_id
        self.log_config = log_config
        self.child_context = child_context
        self.process_id = os.getpid()
        self._handlers = handlers
        self._coordinator = coordinator
        self.installed_from_context = installed_from_context
        self._closed = False

    @property
    def closed(self) -> bool:
        """Return whether this process-local runtime released its resources."""
        return self._closed

    @property
    def owns_rotation(self) -> bool:
        """Return whether this runtime created the main-process coordinator."""
        return self._coordinator is not None and self.process_id == os.getpid()

    def matches(self, log_config: Mapping[str, Any], *, owns_rotation: bool) -> bool:
        """Return whether repeated initialization describes the same local runtime."""
        return (
            not self._closed and self.process_id == os.getpid() and (self._coordinator is not None) == owns_rotation and self.log_config == log_config
        )

    def close(self) -> None:
        """Stop local rotation when owned, then close this process's handlers once."""
        global _active_runtime

        if self.process_id != os.getpid():
            self._detach_inherited_copy()
            return
        if self._closed:
            return
        self._closed = True
        try:
            if self._coordinator is not None:
                self._coordinator.close()
            with _runtime_lock:
                owned_handlers = _detach_runtime_handlers(self.runtime_id)
                owned_handlers.update(self._handlers)
                _close_handlers(owned_handlers)
        finally:
            if _active_runtime is self:
                _active_runtime = None

    def _detach_inherited_copy(self) -> None:
        """Close fork-copied writer fds without touching the parent's coordinator."""
        global _active_runtime

        if self._closed:
            return
        self._closed = True
        with _runtime_lock:
            owned_handlers = _detach_runtime_handlers(self.runtime_id)
            owned_handlers.update(self._handlers)
            _close_handlers(owned_handlers)
        if _active_runtime is self:
            _active_runtime = None


def get_active_runtime() -> LoggingRuntime | None:
    """Return the active process-local runtime when logging is initialized."""
    return _active_runtime


def resolve_child_logging_context(override: ChildLoggingContext | None = None) -> ChildLoggingContext | None:
    """Return the logging context a child process should inherit.

    Read immediately before the process starts, not at construction: the runtime may not
    exist yet when the parent object is built, and a closed one must not be handed on.
    An explicit `override` always wins.

    Lives here because this package owns both halves of the answer. Two callers - the
    process executor and the task manager - had byte-identical private copies of it.
    """
    if override is not None:
        return override
    runtime = get_active_runtime()
    if runtime is None or runtime.closed:
        return None
    return runtime.child_context


def _close_active_for_replacement(active: LoggingRuntime) -> None:
    """Distinguish same-process shutdown from a forked runtime copy."""
    if active.process_id == os.getpid():
        active.close()
    else:
        active._detach_inherited_copy()


def _new_runtime(
    log_config: dict[str, Any],
    *,
    owns_rotation: bool,
    installed_from_context: bool,
) -> LoggingRuntime:
    """Install writer handlers and optionally start the sole coordinator."""
    runtime_id = uuid.uuid4().hex
    _ensure_file_directories(log_config)
    handlers = _install_sink_config(log_config, runtime_id)
    coordinator: RotationCoordinator | None = None
    try:
        if owns_rotation:
            coordinator = RotationCoordinator(runtime_id)
            coordinator.start()
        return LoggingRuntime(
            runtime_id=runtime_id,
            log_config=log_config,
            handlers=handlers,
            child_context=ChildLoggingContext(
                log_config=_clone_config_value(log_config),
            ),
            coordinator=coordinator,
            installed_from_context=installed_from_context,
        )
    except BaseException:
        if coordinator is not None:
            coordinator.close()
        with _runtime_lock:
            owned_handlers = _detach_runtime_handlers(runtime_id)
            owned_handlers.update(handlers)
            _close_handlers(owned_handlers)
        raise


def _replace_active_runtime(
    log_config: dict[str, Any],
    *,
    owns_rotation: bool,
    installed_from_context: bool,
) -> LoggingRuntime:
    """Reuse an identical local runtime or close it before replacement."""
    global _active_runtime

    active = _active_runtime
    if active is not None and active.matches(log_config, owns_rotation=owns_rotation):
        active.installed_from_context |= installed_from_context
        return active
    if active is not None:
        _close_active_for_replacement(active)
    _active_runtime = _new_runtime(
        log_config,
        owns_rotation=owns_rotation,
        installed_from_context=installed_from_context,
    )
    return _active_runtime


def _configured_logging_defaults() -> Any:
    """Return project logging settings or schema defaults during isolated use."""
    from oldman.conf.schemas import LoggingConfig

    fallback = LoggingConfig()
    try:
        from oldman.conf import settings
    except (ImportError, RuntimeError):
        return fallback
    return settings.logging


def init_logging(
    app_name: str = "DefaultApp",
    logger_path: str | os.PathLike[str] | None = None,
    logger_level: int | None = None,
    config: Mapping[str, Any] | None = None,
    *,
    color: ColorPolicy | None = None,
) -> LoggingRuntime:
    """Install main-process writers and return their lifecycle owner."""
    defaults = _configured_logging_defaults()
    resolved_path = defaults.dir if logger_path is None else logger_path
    resolved_level = defaults.level if logger_level is None else logger_level
    resolved_color = defaults.color if color is None else color
    log_config = build_sink_config(
        app_name,
        resolved_path,
        resolved_level,
        resolved_color,
        config,
        rotation=RotationSettings(
            when=defaults.rotate_when,
            interval=defaults.rotate_interval,
            max_bytes=defaults.max_bytes,
            backup_count=defaults.backup_count,
        ),
    )
    return _replace_active_runtime(
        log_config,
        owns_rotation=True,
        installed_from_context=False,
    )


__all__ = [
    "ChildLoggingContext",
    "LoggingRuntime",
    "get_active_runtime",
    "get_logger",
    "init_logging",
    "logger",
]
