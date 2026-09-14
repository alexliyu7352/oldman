"""Runtime-light contract for commands owned by installed Apps."""

from __future__ import annotations

import inspect
import re
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from oldman.i18n import LazyTranslation

_COMMAND_NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]*")


class Command(ABC):
    """Define one asynchronous App command and its CLI metadata."""

    name: ClassVar[str] = ""
    help: ClassVar[str | LazyTranslation] = ""
    check_pid: ClassVar[bool] = False
    raw_stdout: ClassVar[bool] = False

    @abstractmethod
    async def handle(self, *args: Any, **kwargs: Any) -> Any:
        """Run the command inside the selected service's async lifecycle."""
        raise NotImplementedError


def validate_command_class(command_type: type[Command], *, app_label: str) -> None:
    """Reject command metadata that cannot form a stable CLI contract."""
    name = command_type.name
    if not isinstance(name, str) or _COMMAND_NAME_PATTERN.fullmatch(name) is None:
        raise ValueError(
            f"Command {command_type.__qualname__} from App {app_label!r} has "
            f"invalid name {name!r}; expected [a-z][a-z0-9-]*."
        )

    help_text = command_type.help
    if isinstance(help_text, LazyTranslation):
        if not help_text.singular.strip():
            raise ValueError(
                f"Command {name!r} from App {app_label!r} has empty help text."
            )
    elif not isinstance(help_text, str):
        raise TypeError(
            f"Command {name!r} from App {app_label!r} help must be a string "
            f"or LazyTranslation; received {type(help_text).__name__}."
        )
    elif not help_text.strip():
        raise ValueError(
            f"Command {name!r} from App {app_label!r} has empty help text."
        )

    if type(command_type.check_pid) is not bool:
        raise TypeError(
            f"Command {name!r} from App {app_label!r} check_pid must be bool."
        )
    if type(command_type.raw_stdout) is not bool:
        raise TypeError(f"Command {name!r} from App {app_label!r} raw_stdout must be bool.")

    target = inspect.unwrap(command_type.handle)
    if not inspect.iscoroutinefunction(target):
        raise TypeError(
            f"Command {name!r} from App {app_label!r} must define async handle()."
        )


__all__ = ["Command"]
