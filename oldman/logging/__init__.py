"""Stable public logging API for Oldman applications."""

from oldman.logging.config import (
    LOGGING_CONFIG_DEFAULTS,
    ColorPolicy,
)
from oldman.logging.runtime import (
    ChildLoggingContext,
    LoggingRuntime,
    get_active_runtime,
    get_logger,
    init_logging,
    logger,
    resolve_child_logging_context,
)

__all__ = [
    "ChildLoggingContext",
    "ColorPolicy",
    "LOGGING_CONFIG_DEFAULTS",
    "LoggingRuntime",
    "get_active_runtime",
    "resolve_child_logging_context",
    "get_logger",
    "init_logging",
    "logger",
]
