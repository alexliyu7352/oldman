"""Deterministic JSON fixture import and export for registered models."""

from __future__ import annotations

import enum
import heapq
import importlib.util
import json
import math
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    Uuid,
    inspect,
    text,
)
from sqlalchemy.sql.schema import Column
from sqlmodel import select

from oldman.db.models import ModelMetadata
from oldman.db.session import DatabaseManager


class _ModelRegistry(Protocol):
    """只描述 fixture 导入导出实际读取的模型清单。"""

    @property
    def models(self) -> tuple[ModelMetadata, ...]: ...


class _PackageRegistry(Protocol):
    """只描述 fixture 文件查找实际读取的 App 包清单。"""

    @property
    def packages(self) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class _FixtureModel:
    """Resolved model contract used by one fixture operation."""

    identifier: str
    metadata: ModelMetadata
    primary_key: Column[Any]
    fields: dict[str, Column[Any]]
    attributes: dict[str, str]

    @property
    def model(self) -> type[Any]:
        return self.metadata.model


@dataclass(slots=True)
class _FixtureRecord:
    """One fully validated record waiting for dependency ordering."""

    position: int
    fixture_model: _FixtureModel
    primary_key: Any
    fields: dict[str, Any]
    dependencies: set[tuple[str, Any]] = field(default_factory=set)

    @property
    def key(self) -> tuple[str, Any]:
        return self.fixture_model.identifier, self.primary_key


def _resolved_model(metadata: ModelMetadata) -> _FixtureModel:
    """Validate one Registry model and expose its scalar mapped columns."""
    identifier = f"{metadata.app_label}.{metadata.model.__name__}"
    if not metadata.managed:
        raise ValueError(f"Fixture model {identifier!r} is not managed.")

    mapper = inspect(metadata.model)
    primary_keys = tuple(mapper.primary_key)
    if len(primary_keys) != 1:
        raise ValueError(f"Fixture model {identifier!r} must have a single-column primary key.")

    fields: dict[str, Column[Any]] = {}
    attributes: dict[str, str] = {}
    primary_key = primary_keys[0]
    for column in metadata.table.columns:
        try:
            attribute = mapper.get_property_by_column(column).key
        except Exception as exc:
            raise ValueError(f"Fixture model {identifier!r} column {column.key!r} is not mapped to one scalar model attribute.") from exc
        if column is primary_key:
            attributes["__pk__"] = attribute
            continue
        if attribute in fields:
            raise ValueError(f"Fixture model {identifier!r} maps field {attribute!r} more than once.")
        fields[attribute] = column
        attributes[attribute] = attribute
    return _FixtureModel(
        identifier=identifier,
        metadata=metadata,
        primary_key=primary_key,
        fields=fields,
        attributes=attributes,
    )


def _model_index(registry: _ModelRegistry) -> dict[str, ModelMetadata]:
    """Index model metadata while rejecting ambiguous public identifiers."""
    indexed: dict[str, ModelMetadata] = {}
    for metadata in registry.models:
        identifier = f"{metadata.app_label}.{metadata.model.__name__}"
        if identifier in indexed:
            raise ValueError(f"Fixture model identifier {identifier!r} is ambiguous in the App Registry.")
        indexed[identifier] = metadata
    return indexed


def _select_models(
    registry: _ModelRegistry,
    selector: str,
) -> list[_FixtureModel]:
    """Resolve an App label or one exact model identifier."""
    indexed = _model_index(registry)
    if "." in selector:
        metadata = indexed.get(selector)
        if metadata is None:
            raise ValueError(f"Fixture model {selector!r} is not installed.")
        return [_resolved_model(metadata)]

    selected = [_resolved_model(metadata) for identifier, metadata in indexed.items() if identifier.partition(".")[0] == selector]
    if not selected:
        raise ValueError(f"Fixture App {selector!r} is not installed or has no models.")
    return selected


