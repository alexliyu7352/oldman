"""Database model primitives and model discovery."""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from types import ModuleType
from typing import Any, cast

from sqlalchemy import Table

from oldman.db.sqlalchemy.models import (
    Base,
    DatabaseModel,
    NativeTimestampsMixin,
    SoftDeleteMixin,
    UtcTimestampsMixin,
    UUIDMixin,
)
from oldman.i18n import LazyTranslation, gettext_lazy

APP_LABEL_INFO_KEY = "oldman_app_label"
MANAGED_INFO_KEY = "oldman_managed"


@dataclass(frozen=True, slots=True)
class ModelMetadata:
    """Framework metadata resolved for one SQLAlchemy mapped class."""

    model: type[Any]
    table: Table
    app_label: str
    verbose_name: str | LazyTranslation
    verbose_name_plural: str | LazyTranslation
    managed: bool


def _app_owner(
    module_name: str,
    package_labels: Mapping[str, str],
) -> str | None:
    """Resolve a definition module by the longest registered package boundary."""
    matches = [
        (package, label)
        for package, label in package_labels.items()
        if module_name == package or module_name.startswith(f"{package}.")
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: len(item[0]))[1]


def _module_tree_tables(module_name: str) -> set[Table]:
    """Return Table objects directly bound in one imported model module tree."""
    tables: set[Table] = set()
    for loaded_name, module in tuple(sys.modules.items()):
        if loaded_name != module_name and not loaded_name.startswith(f"{module_name}."):
            continue
        if not isinstance(module, ModuleType):
            continue
        tables.update(value for value in vars(module).values() if isinstance(value, Table))
    return tables


def _humanize_model_name(name: str) -> str:
    """Convert a Python model class name into a readable default label."""
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).replace("_", " ")
    return words.strip().title()


def _model_meta_value(
    model: type[Any],
    field_name: str,
    default: object,
) -> object:
    """Read one deliberately small inner Meta option without expanding its API."""
    meta = getattr(model, "Meta", None)
    return getattr(meta, field_name, default) if meta is not None else default


def _display_name(
    model: type[Any],
    field_name: str,
    default: str | LazyTranslation,
) -> str | LazyTranslation:
    """Validate one singular or plural model display name."""
    value = _model_meta_value(model, field_name, default)
    if isinstance(value, LazyTranslation):
        if not value.singular.strip():
            raise ValueError(
                f"{model.__module__}.{model.__qualname__}.Meta.{field_name} cannot be empty."
            )
        return value
    if not isinstance(value, str) or not value.strip():
        raise TypeError(
            f"{model.__module__}.{model.__qualname__}.Meta.{field_name} "
            "must be a non-empty string or LazyTranslation."
        )
    return value


def _default_plural(
    singular: str | LazyTranslation,
) -> str | LazyTranslation:
    """Apply the minimal plural fallback without resolving translations."""
    if isinstance(singular, LazyTranslation):
        return gettext_lazy(f"{singular.singular}s", **singular.variables)
    return f"{singular}s"


def resolve_model_display_names(
    model: type[Any],
) -> tuple[str | LazyTranslation, str | LazyTranslation]:
    """Resolve the two supported Model.Meta labels without translating them."""
    singular = _display_name(
        model,
        "verbose_name",
        _humanize_model_name(model.__name__),
    )
    plural = _display_name(
        model,
        "verbose_name_plural",
        _default_plural(singular),
    )
    return singular, plural


def assign_model_table_app_labels(
    package_labels: Mapping[str, str],
    model_modules: Mapping[str, str],
) -> tuple[ModelMetadata, ...]:
    """Assign every Table and return metadata for registered mapped classes."""
    mapped_table_labels: dict[Table, set[str]] = {}
    mapped_classes: list[tuple[type[Any], Table, str]] = []
    for mapper in Base.registry.mappers:
        mapped_class = mapper.class_
        label = _app_owner(mapped_class.__module__, package_labels)
        if label is None:
            qualified_name = (
                f"{mapped_class.__module__}.{mapped_class.__qualname__}"
            )
            raise RuntimeError(
                f"Mapped class {qualified_name!r} is not defined by a registered App."
            )
        table = cast(Table, mapper.local_table)
        mapped_table_labels.setdefault(table, set()).add(label)
        mapped_classes.append((mapped_class, table, label))

    table_labels: dict[Table, str] = {}
    for table, labels in mapped_table_labels.items():
        if len(labels) != 1:
            rendered = ", ".join(sorted(labels))
            raise RuntimeError(
                f"Table {table.fullname!r} is mapped by multiple Apps: {rendered}."
            )
        table_labels[table] = next(iter(labels))

    module_tables = {
        package: _module_tree_tables(module_name)
        for package, module_name in model_modules.items()
    }
    for table in Base.metadata.tables.values():
        if table in table_labels:
            continue
        candidates = {
            package_labels[package]
            for package, tables in module_tables.items()
            if table in tables
        }
        if len(candidates) != 1:
            rendered = ", ".join(sorted(candidates)) or "none"
            raise RuntimeError(
                f"Standalone Table {table.fullname!r} must be bound in exactly "
                f"one registered App model module tree; found: {rendered}."
            )
        table_labels[table] = next(iter(candidates))

    for table, label in table_labels.items():
        configured_label = table.info.get(APP_LABEL_INFO_KEY)
        if configured_label is not None and configured_label != label:
            raise RuntimeError(
                f"Table {table.fullname!r} declares App {configured_label!r}, "
                f"but its model definition belongs to {label!r}."
            )
        table.info[APP_LABEL_INFO_KEY] = label

    metadata: list[ModelMetadata] = []
    table_managed: dict[Table, bool] = {}
    for model, table, label in sorted(
        mapped_classes,
        key=lambda item: (item[0].__module__, item[0].__qualname__),
    ):
        singular, plural = resolve_model_display_names(model)
        managed = _model_meta_value(model, "managed", True)
        if not isinstance(managed, bool):
            raise TypeError(
                f"{model.__module__}.{model.__qualname__}.Meta.managed must be a bool."
            )

        previous_managed = table_managed.setdefault(table, managed)
        if previous_managed is not managed:
            raise RuntimeError(
                f"Mappers sharing Table {table.fullname!r} disagree on Meta.managed."
            )
        configured_managed = table.info.get(MANAGED_INFO_KEY)
        if configured_managed is not None and configured_managed is not managed:
            raise RuntimeError(
                f"Table {table.fullname!r} declares managed={configured_managed!r}, "
                f"but model {model.__qualname__} declares managed={managed!r}."
            )
        table.info[MANAGED_INFO_KEY] = managed
        metadata.append(
            ModelMetadata(
                model=model,
                table=table,
                app_label=label,
                verbose_name=singular,
                verbose_name_plural=plural,
                managed=managed,
            )
        )

    for table in table_labels:
        if table in table_managed:
            continue
        managed = table.info.get(MANAGED_INFO_KEY, True)
        if not isinstance(managed, bool):
            raise TypeError(
                f"Standalone Table {table.fullname!r} info[{MANAGED_INFO_KEY!r}] "
                "must be a bool."
            )
        table.info[MANAGED_INFO_KEY] = managed
    return tuple(metadata)


__all__ = [
    "APP_LABEL_INFO_KEY",
    "Base",
    "DatabaseModel",
    "MANAGED_INFO_KEY",
    "ModelMetadata",
    "NativeTimestampsMixin",
    "SoftDeleteMixin",
    "UUIDMixin",
    "UtcTimestampsMixin",
    "assign_model_table_app_labels",
    "resolve_model_display_names",
]
