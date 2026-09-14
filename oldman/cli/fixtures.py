"""Service-scoped CLI commands for deterministic JSON fixtures."""

from __future__ import annotations

from pathlib import Path

import typer

from oldman.cli import Command
from oldman.db import db_manager
from oldman.db.fixtures import dump_data, load_data, resolve_fixture_path
from oldman.i18n import gettext
from oldman.i18n import gettext_lazy as _
from oldman.runtime.bootstrap import _get_bootstrap_context


class DumpData(Command):
    """Export one installed App or model as deterministic JSON."""

    name = "dumpdata"
    help = _("Export registered model data as JSON.")
    raw_stdout = True

    async def handle(
        self,
        selector: str,
        output: Path | None = None,
    ) -> None:
        """Write raw JSON to stdout or one explicit UTF-8 file."""
        context = _get_bootstrap_context()
        payload = await dump_data(context.apps, db_manager, selector)
        if output is None:
            typer.echo(payload, nl=False)
            return
        output.write_text(payload, encoding="utf-8")


class LoadData(Command):
    """Load one JSON fixture inside a single database transaction."""

    name = "loaddata"
    help = _("Load registered model data from JSON.")

    async def handle(self, fixture: str) -> str:
        """Resolve one file or installed-App fixture and import it."""
        context = _get_bootstrap_context()
        fixture_path = resolve_fixture_path(context.apps, fixture)
        loaded = await load_data(context.apps, db_manager, fixture_path)
        return gettext(
            "Loaded %(count)s fixture records.",
            count=loaded,
        )


def fixture_commands() -> tuple[Command, Command]:
    """Return the two framework-owned typed service commands."""
    return DumpData(), LoadData()


__all__ = ["DumpData", "LoadData", "fixture_commands"]