def _ordered_models(models: list[_FixtureModel]) -> list[_FixtureModel]:
    """Return stable model order with referenced tables before dependants."""
    by_table = {item.metadata.table: item for item in models}
    dependencies: dict[str, set[str]] = {item.identifier: set() for item in models}
    by_identifier = {item.identifier: item for item in models}
    for item in models:
        for column in item.metadata.table.columns:
            for foreign_key in column.foreign_keys:
                target = by_table.get(foreign_key.column.table)
                if target is not None and target is not item:
                    dependencies[item.identifier].add(target.identifier)

    ready = [name for name, required in dependencies.items() if not required]
    heapq.heapify(ready)
    ordered: list[_FixtureModel] = []
    while ready:
        name = heapq.heappop(ready)
        ordered.append(by_identifier[name])
        for dependant, required in dependencies.items():
            if name not in required:
                continue
            required.remove(name)
            if not required:
                heapq.heappush(ready, dependant)

    if len(ordered) != len(models):
        cycle = ", ".join(sorted(name for name, value in dependencies.items() if value))
        raise ValueError(f"Fixture model foreign-key cycle cannot be ordered: {cycle}.")
    return ordered


def _json_value(value: Any, *, model: str, field_name: str) -> Any:
    """Convert one ORM value to an explicitly supported JSON value."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{model}.{field_name} contains a non-finite float.")
        return value
    if isinstance(value, enum.Enum):
        return _json_value(value.value, model=model, field_name=field_name)
    if isinstance(value, (date, time, datetime)):
        return value.isoformat()
    if isinstance(value, (Decimal, uuid.UUID)):
        return str(value)
    if isinstance(value, list):
        return [_json_value(item, model=model, field_name=field_name) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _json_value(item, model=model, field_name=field_name) for key, item in value.items()}
    raise ValueError(f"{model}.{field_name} uses unsupported fixture value type {type(value).__name__}.")


async def dump_data(
    registry: _ModelRegistry,
    database_manager: DatabaseManager,
    selector: str,
) -> str:
    """Return one deterministic UTF-8 JSON fixture document."""
    models = _ordered_models(_select_models(registry, selector))
    records: list[dict[str, Any]] = []
    async with database_manager.get_read_session() as session:
        for item in models:
            result = await session.exec(select(item.model).order_by(item.primary_key.asc()))
            for instance in result.all():
                fields = {
                    field_name: _json_value(
                        getattr(instance, attribute),
                        model=item.identifier,
                        field_name=field_name,
                    )
                    for field_name, attribute in item.attributes.items()
                    if field_name != "__pk__"
                }
                records.append(
                    {
                        "model": item.identifier,
                        "pk": _json_value(
                            getattr(instance, item.attributes["__pk__"]),
                            model=item.identifier,
                            field_name="pk",
                        ),
                        "fields": fields,
                    }
                )
    return json.dumps(records, ensure_ascii=False, indent=2) + "\n"


def _expect_type(value: Any, expected: type[Any], *, location: str) -> Any:
    """Reject JSON coercions that would silently change fixture data."""
    if expected is int:
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif expected is float:
        valid = isinstance(value, (int, float)) and not isinstance(value, bool)
    else:
        valid = isinstance(value, expected)
    if not valid:
        raise ValueError(f"{location} must be {expected.__name__}; received {type(value).__name__}.")
    return value


def _column_value(column: Column[Any], value: Any, *, location: str) -> Any:
    """Restore one JSON value according to a supported SQLAlchemy column type."""
    if value is None:
        if not column.nullable:
            raise ValueError(f"{location} cannot be null.")
        return None

    column_type = column.type
    try:
        if isinstance(column_type, Enum):
            enum_class = column_type.enum_class
            if enum_class is None:
                allowed = tuple(column_type.enums)
                if not isinstance(value, str) or value not in allowed:
                    raise ValueError(f"{location} must be one of {allowed!r}.")
                return value
            try:
                return enum_class(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{location} is not a valid {enum_class.__name__} value.") from exc
        if isinstance(column_type, JSON):
            # 同 forms/fields.py：这一句的目的就是让 NaN/Infinity 抛错，
            # orjson 会把它们变成 null，所以这里不能换。
            json.dumps(value, allow_nan=False)
            return value
        if isinstance(column_type, DateTime):
            _expect_type(value, str, location=location)
            return datetime.fromisoformat(value)
        if isinstance(column_type, Date):
            _expect_type(value, str, location=location)
            return date.fromisoformat(value)
        if isinstance(column_type, Time):
            _expect_type(value, str, location=location)
            return time.fromisoformat(value)
        if isinstance(column_type, Numeric):
            _expect_type(value, str, location=location)
            return Decimal(value)
        if isinstance(column_type, Uuid):
            _expect_type(value, str, location=location)
            return uuid.UUID(value)
        if isinstance(column_type, Boolean):
            return _expect_type(value, bool, location=location)
        if isinstance(column_type, Integer):
            return _expect_type(value, int, location=location)
        if isinstance(column_type, Float):
            converted = float(_expect_type(value, float, location=location))
            if not math.isfinite(converted):
                raise ValueError(f"{location} must be finite.")
            return converted
        if isinstance(column_type, (String, Text)):
            return _expect_type(value, str, location=location)
    except (ValueError, TypeError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith(location):
            raise
        raise ValueError(f"{location} has an invalid value: {value!r}.") from exc
    raise ValueError(f"{location} uses unsupported fixture column type {type(column_type).__name__}.")


def _parse_records(
    registry: _ModelRegistry,
    payload: Any,
) -> list[_FixtureRecord]:
    """Validate the complete JSON structure and convert every scalar value."""
    if not isinstance(payload, list):
        raise ValueError("Fixture root must be a JSON array.")
    indexed = _model_index(registry)
    resolved: dict[str, _FixtureModel] = {}
    records: list[_FixtureRecord] = []
    seen: set[tuple[str, Any]] = set()
    for position, raw_record in enumerate(payload):
        prefix = f"Fixture record {position}"
        if not isinstance(raw_record, dict):
            raise ValueError(f"{prefix} must be an object.")
        if set(raw_record) != {"model", "pk", "fields"}:
            raise ValueError(f"{prefix} must contain exactly model, pk and fields.")
        identifier = raw_record["model"]
        if not isinstance(identifier, str):
            raise ValueError(f"{prefix}.model must be a string.")
        metadata = indexed.get(identifier)
        if metadata is None:
            raise ValueError(f"Fixture model {identifier!r} is not installed.")
        fixture_model = resolved.setdefault(identifier, _resolved_model(metadata))
        primary_key = _column_value(
            fixture_model.primary_key,
            raw_record["pk"],
            location=f"{identifier}.pk",
        )
        record_key = identifier, primary_key
        if record_key in seen:
            raise ValueError(f"Fixture contains duplicate record {identifier} pk={primary_key!r}.")
        seen.add(record_key)

        raw_fields = raw_record["fields"]
        if not isinstance(raw_fields, dict) or not all(isinstance(name, str) for name in raw_fields):
            raise ValueError(f"{prefix}.fields must be an object with string keys.")
        unknown = sorted(set(raw_fields) - set(fixture_model.fields))
        if unknown:
            raise ValueError(f"Fixture record {identifier} pk={primary_key!r} has unknown field(s): {', '.join(unknown)}.")
        fields = {
            name: _column_value(
                fixture_model.fields[name],
                value,
                location=f"{identifier}.{name}",
            )
            for name, value in raw_fields.items()
        }
        records.append(
            _FixtureRecord(
                position=position,
                fixture_model=fixture_model,
                primary_key=primary_key,
                fields=fields,
            )
        )
    return records


async def _existing_primary_keys(
    records: list[_FixtureRecord],
    database_manager: DatabaseManager,
) -> dict[str, set[Any]]:
    """Batch-read existing fixture targets without starting a write transaction."""
    requested: dict[str, set[Any]] = defaultdict(set)
    models: dict[str, _FixtureModel] = {}
    for record in records:
        requested[record.fixture_model.identifier].add(record.primary_key)
        models[record.fixture_model.identifier] = record.fixture_model

    existing: dict[str, set[Any]] = defaultdict(set)
    async with database_manager.get_read_session() as session:
        for identifier in sorted(requested):
            item = models[identifier]
            result = await session.exec(select(item.primary_key).where(item.primary_key.in_(requested[identifier])))
            existing[identifier].update(result.all())
    return existing


async def _record_dependencies(
    records: list[_FixtureRecord],
    existing: dict[str, set[Any]],
    database_manager: DatabaseManager,
) -> list[_FixtureRecord]:
    """Validate FK targets in batches and order records before database writes."""
    by_key = {record.key: record for record in records}
    model_by_table = {record.fixture_model.metadata.table: record.fixture_model for record in records}
    referenced_columns = {
        foreign_key.column
        for record in records
        for column in record.fixture_model.metadata.table.columns
        for foreign_key in column.foreign_keys
    }
    target_records: dict[tuple[Column[Any], Any], tuple[str, Any]] = {}
    for record in records:
        values = [(record.fixture_model.primary_key, record.primary_key)]
        values.extend(
            (record.fixture_model.fields[field_name], value)
            for field_name, value in record.fields.items()
        )
        for column, value in values:
            if column in referenced_columns and value is not None:
                target_records.setdefault((column, value), record.key)
    missing_checks: dict[Column[Any], set[Any]] = defaultdict(set)
    missing_context: dict[tuple[Column[Any], Any], list[tuple[_FixtureRecord, str]]] = defaultdict(list)

    for record in records:
        for field_name, value in record.fields.items():
            if value is None:
                continue
            column = record.fixture_model.fields[field_name]
            for foreign_key in column.foreign_keys:
                target_column = foreign_key.column
                target_model = model_by_table.get(target_column.table)
                target_key = target_records.get((target_column, value))
                if target_key is not None and target_model is not None and target_column is target_model.primary_key:
                    if value not in existing[target_key[0]]:
                        record.dependencies.add(target_key)
                    continue
                missing_checks[target_column].add(value)
                missing_context[(target_column, value)].append((record, field_name))

    found: dict[Column[Any], set[Any]] = defaultdict(set)
    if missing_checks:
        async with database_manager.get_read_session() as session:
            for column, values in missing_checks.items():
                result = await session.exec(select(column).where(column.in_(values)))
                found[column].update(result.all())
    for (column, value), contexts in missing_context.items():
        if value in found[column]:
            continue
        target_key = target_records.get((column, value))
        if target_key is not None:
            for record, _field_name in contexts:
                record.dependencies.add(target_key)
            continue
        record, field_name = contexts[0]
        raise ValueError(
            f"Fixture record {record.fixture_model.identifier} pk={record.primary_key!r} field {field_name!r} references missing value {value!r}."
        )

    dependencies = {record.key: set(record.dependencies) for record in records}
    ready = [record.key for record in records if not dependencies[record.key]]
    heapq.heapify(ready)
    ordered: list[_FixtureRecord] = []
    while ready:
        key = heapq.heappop(ready)
        ordered.append(by_key[key])
        for dependant, required in dependencies.items():
            if key not in required:
                continue
            required.remove(key)
            if not required:
                heapq.heappush(ready, dependant)
    if len(ordered) != len(records):
        cycle = ", ".join(
            f"{identifier} pk={primary_key!r}"
            for identifier, primary_key in sorted(
                (key for key, required in dependencies.items() if required),
                key=lambda item: (item[0], repr(item[1])),
            )
        )
        raise ValueError(f"Fixture contains a new-record foreign-key cycle: {cycle}.")
    return ordered


async def _synchronize_sequences(
    records: list[_FixtureRecord],
    database_manager: DatabaseManager,
    session: Any,
) -> None:
    """Advance PostgreSQL integer sequences after importing explicit keys."""
    affected = {
        record.fixture_model.identifier: record.fixture_model
        for record in records
        if isinstance(record.fixture_model.primary_key.type, Integer) and record.fixture_model.primary_key.autoincrement is not False
    }
    if not affected:
        return
    dialect = database_manager.engine.dialect.name
    if dialect in {"sqlite", "mysql"}:
        return
    if dialect != "postgresql":
        raise ValueError(f"Fixture sequence synchronization is not supported for {dialect!r}.")

    for identifier in sorted(affected):
        item = affected[identifier]
        table_name = item.metadata.table.fullname
        column_name = item.primary_key.name
        sequence = await session.scalar(
            text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
            {"table_name": table_name, "column_name": column_name},
        )
        if sequence is None:
            continue
        maximum = (await session.exec(select(item.primary_key).order_by(item.primary_key.desc()).limit(1))).first()
        if maximum is not None:
            await session.execute(
                text("SELECT setval(CAST(:sequence AS regclass), :value, true)"),
                {"sequence": sequence, "value": maximum},
            )


async def load_data(
    registry: _ModelRegistry,
    database_manager: DatabaseManager,
    fixture_path: Path,
) -> int:
    """Validate and atomically create or update every record in one JSON file."""
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read fixture {fixture_path}: {exc}") from exc
    records = _parse_records(registry, payload)
    existing = await _existing_primary_keys(records, database_manager)
    ordered = await _record_dependencies(records, existing, database_manager)

    by_model: dict[str, list[_FixtureRecord]] = defaultdict(list)
    for record in ordered:
        by_model[record.fixture_model.identifier].append(record)
    async with database_manager.get_session() as session:
        objects: dict[tuple[str, Any], Any] = {}
        created_records: list[_FixtureRecord] = []
        for identifier in sorted(by_model):
            item = by_model[identifier][0].fixture_model
            primary_keys = [record.primary_key for record in by_model[identifier]]
            result = await session.exec(select(item.model).where(item.primary_key.in_(primary_keys)))
            for instance in result.all():
                primary_key = getattr(instance, item.attributes["__pk__"])
                objects[(identifier, primary_key)] = instance

        current_identifier: str | None = None
        for record in ordered:
            item = record.fixture_model
            if current_identifier is not None and current_identifier != item.identifier:
                await session.flush()
            current_identifier = item.identifier
            instance = objects.get(record.key)
            if instance is None:
                instance = item.model()
                setattr(instance, item.attributes["__pk__"], record.primary_key)
                session.add(instance)
                created_records.append(record)
            for field_name, value in record.fields.items():
                setattr(instance, item.attributes[field_name], value)
        await session.flush()
        await _synchronize_sequences(created_records, database_manager, session)
    return len(records)


def resolve_fixture_path(registry: _PackageRegistry, value: str | Path) -> Path:
    """Resolve a direct file or one unambiguous installed-App fixture name."""
    candidate = Path(value).expanduser()
    if candidate.exists():
        resolved = candidate.resolve()
        if not resolved.is_file():
            raise ValueError(f"Fixture path is not a regular file: {resolved}.")
        return resolved
    if candidate.is_absolute() or candidate.parent != Path(".") or candidate.suffix:
        raise ValueError(f"Fixture file does not exist: {candidate}.")

    matches: list[Path] = []
    for package in registry.packages:
        specification = importlib.util.find_spec(package)
        if specification is None or specification.submodule_search_locations is None:
            continue
        for location in specification.submodule_search_locations:
            fixture = Path(location) / "fixtures" / f"{candidate.name}.json"
            if fixture.is_file():
                matches.append(fixture.resolve())
    unique = sorted(set(matches))
    if not unique:
        raise ValueError(f"Fixture {candidate.name!r} was not found in any installed App.")
    if len(unique) != 1:
        rendered = ", ".join(str(path) for path in unique)
        raise ValueError(f"Fixture {candidate.name!r} exists in more than one installed App: {rendered}.")
    return unique[0]


__all__ = ["dump_data", "load_data", "resolve_fixture_path"]
