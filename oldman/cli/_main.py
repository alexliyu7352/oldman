"""Private Typer assembly and command lifecycle for the Oldman CLI."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, NoReturn

import typer
from typer import _click
from typer.core import TyperCommand, TyperGroup, TyperOption
from typer.main import get_command

from oldman.cli.discovery import discover_services
from oldman.cli.i18n_commands import (
    build_frontend_catalogs,
    compile_catalogs,
    extract_catalog,
    initialize_catalog,
    normalize_catalog_locale,
    update_catalogs,
)
from oldman.cli.localization import (
    CLI_LANGUAGE_ENV,
    CLI_LANGUAGE_REGISTRY,
    CliLanguageState,
    save_cli_language,
    use_cli_language,
)
from oldman.cli.scaffold import (
    AppType,
    DatabaseChoice,
    ProjectType,
    ServiceType,
    humanize_name,
    start_app,
    start_project,
    start_service,
)
from oldman.cli.settings import (
    SettingsCliError,
    get_settings_manager,
)
from oldman.cli.staticfiles import collect_static_files
from oldman.conf import SettingsFileMissingError
from oldman.i18n import gettext, gettext_noop
from oldman.runtime.discovery import ServiceDefinition

if TYPE_CHECKING:
    from oldman.apps import AppRegistry
    from oldman.runtime.base import BaseApplication

_ROOT_COMMANDS = {
    "db",
    "i18n",
    "language",
    "startapp",
    "startproject",
    "startservice",
}

# Typer creates this structural text inside its own package. Keeping the keys
# here makes the CLI catalog reproducible without scanning dependency sources.
_TYPER_CATALOG_MESSAGES = (
    gettext_noop("Arguments"),
    gettext_noop("Commands"),
    gettext_noop("Options"),
    gettext_noop("No such command {name!r}."),
    gettext_noop("default: {default}"),
    gettext_noop("required"),
)


def _format_localized_usage(
    command: TyperCommand | TyperGroup,
    ctx: _click.Context,
    formatter: _click.HelpFormatter,
) -> None:
    """Render a usage prefix through Oldman's current CLI catalog."""
    pieces = command.collect_usage_pieces(ctx)
    formatter.write_usage(
        ctx.command_path,
        " ".join(pieces),
        prefix=f"{gettext('Usage')}: ",
    )


class LocalizedTyperCommand(TyperCommand):
    """Typer command with CLI-local structural labels."""

    def format_usage(
        self,
        ctx: _click.Context,
        formatter: _click.HelpFormatter,
    ) -> None:
        """Render the localized command usage line."""
        _format_localized_usage(self, ctx, formatter)

    def get_help_option(self, ctx: _click.Context) -> TyperOption | None:
        """Translate the lazily created command help option."""
        option = super().get_help_option(ctx)
        if option is not None:
            option.help = gettext("Show this message and exit.")
        return option


