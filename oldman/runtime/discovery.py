"""Discover service definitions without importing application modules."""

from __future__ import annotations

import ast
import importlib
import inspect
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from oldman.runtime.base import BaseApplication


ApplicationBase = Literal["web", "simple", "taskiq_worker", "taskiq_scheduler"]

_APPLICATION_BASES: dict[str, ApplicationBase] = {
    "WebApplication": "web",
    "SimpleApplication": "simple",
    "TaskiqWorkerApplication": "taskiq_worker",
    "TaskiqSchedulerApplication": "taskiq_scheduler",
}
_SERVICE_MODULE_PATTERN = re.compile(r"[a-z][a-z0-9_]*")


@dataclass(frozen=True, slots=True)
class ServiceDefinition:
    """Static facts required to select one service before configuration loads."""

    module_name: str
    module_path: Path
    application_base: ApplicationBase


def _base_name(expression: ast.expr) -> str | None:
    """Return the final name in a direct class base expression."""
    if isinstance(expression, ast.Name):
        return expression.id
    if isinstance(expression, ast.Attribute):
        return expression.attr
    return None


def _application_base(module_path: Path) -> ApplicationBase:
    """Read one service module and identify its sole direct Application class."""
    tree = ast.parse(
        module_path.read_text(encoding="utf-8"),
        filename=str(module_path),
    )
    candidates: list[tuple[str, ApplicationBase]] = []

    for statement in tree.body:
        if not isinstance(statement, ast.ClassDef):
            continue
        bases: set[ApplicationBase] = set()
        for expression in statement.bases:
            name = _base_name(expression)
            if name in _APPLICATION_BASES:
                bases.add(_APPLICATION_BASES[name])
        if len(bases) > 1:
            raise ValueError(f"Service class {statement.name!r} in {module_path} directly inherits more than one supported Application base.")
        if bases:
            candidates.append((statement.name, bases.pop()))

    if len(candidates) != 1:
        raise ValueError(
            f"Service module {module_path} must define exactly one class that "
            "directly inherits WebApplication, SimpleApplication, TaskiqWorkerApplication or TaskiqSchedulerApplication; "
            f"found {len(candidates)}."
        )
    return candidates[0][1]


def discover_service_definitions(
    project_root: str | Path,
) -> dict[str, ServiceDefinition]:
    """Return direct ``services/*.py`` definitions without importing them."""
    services_directory = Path(project_root).resolve() / "services"
    if not services_directory.exists():
        return {}
    if not services_directory.is_dir():
        raise ValueError(f"Services path is not a directory: {services_directory}")

    definitions: dict[str, ServiceDefinition] = {}
    for module_path in sorted(services_directory.iterdir(), key=lambda path: path.name):
        if not module_path.is_file() or module_path.suffix != ".py":
            continue
        module_name = module_path.stem
        if module_name == "__init__" or module_name.startswith("_"):
            continue
        if _SERVICE_MODULE_PATTERN.fullmatch(module_name) is None:
            raise ValueError(f"Invalid service module name {module_path.name!r}; names must match [a-z][a-z0-9_]*.")

        definitions[module_name] = ServiceDefinition(
            module_name=module_name,
            module_path=module_path.resolve(),
            application_base=_application_base(module_path),
        )
    return definitions


def get_service_definition(
    name: str,
    project_root: str | Path,
) -> ServiceDefinition:
    """Return one named service or report the available cold definitions."""
    definitions = discover_service_definitions(project_root)
    try:
        return definitions[name]
    except KeyError as exc:
        available = ", ".join(definitions) or "none"
        raise ValueError(f"Service {name!r} was not found; available services: {available}.") from exc


def _model_state() -> tuple[set[object], set[str]]:
    """Snapshot SQLAlchemy registrations around one controlled import."""
    from oldman.db.models import Base

    return set(Base.registry.mappers), set(Base.metadata.tables)


def _describe_new_mappers(mappers: set[object]) -> str:
    """Return stable mapper names for a configuration error."""
    names = []
    for mapper in mappers:
        mapped_class = getattr(mapper, "class_", None)
        if mapped_class is None:
            names.append(repr(mapper))
        else:
            names.append(f"{mapped_class.__module__}.{mapped_class.__qualname__}")
    return ", ".join(sorted(names))


def load_service_class(definition: ServiceDefinition) -> type[BaseApplication]:
    """Import the selected service and validate it against the cold definition."""
    from oldman.runtime.base import BaseApplication
    from oldman.runtime.simple import SimpleApplication
    from oldman.runtime.taskiq import TaskiqSchedulerApplication, TaskiqWorkerApplication
    from oldman.runtime.web import WebApplication

    before_mappers, before_tables = _model_state()
    module = importlib.import_module(f"services.{definition.module_name}")
    after_mappers, after_tables = _model_state()

    new_mappers = after_mappers - before_mappers
    new_tables = after_tables - before_tables
    if new_mappers or new_tables:
        details = []
        if new_tables:
            details.append(f"tables: {', '.join(sorted(new_tables))}")
        if new_mappers:
            details.append(f"mappers: {_describe_new_mappers(new_mappers)}")
        raise RuntimeError(
            f"Importing service module {module.__name__!r} registered SQLAlchemy "
            f"model state ({'; '.join(details)}). Models must be loaded through "
            "the App Registry after service bootstrap."
        )

    module_file = getattr(module, "__file__", None)
    if module_file is None or Path(module_file).resolve() != definition.module_path.resolve():
        raise ValueError(f"Imported {module.__name__!r} from {module_file!r}, expected {str(definition.module_path)!r}.")

    expected_base: type[BaseApplication]
    if definition.application_base == "web":
        expected_base = WebApplication
    elif definition.application_base == "simple":
        expected_base = SimpleApplication
    elif definition.application_base == "taskiq_worker":
        expected_base = TaskiqWorkerApplication
    elif definition.application_base == "taskiq_scheduler":
        expected_base = TaskiqSchedulerApplication
    else:
        raise ValueError(f"Unknown application base {definition.application_base!r} for service {definition.module_name!r}.")

    application_classes: dict[
        type[BaseApplication],
        set[type[BaseApplication]],
    ] = {}
    for value in vars(module).values():
        if not isinstance(value, type) or value.__module__ != module.__name__:
            continue
        if not issubclass(value, BaseApplication):
            continue
        direct_bases = {WebApplication, SimpleApplication, TaskiqWorkerApplication, TaskiqSchedulerApplication}.intersection(value.__bases__)
        if direct_bases:
            application_classes[value] = direct_bases

    if len(application_classes) != 1:
        raise ValueError(
            f"Imported service module {module.__name__!r} must contain exactly one direct Application class; found {len(application_classes)}."
        )

    service_class = next(iter(application_classes))
    if application_classes[service_class] != {expected_base}:
        raise ValueError(
            f"Service {definition.module_name!r} was statically identified as "
            f"{definition.application_base}, but {service_class.__qualname__} "
            "uses a different direct Application base."
        )
    if inspect.isabstract(service_class):
        raise ValueError(f"Service class {service_class.__qualname__!r} in {module.__name__!r} is abstract.")
    return service_class


__all__ = [
    "ServiceDefinition",
    "discover_service_definitions",
    "get_service_definition",
    "load_service_class",
]
