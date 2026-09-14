"""Thin Typer adapter for project-wide database migration commands."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import typer
from alembic.util.exc import CommandError
from sqlalchemy.exc import SQLAlchemyError
from typer.core import TyperCommand, TyperGroup

from oldman.cli.settings import ensure_cwd_on_syspath
from oldman.i18n import gettext

if TYPE_CHECKING:
    from oldman.db.migrations.interaction import MigrationInteraction
    from oldman.db.migrations.project import MigrationProject

ExitWithError = Callable[[str], NoReturn]


def _execute[T](
    operation: Callable[[MigrationProject, MigrationInteraction], T],
    exit_with_error: ExitWithError,
) -> T:
    """Load one project and turn expected command failures into plain CLI errors."""
    try:
        ensure_cwd_on_syspath()
        from oldman.db.migrations.interaction import ConsoleMigrationInteraction
        from oldman.db.migrations.project import load_migration_project

        project = load_migration_project(Path.cwd())
        return operation(project, ConsoleMigrationInteraction())
    except (
        CommandError,
        ImportError,
        OSError,
        RuntimeError,
        SQLAlchemyError,
        SyntaxError,
        ValueError,
    ) as exc:
        exit_with_error(str(exc))


def _execute_read[T](
    operation: Callable[[MigrationProject], T],
    exit_with_error: ExitWithError,
) -> T:
    """Run a read-only project command without constructing an interaction adapter."""
    try:
        ensure_cwd_on_syspath()
        from oldman.db.migrations.project import load_migration_project

        project = load_migration_project(Path.cwd())
        return operation(project)
    except (
        CommandError,
        ImportError,
        OSError,
        RuntimeError,
        SQLAlchemyError,
        SyntaxError,
        ValueError,
    ) as exc:
        exit_with_error(str(exc))


def register_database_commands(
    app: typer.Typer,
    *,
    command_class: type[TyperCommand],
    group_class: type[TyperGroup],
    exit_with_error: ExitWithError,
) -> None:
    """Register the six project-level database commands."""
    database_app = typer.Typer(
        help=gettext("Manage project database migrations."),
        no_args_is_help=True,
        add_completion=False,
        cls=group_class,
        rich_markup_mode=None,
    )

    def makemigrations_command() -> None:
        """Generate one reviewed migration revision."""
        from oldman.db.migrations.commands import makemigrations

        generated = _execute(makemigrations, exit_with_error)
        if generated is None:
            typer.echo(gettext("No migration was generated."))
            return
        typer.echo(
            gettext(
                "Generated %(app)s revision %(revision)s: %(path)s",
                app=generated.app_label,
                revision=generated.revision,
                path=generated.path,
            )
        )

    def migrate_command() -> None:
        """Apply pending project migrations."""
        from oldman.db.migrations.commands import migrate

        result = _execute(migrate, exit_with_error)
        if result.recovered:
            typer.echo(gettext("Recovered Oldman migration state."))
        if result.applied_revisions:
            typer.echo(
                gettext(
                    "Applied revisions: %(revisions)s",
                    revisions=", ".join(result.applied_revisions),
                )
            )
        elif not result.recovered:
            typer.echo(gettext("No pending migrations."))

    def downgrade_command() -> None:
        """Interactively downgrade one App migration branch."""
        from oldman.db.migrations.commands import downgrade

        result = _execute(downgrade, exit_with_error)
        if result is None:
            typer.echo(gettext("No applied App can be downgraded."))
            return
        typer.echo(
            gettext(
                "Downgraded %(app)s to %(revision)s; removed: %(removed)s",
                app=result.app_label,
                revision=result.target_revision,
                removed=", ".join(result.removed_revisions),
            )
        )

    def retire_command() -> None:
        """Stop managing one App while retaining its physical tables."""
        from oldman.db.migrations.commands import retire

        result = _execute(retire, exit_with_error)
        if result is None:
            typer.echo(gettext("No App was retired."))
            return
        typer.echo(
            gettext(
                "Retired %(app)s; retained tables: %(tables)s",
                app=result.app_label,
                tables=", ".join(result.retained_tables) or "none",
            )
        )
        typer.echo(
            gettext(
                "Remove %(package)s from: %(files)s",
                package=result.package,
                files=", ".join(str(path) for path in result.service_config_files)
                or "the project migration App list",
            )
        )

    def status_command() -> None:
        """Show read-only database and source migration status."""
        from oldman.db.migrations.commands import status

        result = _execute_read(status, exit_with_error)
        if not result.present_tables:
            typer.echo(gettext("Migration state: not initialized."))
        elif result.missing_tables:
            typer.echo(
                gettext(
                    "Migration state: incomplete; missing %(tables)s",
                    tables=", ".join(result.missing_tables),
                )
            )
        elif result.owner is None:
            typer.echo(gettext("Migration state: complete tables, but owner is missing."))
        else:
            typer.echo(
                gettext(
                    "Migration owner: %(name)s (%(project_id)s)",
                    name=result.owner.project_name,
                    project_id=result.owner.project_id,
                )
            )
        for item in result.apps:
            typer.echo(
                gettext(
                    "%(app)s: current=%(current)s; heads=%(heads)s; pending=%(pending)s",
                    app=item.app_label,
                    current=", ".join(item.current_revisions) or "none",
                    heads=", ".join(item.source_heads) or "none",
                    pending=", ".join(item.pending_revisions) or "none",
                )
            )

    def history_command() -> None:
        """Show source migration history without connecting to the database."""
        from oldman.db.migrations.commands import history

        result = _execute_read(history, exit_with_error)
        if not result:
            typer.echo(gettext("No registered Apps."))
            return
        for app_history in result:
            typer.echo(f"{app_history.app_label}:")
            if not app_history.revisions:
                typer.echo(gettext("  no revisions"))
                continue
            for revision in app_history.revisions:
                relationships = []
                if revision.down_revisions:
                    relationships.append(
                        "down=" + ",".join(revision.down_revisions)
                    )
                if revision.dependencies:
                    relationships.append(
                        "depends=" + ",".join(revision.dependencies)
                    )
                suffix = f" ({'; '.join(relationships)})" if relationships else ""
                message = f" - {revision.message}" if revision.message else ""
                typer.echo(f"  {revision.revision}{suffix}{message}")

    database_app.command(
        "makemigrations",
        help=gettext("Generate one reviewed migration revision."),
        cls=command_class,
    )(makemigrations_command)
    database_app.command(
        "migrate",
        help=gettext("Apply pending project migrations."),
        cls=command_class,
    )(migrate_command)
    database_app.command(
        "downgrade",
        help=gettext("Downgrade one App migration branch."),
        cls=command_class,
    )(downgrade_command)
    database_app.command(
        "retire",
        help=gettext("Retire one App without dropping its tables."),
        cls=command_class,
    )(retire_command)
    database_app.command(
        "status",
        help=gettext("Show read-only migration status."),
        cls=command_class,
    )(status_command)
    database_app.command(
        "history",
        help=gettext("Show source migration history."),
        cls=command_class,
    )(history_command)
    app.add_typer(database_app, name="db")


__all__ = ["register_database_commands"]