class LocalizedTyperGroup(TyperGroup):
    """Typer group with CLI-local structural labels."""

    service_command_sections = False

    def format_usage(
        self,
        ctx: _click.Context,
        formatter: _click.HelpFormatter,
    ) -> None:
        """Render the localized group usage line."""
        _format_localized_usage(self, ctx, formatter)

    def get_help_option(self, ctx: _click.Context) -> TyperOption | None:
        """Translate the lazily created group help option."""
        option = super().get_help_option(ctx)
        if option is not None:
            option.help = gettext("Show this message and exit.")
        return option

    def format_commands(
        self,
        ctx: _click.Context,
        formatter: _click.HelpFormatter,
    ) -> None:
        """Separate framework commands and discovered services at the root."""
        commands: list[tuple[str, _click.Command]] = []
        for name in self.list_commands(ctx):
            command = self.get_command(ctx, name)
            if command is not None and not command.hidden:
                commands.append((name, command))
        if not commands:
            return

        limit = formatter.width - 6 - max(len(name) for name, _ in commands)

        def write_section(title: str, entries: list[tuple[str, _click.Command]]) -> None:
            if not entries:
                return
            rows = [(name, command.get_short_help_str(limit)) for name, command in entries]
            with formatter.section(title):
                formatter.write_dl(rows)

        if ctx.parent is not None and not self.service_command_sections:
            write_section(gettext("Commands"), commands)
            return

        if self.service_command_sections:
            service_commands: list[tuple[str, _click.Command]] = []
            app_sections: dict[
                tuple[int, str],
                list[tuple[str, _click.Command]],
            ] = {}
            for name, command in commands:
                callback = command.callback
                app_group = getattr(
                    callback,
                    "__oldman_app_command_group__",
                    None,
                )
                if not isinstance(app_group, str):
                    service_commands.append((name, command))
                    continue
                app_order = getattr(
                    callback,
                    "__oldman_app_command_group_order__",
                    0,
                )
                app_sections.setdefault(
                    (int(app_order), app_group),
                    [],
                ).append((name, command))

            write_section(gettext("Service commands"), service_commands)
            for (_, title), entries in sorted(app_sections.items()):
                write_section(title, entries)
            return

        write_section(
            gettext("Framework commands"),
            [(name, command) for name, command in commands if name in _ROOT_COMMANDS],
        )
        write_section(
            gettext("Services"),
            [(name, command) for name, command in commands if name not in _ROOT_COMMANDS],
        )


class LocalizedServiceTyperGroup(LocalizedTyperGroup):
    """Render one selected service's framework and App command sections."""

    service_command_sections = True


def _exit_with_error(message: str, *, code: int = 2) -> NoReturn:
    """Write one localized CLI error and stop the current callback."""
    typer.echo(gettext("Error: %(error)s", error=message), err=True)
    raise typer.Exit(code)


def _settings_manager(
    definition: ServiceDefinition,
    config_file: Path | None,
) -> Any:
    """Return one service manager or convert a known schema error to exit 2."""
    try:
        return get_settings_manager(definition, config_file)
    except SettingsCliError as exc:
        _exit_with_error(gettext(exc.message, **exc.variables))


def _print_settings_diagnostics(manager: Any) -> None:
    """Write non-fatal settings migration diagnostics to stderr."""
    for message in manager.diagnostics:
        typer.echo(
            gettext("Warning: %(detail)s", detail=message),
            err=True,
        )


def _startproject_command(
    name: Annotated[
        str,
        typer.Argument(help=gettext("Project directory name.")),
    ],
) -> None:
    """Create one project scaffold."""
    project_type = ProjectType(
        typer.prompt(
            gettext("Project type [cli/service/api/web/dashboard]"),
            type=ProjectType,
        )
    )
    if project_type == ProjectType.CLI:
        database = DatabaseChoice.NONE
    else:
        while True:
            database = DatabaseChoice(
                typer.prompt(
                    gettext("Database [none/sqlite/mysql/postgres]"),
                    type=DatabaseChoice,
                )
            )
            if (
                project_type != ProjectType.DASHBOARD
                or database != DatabaseChoice.NONE
            ):
                break
            typer.echo(
                gettext("Dashboard projects require a database."),
                err=True,
            )
    try:
        target = start_project(
            name,
            project_type=project_type,
            db=database,
        )
    except (FileExistsError, ValueError) as exc:
        _exit_with_error(str(exc))
    typer.echo(gettext("Created project at %(path)s", path=target))


def _startapp_command(
    name: Annotated[
        str,
        typer.Argument(help=gettext("Application name.")),
    ],
) -> None:
    """Create one application scaffold."""
    app_type = AppType(
        typer.prompt(
            gettext("App template [service/api/web/dashboard]"),
            type=AppType,
        )
    )
    suggested_display_name = humanize_name(name)
    while True:
        display_name = typer.prompt(
            gettext("Display name"),
            default=suggested_display_name,
        ).strip()
        if display_name:
            break
        typer.echo(gettext("Display name cannot be empty."), err=True)
    try:
        created = start_app(
            name,
            app_type=app_type,
            display_name=display_name,
        )
    except (FileExistsError, ValueError) as exc:
        _exit_with_error(str(exc))
    typer.echo(
        gettext("Created app %(name)s", name=created.app_slug),
    )


