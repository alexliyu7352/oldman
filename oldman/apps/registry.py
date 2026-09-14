"""
@author:alex
@date:2025/6/29
@time:23:01
"""

from __future__ import annotations

__author__ = "alex"
import importlib
import importlib.util
import inspect
import re
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING, Any

from oldman.apps.config import (
    AppConfig,
    AppNotInstalledError,
    AppSettingsNotDefinedError,
)

if TYPE_CHECKING:
    from oldman.cli import Command
    from oldman.db.models import ModelMetadata

_PACKAGE_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


def _model_state() -> tuple[set[object], set[str]]:
    """Snapshot ORM state before importing one App metadata module."""
    from oldman.db.models import Base

    return set(Base.registry.mappers), set(Base.metadata.tables)


def _mapper_names(mappers: set[object]) -> str:
    """Render stable mapped-class names for an early-import error."""
    names = []
    for mapper in mappers:
        mapped_class = getattr(mapper, "class_", None)
        if mapped_class is None:
            names.append(repr(mapper))
        else:
            names.append(f"{mapped_class.__module__}.{mapped_class.__qualname__}")
    return ", ".join(sorted(names))


class AppRegistry:
    """Register App metadata once while preserving the configured package order."""

    def __init__(self) -> None:
        self._by_package: dict[str, AppConfig[Any]] = {}
        self._by_label: dict[str, AppConfig[Any]] = {}
        self._models_loaded = False
        self._commands_loaded = False
        self._views_loaded = False
        self._tasks_loaded = False
        self._events_loaded = False
        self._models: tuple[ModelMetadata, ...] = ()
        self._models_by_type: dict[type[Any], ModelMetadata] = {}
        self._commands: tuple[Command, ...] = ()
        self._commands_by_name: dict[str, Command] = {}
        self._commands_by_app: dict[str, tuple[Command, ...]] = {}

    @property
    def packages(self) -> tuple[str, ...]:
        """Return package paths in their original registration order."""
        return tuple(self._by_package)

    @property
    def labels(self) -> tuple[str, ...]:
        """Return App labels in the corresponding registration order."""
        return tuple(app.label for app in self._by_package.values())

    @property
    def configs(self) -> tuple[AppConfig[Any], ...]:
        """Return registered AppConfig objects without exposing mutable storage."""
        return tuple(self._by_package.values())

    @property
    def models(self) -> tuple[ModelMetadata, ...]:
        """Return resolved mapped model metadata after the model stage."""
        if not self._models_loaded:
            raise RuntimeError("App models have not been loaded.")
        return self._models

    @property
    def commands(self) -> tuple[Command, ...]:
        """Return discovered App commands in configured App and module order."""
        if not self._commands_loaded:
            raise RuntimeError("App commands have not been loaded.")
        return self._commands

    def get_command(self, name: str) -> Command:
        """Return one discovered App command by its service-level CLI name."""
        if not self._commands_loaded:
            raise RuntimeError("App commands have not been loaded.")
        try:
            return self._commands_by_name[name]
        except KeyError as exc:
            raise LookupError(f"App command {name!r} is not registered.") from exc

    def get_app_commands(self, label: str) -> tuple[Command, ...]:
        """Return commands owned by one installed App in declaration order."""
        if not self._commands_loaded:
            raise RuntimeError("App commands have not been loaded.")
        self.get_by_label(label)
        return self._commands_by_app[label]

    def get_model_metadata(self, model: type[Any]) -> ModelMetadata:
        """Return Registry metadata for one mapped model class."""
        if not self._models_loaded:
            raise RuntimeError("App models have not been loaded.")
        try:
            return self._models_by_type[model]
        except KeyError as exc:
            raise LookupError(
                f"Model {model.__module__}.{model.__qualname__} is not registered."
            ) from exc

    def __iter__(self) -> Iterator[AppConfig[Any]]:
        """Iterate over AppConfig objects in configured order."""
        return iter(self._by_package.values())

    def register_packages(self, packages: Iterable[str]) -> None:
        """Import and register each package's sole public AppConfig object."""
        if self._models_loaded or self._commands_loaded or self._views_loaded:
            raise RuntimeError(
                "App packages cannot be registered after model loading starts."
            )
        if isinstance(packages, str):
            raise TypeError("App packages must be provided as an iterable of paths.")
        for package in packages:
            self._register_package(package)

    def _register_package(self, package: str) -> None:
        """Register one package after validating import boundaries and identity."""
        if not isinstance(package, str) or _PACKAGE_PATTERN.fullmatch(package) is None:
            raise ValueError(f"Invalid App package path: {package!r}.")
        if package in self._by_package:
            raise ValueError(f"App package {package!r} was registered more than once.")

        before_mappers, before_tables = _model_state()
        module_name = f"{package}.apps"
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name == module_name or module_name.startswith(f"{exc.name}."):
                raise ImportError(f"App package {package!r} must provide {module_name!r}.") from exc
            raise
        after_mappers, after_tables = _model_state()

        new_mappers = after_mappers - before_mappers
        new_tables = after_tables - before_tables
        if new_mappers or new_tables:
            details = []
            if new_tables:
                details.append(f"tables: {', '.join(sorted(new_tables))}")
            if new_mappers:
                details.append(f"mappers: {_mapper_names(new_mappers)}")
            raise RuntimeError(
                f"Importing App metadata {module_name!r} registered SQLAlchemy "
                f"model state ({'; '.join(details)}). Package roots and apps.py "
                "must not load models before the Registry model phase."
            )

        public_apps = {id(value): value for name, value in vars(module).items() if not name.startswith("_") and isinstance(value, AppConfig)}
        app = getattr(module, "app", None)
        if not isinstance(app, AppConfig) or len(public_apps) != 1 or app not in public_apps.values():
            raise ValueError(f"App package {package!r} must export exactly one public AppConfig object named 'app'; found {len(public_apps)}.")

        previous_package = next(
            (registered_package for registered_package, registered_app in self._by_package.items() if registered_app is app),
            None,
        )
        if previous_package is not None:
            raise ValueError(f"AppConfig {app.label!r} is already registered as {previous_package!r}, not {package!r}.")

        existing = self._by_label.get(app.label)
        if existing is not None:
            existing_package = next(
                registered_package for registered_package, registered_app in self._by_package.items() if registered_app is existing
            )
            raise ValueError(f"App label {app.label!r} is already registered by package {existing_package!r} and cannot also register {package!r}.")

        app._install(self)
        self._by_package[package] = app
        self._by_label[app.label] = app

    def get_by_package(self, package: str) -> AppConfig[Any]:
        """Return a registered AppConfig by its import package."""
        try:
            return self._by_package[package]
        except KeyError as exc:
            raise AppNotInstalledError(f"App package {package!r} is not installed in the current service.") from exc

    def get_by_label(self, label: str) -> AppConfig[Any]:
        """Return a registered AppConfig by its stable label."""
        try:
            return self._by_label[label]
        except KeyError as exc:
            raise AppNotInstalledError(f"App {label!r} is not installed in the current service.") from exc

    def bind_settings(self, label: str, settings: object) -> None:
        """Bind one settings instance after SettingsManager validation."""
        app = self.get_by_label(label)
        settings_model = app.settings_model
        if settings_model is None:
            raise AppSettingsNotDefinedError(f"App {label!r} does not define a settings model.")
        if not isinstance(settings, settings_model):
            raise TypeError(
                f"Settings for App {label!r} must be an instance of {settings_model.__qualname__}, received {type(settings).__qualname__}."
            )
        app._bind_settings(settings)

    def _package_for_model_module(self, module_name: str) -> str | None:
        """Resolve a model module to the longest installed package boundary."""
        matches = [
            package
            for package in self._by_package
            if module_name == package or module_name.startswith(f"{package}.")
        ]
        return max(matches, key=len) if matches else None

    def _load_configured_user_model(
        self,
        user_model_path: str | None = None,
    ) -> tuple[type[Any], str] | None:
        """Load Auth's selected concrete User before ordinary App model modules."""
        auth_config = self._by_package.get("oldman.auth")
        if auth_config is None:
            if user_model_path is not None:
                raise AppNotInstalledError(
                    "A migration User model cannot be selected without installing oldman.auth."
                )
            return None

        from oldman.auth.base import AbstractUser
        from oldman.auth.registry import import_user_model, validate_user_model
        from oldman.auth.settings import AuthSettings
        from oldman.db.models import Base

        if user_model_path is None:
            auth_settings = auth_config.settings
            if not isinstance(auth_settings, AuthSettings):
                raise TypeError("The oldman.auth App must bind AuthSettings.")
            model_path = auth_settings.user_model
        else:
            model_path = AuthSettings(user_model=user_model_path).user_model
        module_name, _, _ = model_path.rpartition(".")
        configured_package = self._package_for_model_module(module_name)
        if configured_package is None:
            raise AppNotInstalledError(
                f"Configured User model {model_path!r} must belong to an App "
                "listed in settings.apps."
            )

        existing_users = [
            mapper.class_
            for mapper in Base.registry.mappers
            if isinstance(mapper.class_, type)
            and issubclass(mapper.class_, AbstractUser)
        ]
        if existing_users:
            selected = next(
                (
                    model
                    for model in existing_users
                    if f"{model.__module__}.{model.__qualname__}" == model_path
                ),
                None,
            )
            if selected is None or len(existing_users) != 1:
                loaded = ", ".join(
                    sorted(
                        f"{model.__module__}.{model.__qualname__}"
                        for model in existing_users
                    )
                )
                raise RuntimeError(
                    "A concrete User model was imported before the Registry "
                    f"model phase ({loaded}); configured model is {model_path!r}."
                )
        else:
            selected = validate_user_model(import_user_model(model_path))

        actual_package = self._package_for_model_module(selected.__module__)
        if actual_package != configured_package:
            raise RuntimeError(
                f"Configured User path {model_path!r} re-exports a model defined "
                f"outside App {configured_package!r}."
            )
        return selected, self._by_package[configured_package].label

    def load_models(self, *, user_model_path: str | None = None) -> None:
        """Import each configured model module and resolve table ownership once."""
        if self._models_loaded:
            return

        user_selection = self._load_configured_user_model(user_model_path)
        user_package = None
        if user_selection is not None:
            user_package = self._package_for_model_module(
                user_selection[0].__module__
            )

        model_modules: dict[str, str] = {}
        for package, config in self._by_package.items():
            if package == "oldman.auth" and user_package != "oldman.auth":
                continue
            module_name = f"{package}.{config.models_module}"
            if importlib.util.find_spec(module_name) is None:
                continue
            importlib.import_module(module_name)
            model_modules[package] = module_name

        from oldman.db.models import assign_model_table_app_labels

        self._models = assign_model_table_app_labels(
            {
                package: config.label
                for package, config in self._by_package.items()
            },
            model_modules,
        )
        if user_selection is not None:
            from oldman.auth.base import (
                AbstractUser,
                assign_user_model_ownership,
            )

            user_model, user_app_label = user_selection
            loaded_users = [
                item.model
                for item in self._models
                if issubclass(item.model, AbstractUser)
            ]
            if loaded_users != [user_model]:
                rendered = ", ".join(
                    f"{model.__module__}.{model.__qualname__}"
                    for model in loaded_users
                )
                raise RuntimeError(
                    "Registry model loading must produce exactly the configured "
                    f"User {user_model.__module__}.{user_model.__qualname__}; "
                    f"loaded: {rendered or 'none'}."
                )
            assign_user_model_ownership(user_model, user_app_label)
        from oldman.storage.lifecycle import install_model_file_lifecycle

        install_model_file_lifecycle(self._models)
        self._models_by_type = {
            metadata.model: metadata
            for metadata in self._models
        }
        self._models_loaded = True

    def load_commands(self) -> None:
        """Import installed Apps' command modules after the model stage."""
        if self._commands_loaded:
            return
        if not self._models_loaded:
            raise RuntimeError("App models must be loaded before App commands.")

        from oldman.cli.commands import Command, validate_command_class

        commands_by_name: dict[str, Command] = {}
        command_app_by_name: dict[str, str] = {}
        commands_by_app: dict[str, tuple[Command, ...]] = {}
        command_owners: dict[type[Command], tuple[str, str]] = {}

        for package, config in self._by_package.items():
            module_name = f"{package}.{config.commands_module}"
            if importlib.util.find_spec(module_name) is None:
                commands_by_app[config.label] = ()
                continue

            before_mappers, before_tables = _model_state()
            module = importlib.import_module(module_name)
            after_mappers, after_tables = _model_state()
            new_mappers = after_mappers - before_mappers
            new_tables = after_tables - before_tables
            if new_mappers or new_tables:
                details = []
                if new_tables:
                    details.append(f"tables: {', '.join(sorted(new_tables))}")
                if new_mappers:
                    details.append(f"mappers: {_mapper_names(new_mappers)}")
                raise RuntimeError(
                    f"Importing App commands {module_name!r} registered "
                    f"SQLAlchemy model state ({'; '.join(details)}). All "
                    "models must be declared during the Registry model stage."
                )

            app_commands: list[Command] = []
            for public_name, value in vars(module).items():
                if (
                    public_name.startswith("_")
                    or not inspect.isclass(value)
                    or value is Command
                    or not issubclass(value, Command)
                    or inspect.isabstract(value)
                ):
                    continue

                previous_owner = command_owners.get(value)
                if previous_owner is not None:
                    previous_app, previous_name = previous_owner
                    raise ValueError(
                        f"Command class {value.__module__}.{value.__qualname__} "
                        f"is exported more than once: {previous_app}.{previous_name} "
                        f"and {config.label}.{public_name}."
                    )
                command_owners[value] = (config.label, public_name)
                validate_command_class(value, app_label=config.label)

                try:
                    command = value()
                except TypeError as exc:
                    raise TypeError(
                        f"Command {value.__module__}.{value.__qualname__} from App "
                        f"{config.label!r} must be constructible without arguments."
                    ) from exc

                existing = commands_by_name.get(command.name)
                if existing is not None:
                    raise ValueError(
                        f"App command {command.name!r} is provided by both "
                        f"{command_app_by_name[command.name]!r} and {config.label!r}."
                    )
                commands_by_name[command.name] = command
                command_app_by_name[command.name] = config.label
                app_commands.append(command)

            commands_by_app[config.label] = tuple(app_commands)

        self._commands = tuple(commands_by_name.values())
        self._commands_by_name = commands_by_name
        self._commands_by_app = commands_by_app
        self._commands_loaded = True

    def load_views(self) -> None:
        """Import each Web module after models without allowing schema changes."""
        if self._views_loaded:
            return
        self._load_runtime_modules("views", "web_module")
        self._views_loaded = True

    def load_tasks(self) -> None:
        """Import only installed Apps' tasks once, without loading Web modules."""
        if self._tasks_loaded:
            return
        self._load_runtime_modules("tasks", "tasks_module")
        self._tasks_loaded = True

    def load_events(self) -> None:
        """Declare installed App handlers once; the caller owns network startup."""
        if self._events_loaded:
            return
        self._load_runtime_modules("events", "events_module")
        self._events_loaded = True

    def _load_runtime_modules(self, stage: str, module_field: str) -> None:
        """Runtime declarations share the existing post-model import boundary."""
        if not self._models_loaded:
            raise RuntimeError(f"App models must be loaded before App {stage}.")

        for package, config in self._by_package.items():
            module_name = f"{package}.{getattr(config, module_field)}"
            if importlib.util.find_spec(module_name) is None:
                continue

            before_mappers, before_tables = _model_state()
            importlib.import_module(module_name)
            after_mappers, after_tables = _model_state()
            new_mappers = after_mappers - before_mappers
            new_tables = after_tables - before_tables
            if new_mappers or new_tables:
                details = []
                if new_tables:
                    details.append(f"tables: {', '.join(sorted(new_tables))}")
                if new_mappers:
                    details.append(f"mappers: {_mapper_names(new_mappers)}")
                raise RuntimeError(
                    f"Importing App {stage} {module_name!r} registered SQLAlchemy "
                    f"model state ({'; '.join(details)}). All models must be "
                    "declared during the Registry model stage."
                )
__all__ = ["AppRegistry"]
