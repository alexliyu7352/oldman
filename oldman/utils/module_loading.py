"""Load objects that settings name by dotted import path."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from typing import Any


def import_string(dotted_path: str) -> Any:
    """Import the attribute a ``module.attribute`` path names.

    Settings name classes this way: the User model, request authentication methods, login
    backends. The path must hold both a module and an attribute; a bare module name is
    refused rather than guessed at.
    """
    module_name, separator, attribute = dotted_path.rpartition(".")
    if not separator or not module_name or not attribute:
        raise ImportError(f"Invalid import path: {dotted_path!r}")
    module = importlib.import_module(module_name)
    try:
        return getattr(module, attribute)
    except AttributeError as exc:
        raise ImportError(f"Module {module_name!r} has no attribute {attribute!r}") from exc


def build_configured(names: Sequence[str], builtins: Mapping[str, Callable[[], Any]], *, setting: str) -> list[Any]:
    """Build, in order, the objects a settings list names.

    A bare word names one of ``builtins``; anything with a dot is an import path to a
    project's class, built with no arguments. A name listed twice or a bare word that is
    not built in is refused, naming ``setting`` so the error points at the line to fix.
    """
    built: list[Any] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise ValueError(f"{setting} lists {name!r} twice")
        seen.add(name)
        if "." in name:
            factory = import_string(name)
        elif name in builtins:
            factory = builtins[name]
        else:
            known = ", ".join(sorted(builtins))
            raise ValueError(f"{setting} names unknown {name!r}; built in: {known}, or give an import path")
        built.append(factory())
    return built


__all__ = ["build_configured", "import_string"]