def _startservice_command(
    name: Annotated[
        str,
        typer.Argument(help=gettext("Service module name.")),
    ],
) -> None:
    """Create one standalone service module."""
    service_type = ServiceType(
        typer.prompt(
            gettext("Service type [simple/web/taskiq_worker/taskiq_scheduler]"),
            type=ServiceType,
        )
    )
    try:
        created = start_service(name, service_type=service_type)
    except (FileExistsError, ValueError) as exc:
        _exit_with_error(str(exc))
    typer.echo(
        gettext("Created service %(name)s", name=created.service_name),
    )


def _settings_init(
    definition: ServiceDefinition,
    config_file: Path | None,
) -> None:
    """Create one service settings file without importing the service."""
    manager = _settings_manager(definition, config_file)
    try:
        manager.init_config()
    except FileExistsError:
        _exit_with_error(
            gettext(
                "Settings file already exists: %(path)s",
                path=manager.config_file,
            )
        )
    typer.echo(
        gettext("Initialized settings: %(path)s", path=manager.config_file),
    )


def _settings_check(
    definition: ServiceDefinition,
    config_file: Path | None,
) -> None:
    """Validate one service settings file without publishing it."""
    manager = _settings_manager(definition, config_file)
    try:
        manager.check_config()
    except SettingsFileMissingError:
        _exit_with_error(
            gettext(
                "Settings file does not exist: %(path)s. Run `oldman %(service)s settings init` first.",
                path=manager.config_file,
                service=definition.module_name,
            )
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        _exit_with_error(str(exc))
    _print_settings_diagnostics(manager)
    typer.echo(gettext("Settings OK: %(path)s", path=manager.config_file))


def _settings_sync(
    definition: ServiceDefinition,
    config_file: Path | None,
) -> None:
    """Synchronize missing managed settings keys."""
    manager = _settings_manager(definition, config_file)
    try:
        manager.sync_config()
    except SettingsFileMissingError:
        _exit_with_error(
            gettext(
                "Settings file does not exist: %(path)s. Run `oldman %(service)s settings init` first.",
                path=manager.config_file,
                service=definition.module_name,
            )
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        _exit_with_error(str(exc))
    _print_settings_diagnostics(manager)
    typer.echo(
        gettext("Synchronized settings: %(path)s", path=manager.config_file),
    )


def _static_collect(
    definition: ServiceDefinition,
    config_file: Path | None,
    clear: bool,
) -> None:
    """Collect project and installed-App static files for one Web service."""
    try:
        result = collect_static_files(
            definition,
            config_file,
            clear=clear,
        )
    except SettingsCliError as exc:
        _exit_with_error(gettext(exc.message, **exc.variables))
    except SettingsFileMissingError:
        manager = _settings_manager(definition, config_file)
        _exit_with_error(
            gettext(
                "Settings file does not exist: %(path)s. Run `oldman %(service)s settings init` first.",
                path=manager.config_file,
                service=definition.module_name,
            )
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        _exit_with_error(str(exc))

    for conflict in result.conflicts:
        typer.echo(
            gettext(
                "Warning: %(path)s uses %(winner)s; ignored %(ignored)s",
                path=conflict.relative_path,
                winner=conflict.winner,
                ignored=conflict.ignored,
            ),
            err=True,
        )
    typer.echo(
        gettext(
            "Collected static files to %(destination)s: %(copied)s copied, %(unchanged)s unchanged, %(removed)s removed.",
            destination=result.destination,
            copied=result.copied,
            unchanged=result.unchanged,
            removed=result.removed,
        )
    )


def _i18n_extract() -> None:
    """Extract project and framework translation messages."""
    typer.echo(gettext("Extracting messages..."))
    extract_catalog()


def _i18n_init(
    language: Annotated[
        str,
        typer.Argument(help=gettext("Canonical language code.")),
    ],
) -> None:
    """Initialize one project translation catalog."""
    try:
        canonical, locale_name = normalize_catalog_locale(language)
    except (TypeError, ValueError):
        _exit_with_error(gettext("Invalid canonical language code: %(language)s", language=language))
    typer.echo(
        gettext("Initializing locale: %(language)s", language=canonical),
    )
    initialize_catalog(locale_name)


def _i18n_update() -> None:
    """Update all project translation catalogs."""
    typer.echo(gettext("Updating translations..."))
    update_catalogs()


def _i18n_compile() -> None:
    """Compile all project translation catalogs."""
    typer.echo(gettext("Compiling translations..."))
    compile_catalogs()


def _i18n_compile_frontend(
    service: Annotated[
        str,
        typer.Option("--service", help=gettext("Service whose settings describe the languages.")),
    ] = "web",
) -> None:
    """Build the browser catalogs and the language manifest the frontend imports."""
    typer.echo(gettext("Building frontend catalogs..."))
    try:
        build_frontend_catalogs(project_root=Path.cwd(), service=service)
    except ValueError as exc:
        typer.echo(gettext("Error: %(error)s", error=str(exc)), err=True)
        raise typer.Exit(1) from exc


def _register_language_commands(
    app: typer.Typer,
    language_state: CliLanguageState,
) -> None:
    """Register cold CLI-language commands using the resolved invocation state."""
    language_app = typer.Typer(
        help=gettext("Manage CLI display language."),
        cls=LocalizedTyperGroup,
        rich_markup_mode=None,
        add_completion=False,
    )

    def list_languages() -> None:
        """List supported CLI display languages."""
        typer.echo(gettext("Supported CLI languages:"))
        for definition in CLI_LANGUAGE_REGISTRY:
            typer.echo(f"{definition.code}: {definition.name}")

    def show_language() -> None:
        """Show effective, saved, and environment language state."""
        effective = CLI_LANGUAGE_REGISTRY.definition(language_state.effective)
        typer.echo(
            gettext(
                "Current language: %(code)s (%(name)s)",
                code=effective.code,
                name=effective.name,
            )
        )
        if language_state.saved:
            typer.echo(
                gettext(
                    "Saved language: %(language)s",
                    language=language_state.saved,
                )
            )
        else:
            typer.echo(gettext("Saved language: not set"))
        if language_state.source == "environment":
            typer.echo(
                gettext(
                    "Environment override: %(variable)s=%(language)s",
                    variable=CLI_LANGUAGE_ENV,
                    language=language_state.effective,
                )
            )

    def set_language(
        language: Annotated[
            str,
            typer.Argument(help=gettext("CLI language code or registered alias.")),
        ],
    ) -> None:
        """Persist one canonical CLI display language."""
        resolved = CLI_LANGUAGE_REGISTRY.resolve(language)
        if not resolved:
            _exit_with_error(
                gettext(
                    "Unsupported CLI language %(language)s. Supported: %(supported)s",
                    language=language,
                    supported=", ".join(CLI_LANGUAGE_REGISTRY.codes),
                )
            )
        try:
            saved = save_cli_language(resolved)
        except OSError as exc:
            _exit_with_error(str(exc), code=1)
        with use_cli_language(saved):
            typer.echo(
                gettext("CLI language set to %(language)s.", language=saved),
            )

    language_app.command(
        "list",
        help=gettext("List supported CLI languages."),
        cls=LocalizedTyperCommand,
    )(list_languages)
    language_app.command(
        "show",
        help=gettext("Show the current CLI language."),
        cls=LocalizedTyperCommand,
    )(show_language)
    language_app.command(
        "set",
        help=gettext("Set the CLI language."),
        cls=LocalizedTyperCommand,
    )(set_language)
    app.add_typer(language_app, name="language")


def _register_settings_commands(
    app: typer.Typer,
    definition: ServiceDefinition,
) -> None:
    """Register cold settings commands for one static service definition."""
    settings_app = typer.Typer(
        help=gettext("Manage explicit Oldman settings files."),
        cls=LocalizedTyperGroup,
        rich_markup_mode=None,
        add_completion=False,
    )

    def init_settings(
        config_file: Annotated[
            Path | None,
            typer.Option("--config", help=gettext("Settings YAML path.")),
        ] = None,
    ) -> None:
        """Create the selected service's first settings file."""
        _settings_init(definition, config_file)

    def check_settings(
        config_file: Annotated[
            Path | None,
            typer.Option("--config", help=gettext("Settings YAML path.")),
        ] = None,
    ) -> None:
        """Validate the selected service's settings file."""
        _settings_check(definition, config_file)

    def sync_settings(
        config_file: Annotated[
            Path | None,
            typer.Option("--config", help=gettext("Settings YAML path.")),
        ] = None,
    ) -> None:
        """Synchronize the selected service's settings file."""
        _settings_sync(definition, config_file)

    settings_app.command(
        "init",
        help=gettext("Create a settings file explicitly."),
        cls=LocalizedTyperCommand,
    )(init_settings)
    settings_app.command(
        "check",
        help=gettext("Validate the current settings file."),
        cls=LocalizedTyperCommand,
    )(check_settings)
    settings_app.command(
        "sync",
        help=gettext("Add missing managed settings keys."),
        cls=LocalizedTyperCommand,
    )(sync_settings)
    app.add_typer(settings_app, name="settings")


def _register_static_commands(
    app: typer.Typer,
    definition: ServiceDefinition,
) -> None:
    """Register static collection for one statically identified Web service."""
    static_app = typer.Typer(
        help=gettext("Collect project and installed-App static files."),
        cls=LocalizedTyperGroup,
        rich_markup_mode=None,
        add_completion=False,
    )

    def collect_static(
        config_file: Annotated[
            Path | None,
            typer.Option("--config", help=gettext("Settings YAML path.")),
        ] = None,
        clear: Annotated[
            bool,
            typer.Option(
                "--clear",
                help=gettext("Remove previously collected output first."),
            ),
        ] = False,
    ) -> None:
        """Collect assets for the selected Web service."""
        _static_collect(definition, config_file, clear)

    static_app.command(
        "collect",
        help=gettext("Collect static files into settings.web.static.root."),
        cls=LocalizedTyperCommand,
    )(collect_static)
    app.add_typer(static_app, name="static")


def _register_mail_commands(
    app: typer.Typer,
    definition: ServiceDefinition,
) -> None:
    """Register the mail settings check for one service."""
    mail_app = typer.Typer(
        help=gettext("Check outgoing mail settings."),
        cls=LocalizedTyperGroup,
        rich_markup_mode=None,
        add_completion=False,
    )

    def sendtest(
        recipients: Annotated[
            list[str],
            typer.Argument(help=gettext("Recipient addresses.")),
        ],
        config_file: Annotated[
            Path | None,
            typer.Option("--config", help=gettext("Settings YAML path.")),
        ] = None,
    ) -> None:
        """Send one test message through the configured backend."""
        from oldman.cli.mail import send_test_mail

        try:
            result = send_test_mail(
                definition.module_name,
                recipients,
                config_file=config_file,
            )
        except SettingsFileMissingError:
            manager = _settings_manager(definition, config_file)
            _exit_with_error(
                gettext(
                    "Settings file does not exist: %(path)s. Run `oldman %(service)s settings init` first.",
                    path=manager.config_file,
                    service=definition.module_name,
                )
            )
        except Exception as exc:
            _exit_with_error(gettext("Sending the test message failed: %(error)s", error=exc))
        typer.echo(
            gettext(
                "Sent %(count)s test message(s) through %(backend)s.",
                count=result.count,
                backend=result.backend,
            )
        )

    mail_app.command(
        "sendtest",
        help=gettext("Send a test message to the given addresses."),
        cls=LocalizedTyperCommand,
    )(sendtest)
    app.add_typer(mail_app, name="mail")


def _register_shell_command(
    app: typer.Typer,
    definition: ServiceDefinition,
) -> None:
    """Register the public headless bootstrap shell for one service."""

    def shell(
        config_file: Annotated[
            Path | None,
            typer.Option("--config", help=gettext("Settings YAML path.")),
        ] = None,
    ) -> None:
        """Open an interactive interpreter with one bootstrapped context."""
        from oldman.cli.shell import open_service_shell

        try:
            open_service_shell(
                definition.module_name,
                config_file=config_file,
            )
        except SettingsFileMissingError:
            manager = _settings_manager(definition, config_file)
            _exit_with_error(
                gettext(
                    "Settings file does not exist: %(path)s. Run `oldman %(service)s settings init` first.",
                    path=manager.config_file,
                    service=definition.module_name,
                )
            )

    app.command(
        "shell",
        help=gettext("Open a bootstrapped Python shell."),
        cls=LocalizedTyperCommand,
    )(shell)


def _register_i18n_commands(app: typer.Typer) -> None:
    """Register thin project-catalog command adapters."""
    i18n_app = typer.Typer(
        help=gettext("Manage project translation catalogs."),
        cls=LocalizedTyperGroup,
        rich_markup_mode=None,
        add_completion=False,
    )
    i18n_app.command(
        "extract",
        help=gettext("Extract translation messages."),
        cls=LocalizedTyperCommand,
    )(_i18n_extract)
    i18n_app.command(
        "init",
        help=gettext("Initialize a language catalog."),
        cls=LocalizedTyperCommand,
    )(_i18n_init)
    i18n_app.command(
        "update",
        help=gettext("Update translation catalogs."),
        cls=LocalizedTyperCommand,
    )(_i18n_update)
    i18n_app.command(
        "compile",
        help=gettext("Compile translation catalogs."),
        cls=LocalizedTyperCommand,
    )(_i18n_compile)
    i18n_app.command(
        "compile-frontend",
        help=gettext("Build browser catalogs and the frontend language manifest."),
        cls=LocalizedTyperCommand,
    )(_i18n_compile_frontend)
    app.add_typer(i18n_app, name="i18n")


def create_app(
    language_state: CliLanguageState,
    *,
    definitions: dict[str, ServiceDefinition],
    selected_service: str | None = None,
    service_class: type[BaseApplication] | None = None,
    app_registry: AppRegistry | None = None,
) -> typer.Typer:
    """Build root commands and cold service groups for this invocation."""
    app = typer.Typer(
        help=gettext("Oldman application framework command line."),
        no_args_is_help=True,
        cls=LocalizedTyperGroup,
        rich_markup_mode=None,
    )
    app.command(
        "startproject",
        help=gettext("Create an Oldman project scaffold."),
        cls=LocalizedTyperCommand,
    )(_startproject_command)
    app.command(
        "startapp",
        help=gettext("Create an Oldman app module."),
        cls=LocalizedTyperCommand,
    )(_startapp_command)
    app.command(
        "startservice",
        help=gettext("Create an Oldman service entry."),
        cls=LocalizedTyperCommand,
    )(_startservice_command)
    _register_language_commands(app, language_state)
    _register_i18n_commands(app)
    from oldman.cli.database import register_database_commands

    register_database_commands(
        app,
        command_class=LocalizedTyperCommand,
        group_class=LocalizedTyperGroup,
        exit_with_error=_exit_with_error,
    )

    for name, definition in definitions.items():
        if definition.application_base == "web":
            service_help = gettext("Web service %(service)s.", service=name)
        else:
            service_help = gettext(
                "Application service %(service)s.",
                service=name,
            )
        service_app = typer.Typer(
            help=service_help,
            no_args_is_help=True,
            cls=LocalizedServiceTyperGroup,
            rich_markup_mode=None,
            add_completion=False,
        )
        _register_settings_commands(service_app, definition)
        if definition.application_base == "web":
            _register_static_commands(service_app, definition)
        _register_shell_command(service_app, definition)
        _register_mail_commands(service_app, definition)
        if name == selected_service and service_class is not None:
            from oldman.cli.service import register_application_commands

            if app_registry is None:
                raise RuntimeError(
                    "Selected service commands require its bootstrapped App Registry."
                )
            register_application_commands(
                service_app,
                service_class,
                app_registry,
                command_class=LocalizedTyperCommand,
                reserved_names={
                    "mail",
                    "settings",
                    "shell",
                    *({"static"} if definition.application_base == "web" else set()),
                },
            )
        app.add_typer(service_app, name=name)
    return app


def _selected_runtime_service(
    args: list[str],
    definitions: dict[str, ServiceDefinition],
) -> ServiceDefinition | None:
    """Return the service that requires its real Application command set."""
    if not args or args[0].startswith("-") or args[0] in _ROOT_COMMANDS:
        return None
    definition = definitions.get(args[0])
    if definition is None:
        return None
    action = args[1] if len(args) > 1 else ""
    if action in {"mail", "settings", "shell", "static"}:
        return None
    return definition


def _localize_completion_options(command: _click.Command) -> None:
    """Translate the two root completion option descriptions created by Typer."""
    for parameter in command.params:
        option_names = set(getattr(parameter, "opts", ()))
        if not isinstance(parameter, TyperOption):
            continue
        if "--install-completion" in option_names:
            parameter.help = gettext("Install completion for the current shell.")
        elif "--show-completion" in option_names:
            parameter.help = gettext("Show completion for the current shell.")


def _parameter_hint(exc: _click.exceptions.BadParameter) -> str:
    """Return Click's public parameter hint without translating command tokens."""
    if exc.param_hint is not None:
        hints = exc.param_hint
    elif exc.param is not None:
        if exc.ctx is None:
            return ""
        hints = exc.param.get_error_hint(exc.ctx)
    else:
        return ""
    if isinstance(hints, str):
        return hints
    return " / ".join(repr(hint) for hint in hints)


def _localized_bad_parameter_detail(detail: str) -> str:
    """Translate Typer's fixed choice-error phrase while preserving its values."""
    value, separator, choices = detail.partition(" is not one of ")
    if separator and choices.endswith("."):
        return gettext(
            "%(value)s is not one of %(choices)s.",
            value=value,
            choices=choices[:-1],
        )
    return detail


def _localized_click_error_message(
    exc: _click.exceptions.ClickException,
) -> str:
    """Translate common vendored-Click usage errors at the CLI boundary."""
    if isinstance(exc, _click.exceptions.NoSuchOption):
        message = gettext(
            "No such option: %(option)s",
            option=exc.option_name,
        )
        if exc.possibilities:
            message = gettext(
                "%(text)s (Possible options: %(options)s)",
                text=message,
                options=", ".join(sorted(exc.possibilities)),
            )
        return message

    if isinstance(exc, _click.exceptions.MissingParameter):
        parameter_type = exc.param_type
        if parameter_type is None and exc.param is not None:
            parameter_type = exc.param.param_type_name
        parameter = _parameter_hint(exc)
        missing_messages: dict[str, str] = {
            "argument": gettext_noop("Missing argument %(parameter)s."),
            "option": gettext_noop("Missing option %(parameter)s."),
            "parameter": gettext_noop("Missing parameter %(parameter)s."),
        }
        source = missing_messages.get(
            parameter_type or "",
            gettext_noop("Missing parameter %(parameter)s."),
        )
        return gettext(source, parameter=parameter)

    if isinstance(exc, _click.exceptions.BadParameter):
        detail = _localized_bad_parameter_detail(exc.message)
        parameter = _parameter_hint(exc)
        if parameter:
            return gettext(
                "Invalid value for %(parameter)s: %(detail)s",
                parameter=parameter,
                detail=detail,
            )
        return gettext("Invalid value: %(detail)s", detail=detail)

    message = exc.format_message()
    prefix = "Got unexpected extra argument(s) ("
    if message.startswith(prefix) and message.endswith(")"):
        return gettext(
            "Got unexpected extra argument(s): %(arguments)s",
            arguments=message[len(prefix) : -1],
        )
    return message


def _render_click_error(exc: _click.exceptions.ClickException) -> int:
    """Render structural Click errors through the active CLI catalog."""
    if isinstance(exc, _click.exceptions.NoArgsIsHelpError):
        if exc.ctx is not None:
            typer.echo(exc.ctx.get_help())
        return exc.exit_code

    if isinstance(exc, _click.exceptions.UsageError) and exc.ctx is not None:
        typer.echo(exc.ctx.get_usage(), err=True)
        if exc.ctx.command.get_help_option(exc.ctx) is not None:
            typer.echo(
                gettext(
                    "Try '%(command)s --help' for help.",
                    command=exc.ctx.command_path,
                ),
                err=True,
            )
    typer.echo(
        gettext(
            "Error: %(error)s",
            error=_localized_click_error_message(exc),
        ),
        err=True,
    )
    return exc.exit_code


def run(
    args: list[str],
    *,
    language_state: CliLanguageState,
) -> int:
    """Execute one CLI invocation and return its process exit code."""
    try:
        definitions = discover_services()
    except (OSError, SyntaxError, ValueError) as exc:
        typer.echo(gettext("Error: %(error)s", error=str(exc)), err=True)
        return 2

    collisions = sorted(set(definitions) & _ROOT_COMMANDS)
    if collisions:
        typer.echo(
            gettext(
                "Error: Service names conflict with root commands: %(services)s",
                services=", ".join(collisions),
            ),
            err=True,
        )
        return 2

    selected_definition = _selected_runtime_service(args, definitions)
    service_class: type[BaseApplication] | None = None
    app_registry: AppRegistry | None = None
    if selected_definition is not None:
        from oldman.cli.service import load_selected_service

        try:
            service_class, app_registry = load_selected_service(
                selected_definition
            )
        except SettingsFileMissingError:
            config_file = (
                selected_definition.module_path.parent.parent
                / "data"
                / f"{selected_definition.module_name}_settings.yaml"
            )
            typer.echo(
                gettext(
                    "Error: Settings file does not exist: %(path)s. Run `oldman %(service)s settings init` first.",
                    path=config_file,
                    service=selected_definition.module_name,
                ),
                err=True,
            )
            return 2
        except (ImportError, RuntimeError, TypeError, ValueError) as exc:
            typer.echo(gettext("Error: %(error)s", error=str(exc)), err=True)
            return 2

    if app_registry is None:
        catalog_context = nullcontext()
    else:
        from oldman.cli.localization import use_cli_language

        catalog_context = use_cli_language(
            language_state.effective,
            app_packages=app_registry.packages,
        )

    with catalog_context:
        try:
            app = create_app(
                language_state,
                definitions=definitions,
                selected_service=(
                    selected_definition.module_name
                    if selected_definition is not None
                    else None
                ),
                service_class=service_class,
                app_registry=app_registry,
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            typer.echo(gettext("Error: %(error)s", error=str(exc)), err=True)
            return 2
        command = get_command(app)
        _localize_completion_options(command)
        try:
            result = command.main(
                args=args,
                prog_name="oldman",
                standalone_mode=False,
            )
        except _click.exceptions.ClickException as exc:
            return _render_click_error(exc)
        except typer.Abort:
            typer.echo(gettext("Aborted."), err=True)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        return result if isinstance(result, int) else 0


__all__ = ["run"]
