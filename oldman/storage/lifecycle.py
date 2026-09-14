"""根据数据库最终状态清理模型文件列不再引用的 Storage 文件。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import and_, event, inspect, select
from sqlalchemy.orm import Mapper
from sqlalchemy.orm.state import InstanceState
from sqlalchemy.sql.schema import Column
from sqlmodel import Session

from oldman.logging import logger
from oldman.storage.models import (
    _CREATED_FILES_KEY,
    _CreatedFileRecord,
    _get_model_file_config,
)
from oldman.storage.registry import storages

if TYPE_CHECKING:
    from oldman.db.models import ModelMetadata
    from oldman.db.session import DatabaseManager

_STATE_CHANGED_FIELDS_KEY = "oldman_model_file_changed_fields"
_SESSION_CHANGED_STATES_KEY = "oldman_model_file_changed_states"
_SESSION_PENDING_RECORDS_KEY = "oldman_model_file_pending_records"


class OldmanWriteSession(Session):
    """只供 DatabaseManager 写会话使用的内部同步 Session。"""


@dataclass(frozen=True, slots=True)
class _FileField:
    """一个 mapper 文件属性及其 Storage 配置。"""

    name: str
    column: Column[Any]
    storage_alias: str


@dataclass(slots=True)
class _PendingRecord:
    """当前事务第一次文件变化前的数据库快照。"""

    state: InstanceState[Any]
    mapper: Mapper[Any]
    fields: tuple[_FileField, ...]
    original: dict[str, str | None]
    created: dict[str, set[tuple[str, str]]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _CleanupRecord:
    """原 Session 关闭后执行最终状态核对所需的数据。"""

    state: InstanceState[Any]
    mapper: Mapper[Any]
    fields: tuple[_FileField, ...]
    original: tuple[tuple[str, str | None], ...]
    created: tuple[tuple[str, str, str], ...]


_FILE_FIELDS_BY_MAPPER: dict[Mapper[Any], tuple[_FileField, ...]] = {}
_INSTALLED_ATTRIBUTES: set[Any] = set()
_SESSION_EVENTS_INSTALLED = False


def install_model_file_lifecycle(models: Iterable[ModelMetadata]) -> None:
    """只为已注册模型中的 file_column 属性安装轻量变化标记。"""
    global _SESSION_EVENTS_INSTALLED

    found_file_field = False
    for metadata in models:
        mapper = cast(Mapper[Any], inspect(metadata.model))
        fields = _mapper_file_fields(mapper)
        if not fields:
            continue
        found_file_field = True
        _FILE_FIELDS_BY_MAPPER[mapper] = fields
        for file_field in fields:
            attribute = getattr(metadata.model, file_field.name)
            if attribute in _INSTALLED_ATTRIBUTES:
                continue
            event.listen(attribute, "set", _mark_file_assignment, retval=False)
            _INSTALLED_ATTRIBUTES.add(attribute)

    if found_file_field and not _SESSION_EVENTS_INSTALLED:
        event.listen(OldmanWriteSession, "after_attach", _transfer_detached_marker)
        event.listen(OldmanWriteSession, "before_flush", _capture_database_originals)
        _SESSION_EVENTS_INSTALLED = True


def _mapper_file_fields(mapper: Mapper[Any]) -> tuple[_FileField, ...]:
    """读取 mapper 中真实声明为 file_column 的字段。"""
    cached = _FILE_FIELDS_BY_MAPPER.get(mapper)
    if cached is not None:
        return cached
    fields: list[_FileField] = []
    for column in mapper.columns:
        config = _get_model_file_config(column)
        if config is None:
            continue
        property_ = mapper.get_property_by_column(column)
        fields.append(_FileField(name=property_.key, column=column, storage_alias=config.storage))
    resolved = tuple(fields)
    _FILE_FIELDS_BY_MAPPER[mapper] = resolved
    return resolved


def _mark_file_assignment(instance: Any, value: Any, _old_value: Any, initiator: Any) -> Any:
    """属性赋值只写内存标记，不读取旧值或执行 I/O。"""
    state = cast(InstanceState[Any], inspect(instance))
    state.info.setdefault(_STATE_CHANGED_FIELDS_KEY, set()).add(str(initiator.key))
    session = state.session
    if isinstance(session, OldmanWriteSession):
        session.info.setdefault(_SESSION_CHANGED_STATES_KEY, set()).add(state)
    return value


def _transfer_detached_marker(session: OldmanWriteSession, instance: Any) -> None:
    """对象重新挂入写 Session 时转入其 detached 文件变化标记。"""
    state = cast(InstanceState[Any], inspect(instance))
    if state.info.get(_STATE_CHANGED_FIELDS_KEY):
        session.info.setdefault(_SESSION_CHANGED_STATES_KEY, set()).add(state)


def _capture_database_originals(session: OldmanWriteSession, _flush_context: Any, _instances: Any) -> None:
    """第一次真实文件变化或删除前通过当前 Connection 读取数据库原值。"""
    marked_states = cast(set[InstanceState[Any]] | None, session.info.get(_SESSION_CHANGED_STATES_KEY))
    if not marked_states and not session.deleted:
        return
    active_markers = marked_states or set()

    pending = cast(dict[InstanceState[Any], _PendingRecord] | None, session.info.get(_SESSION_PENDING_RECORDS_KEY)) or {}
    for state in tuple(active_markers):
        if state.session is not session:
            active_markers.discard(state)
            continue
        changed_names = state.info.pop(_STATE_CHANGED_FIELDS_KEY, set())
        active_markers.discard(state)
        fields = _mapper_file_fields(state.mapper)
        file_names = {item.name for item in fields}
        has_net_change = any(name in file_names and cast(Any, state).attrs[name].history.has_changes() for name in changed_names)
        if not has_net_change or state.pending or state.identity is None:
            continue
        _ensure_original_snapshot(session, pending, state, fields)

    for instance in tuple(session.deleted):
        state = cast(InstanceState[Any], inspect(instance))
        fields = _mapper_file_fields(state.mapper)
        if fields and state.identity is not None:
            _ensure_original_snapshot(session, pending, state, fields)
    if pending:
        session.info[_SESSION_PENDING_RECORDS_KEY] = pending


def _ensure_original_snapshot(
    session: OldmanWriteSession,
    pending: dict[InstanceState[Any], _PendingRecord],
    state: InstanceState[Any],
    fields: tuple[_FileField, ...],
) -> None:
    """同一记录在一个外层事务中只读取一次全部文件字段。"""
    if state in pending:
        return
    identity = state.identity
    if identity is None:
        return
    conditions = [column == value for column, value in zip(state.mapper.primary_key, identity, strict=True)]
    row = session.connection().execute(select(*(item.column for item in fields)).where(and_(*conditions))).one_or_none()
    original = {item.name: None if row is None else cast(str | None, row._mapping[item.column]) for item in fields}
    pending[state] = _PendingRecord(state=state, mapper=state.mapper, fields=fields, original=original)


def take_file_cleanup_records(session: Any) -> tuple[_CleanupRecord, ...]:
    """从已关闭写 Session 取出并冻结本次文件候选。"""
    pending: dict[InstanceState[Any], _PendingRecord] = session.info.pop(_SESSION_PENDING_RECORDS_KEY, {})
    created: list[_CreatedFileRecord] = session.info.pop(_CREATED_FILES_KEY, [])
    session.info.pop(_SESSION_CHANGED_STATES_KEY, None)

    for item in created:
        state = cast(InstanceState[Any], inspect(item.instance))
        record = pending.get(state)
        if record is None:
            fields = _mapper_file_fields(state.mapper)
            if not any(field.name == item.field_name for field in fields):
                continue
            record = _PendingRecord(state=state, mapper=state.mapper, fields=fields, original={})
            pending[state] = record
        record.created.setdefault(item.field_name, set()).add((item.storage_alias, item.path))

    return tuple(
        _CleanupRecord(
            state=record.state,
            mapper=record.mapper,
            fields=record.fields,
            original=tuple(record.original.items()),
            created=tuple((field_name, alias, path) for field_name, candidates in record.created.items() for alias, path in candidates),
        )
        for record in pending.values()
        if record.original or record.created
    )


async def finalize_model_files(manager: DatabaseManager, records: tuple[_CleanupRecord, ...]) -> None:
    """查询数据库最终值，只删除候选中已不再被引用的文件。"""
    if not records:
        return
    final_values: dict[int, dict[str, str | None]] = {}
    try:
        records_with_identity = [record for record in records if record.state.identity is not None]
        if records_with_identity:
            async with manager.get_read_session() as session:
                for record in records_with_identity:
                    identity = record.state.identity
                    assert identity is not None
                    conditions = [column == value for column, value in zip(record.mapper.primary_key, identity, strict=True)]
                    statement = select(*(item.column for item in record.fields)).where(and_(*conditions))
                    result = await session.exec(cast(Any, statement))
                    row = result.one_or_none()
                    final_values[id(record)] = {
                        item.name: None if row is None else cast(str | None, row._mapping[item.column]) for item in record.fields
                    }
        for record in records:
            final_values.setdefault(id(record), {item.name: None for item in record.fields})
    except Exception as error:
        logger.error("Could not query final database state for model file cleanup: %s", error, exc_info=True)
        return

    for record in records:
        final = final_values[id(record)]
        fields = {item.name: item for item in record.fields}
        candidates: dict[str, set[tuple[str, str]]] = {}
        for field_name, path in record.original:
            if path is not None:
                candidates.setdefault(field_name, set()).add((fields[field_name].storage_alias, path))
        for field_name, alias, path in record.created:
            candidates.setdefault(field_name, set()).add((alias, path))
        for field_name, paths in candidates.items():
            for alias, path in paths:
                if path == final.get(field_name):
                    continue
                try:
                    await storages.using(alias).delete(path)
                except Exception as error:
                    logger.error(
                        "Could not delete unreferenced model file %r from storage %r for %s.%s: %s",
                        path,
                        alias,
                        record.mapper.class_.__qualname__,
                        field_name,
                        error,
                        exc_info=True,
                    )


__all__ = ("OldmanWriteSession", "finalize_model_files", "install_model_file_lifecycle", "take_file_cleanup_records")
