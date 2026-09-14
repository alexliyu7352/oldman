"""Runtime command adapters for one selected service."""

from __future__ import annotations

import inspect
from collections.abc import Set as AbstractSet
from pathlib import Path
from typing import Annotated, Any, cast, get_type_hints

import typer
from typer.core import TyperCommand

from oldman.apps import AppRegistry
from oldman.cli import Command
from oldman.cli.settings import ensure_cwd_on_syspath
from oldman.i18n import gettext
from oldman.runtime import bootstrap_service
from oldman.runtime.discovery import ServiceDefinition, load_service_class
from oldman.utils import loop_utls
from oldman.utils.console import console


def load_selected_service(
    definition: ServiceDefinition,
    *,
    config_file: Path | None = None,
) -> tuple[type[Any], AppRegistry]:
    """Bootstrap and import exactly one service for runtime commands."""
    ensure_cwd_on_syspath()
    context = bootstrap_service(
        definition.module_name,
        config_file=config_file,
    )
    context.apps.load_commands()
    loop_utls.use_uvloop()
    return load_service_class(definition), context.apps


def _create_service_command_handler(
    service_class: type[Any],
    command_name: str,
):
    """Create one legacy-shaped callback for a service lifecycle command."""

    def command_handler(
        args: Annotated[
            list[str] | None,
            typer.Argument(
                help=gettext("Command arguments."),
                show_default=False,
            ),
        ] = None,
    ) -> None:
        """Execute one registered application command."""
        try:
            result = service_class.execute_command(command_name, *(args or []))
            if result:
                console.print(str(result))
        except ValueError as exc:
            console.print(
                gettext("Error: %(error)s", error=str(exc)),
                style="bold red",
            )
            raise typer.Exit(1) from exc
        except Exception as exc:
            console.print(
                gettext("Error executing command: %(error)s", error=str(exc)),
                style="bold red",
            )
            raise typer.Exit(1) from exc

    command_handler.__name__ = f"{command_name}_command"
    return command_handler


def _resolved_handle_signature(command: Command) -> inspect.Signature:
    """Resolve postponed annotations before handing a bound handle to Typer."""
    signature = inspect.signature(command.handle)
    hints = get_type_hints(command.handle, include_extras=True)
    parameters = [
        parameter.replace(
            annotation=hints.get(parameter.name, parameter.annotation),
        )
        for parameter in signature.parameters.values()
    ]
    return signature.replace(
        parameters=parameters,
        return_annotation=None,
    )


def _create_typed_command_handler(
    service_class: type[Any],
    command: Command,
    *,
    app_display_name: str | None = None,
    app_order: int = 0,
):
    """Create one typed Typer callback for a framework or App command."""

    def command_handler(*args: Any, **kwargs: Any) -> None:
        """Execute one discovered App command."""
        try:
            result = service_class.execute_app_command(command, *args, **kwargs)
            if result:
                console.print(str(result))
        except ValueError as exc:
            console.print(
                gettext("Error: %(error)s", error=str(exc)),
                style="bold red",
            )
            raise typer.Exit(1) from exc
        except Exception as exc:
            console.print(
                gettext("Error executing command: %(error)s", error=str(exc)),
                style="bold red",
            )
            raise typer.Exit(1) from exc

    command_handler.__name__ = f"{command.name.replace('-', '_')}_command"
    command_handler.__doc__ = str(command.help)
    callback = cast(Any, command_handler)
    callback.__signature__ = _resolved_handle_signature(command)
    if app_display_name is not None:
        callback.__oldman_app_command_group__ = app_display_name
        callback.__oldman_app_command_group_order__ = app_order
    return command_handler


def register_application_commands(
    service_app: typer.Typer,
    service_class: type[Any],
    app_registry: AppRegistry,
    *,
    command_class: type[TyperCommand],
    reserved_names: AbstractSet[str],
) -> None:
    """Attach service commands and installed Apps' typed commands."""
    from oldman.cli.fixtures import fixture_commands

    service_commands = service_class.get_default_commands()
    framework_commands = fixture_commands()
    framework_command_names = {command.name for command in framework_commands}
    app_command_names = {command.name for command in app_registry.commands}
    service_conflicts = sorted(framework_command_names & set(service_commands))
    if service_conflicts:
        raise ValueError(
            gettext(
                "Service command names conflict with framework commands: %(commands)s",
                commands=", ".join(service_conflicts),
            )
        )
    conflicts = sorted(app_command_names & (set(service_commands) | set(reserved_names) | framework_command_names))
    if conflicts:
        raise ValueError(
            gettext(
                "App command names conflict with service commands: %(commands)s",
                commands=", ".join(conflicts),
            )
        )

    for command_name, (_, description) in service_commands.items():
        localized_description = gettext(description)
        handler = _create_service_command_handler(service_class, command_name)
        handler.__doc__ = localized_description
        service_app.command(
            command_name,
            help=localized_description,
            cls=command_class,
        )(handler)

    for command in framework_commands:
        localized_description = str(command.help)
        handler = _create_typed_command_handler(service_class, command)
        service_app.command(
            command.name,
            help=localized_description,
            cls=command_class,
        )(handler)

    for app_order, app_config in enumerate(app_registry):
        app_display_name = str(app_config.display_name)
        for command in app_registry.get_app_commands(app_config.label):
            localized_description = str(command.help)
            handler = _create_typed_command_handler(
                service_class,
                command,
                app_display_name=app_display_name,
                app_order=app_order,
            )
            service_app.command(
                command.name,
                help=localized_description,
                cls=command_class,
            )(handler)


__all__ = ["load_selected_service", "register_application_commands"]
