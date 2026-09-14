"""Lazy public entry point for the Oldman command line."""

from __future__ import annotations

import sys

from oldman.cli.commands import Command


def main(argv: list[str] | None = None) -> int:
    """Resolve CLI localization before importing Typer and command modules."""
    import gettext as stdlib_gettext
    import importlib

    from oldman.cli.localization import cli_translation_context
    from oldman.i18n import gettext

    args = list(sys.argv[1:] if argv is None else argv)
    with cli_translation_context(args) as language_state:
        # Typer captures ``gettext.gettext`` while importing its core module.
        # Bridge that one import to Oldman's ContextVar-backed translator, then
        # restore the standard-library function immediately.
        original_gettext = stdlib_gettext.gettext
        stdlib_gettext.gettext = gettext
        try:
            runner = importlib.import_module("oldman.cli._main").run
        finally:
            stdlib_gettext.gettext = original_gettext
        return runner(args, language_state=language_state)


__all__ = ["Command", "main"]
