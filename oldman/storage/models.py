"""SQLAlchemy 模型文件列声明和本次创建文件登记。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import String
from sqlalchemy.orm import MappedColumn, mapped_column

from oldman.storage.base import validate_storage_name

type UploadTo = str | Callable[[Any, str], str]

_MODEL_FILE_INFO_KEY = "oldman_model_file"
_CREATED_FILES_KEY = "oldman_created_model_files"


@dataclass(frozen=True, slots=True)
class _ModelFileConfig:
    """保存在普通 String 列中的文件配置。"""

    upload_to: UploadTo
    storage: str


@dataclass(frozen=True, slots=True)
class _CreatedFileRecord:
    """Storage 本次实际创建且需在事务后核对的文件。"""

    instance: Any
    field_name: str
    storage_alias: str
    path: str


def file_column(
    *,
    upload_to: UploadTo,
    storage: str = "default",
    max_length: int = 255,
    nullable: bool = False,
    **column_kwargs: Any,
) -> MappedColumn[Any]:
    """声明由 Storage 管理、数据库中仍保存逻辑名称的 String 列。"""
    if not isinstance(upload_to, str) and not callable(upload_to):
        raise TypeError("upload_to must be a string or callable")
    if not isinstance(storage, str):
        raise TypeError("storage must be a string alias")
    if not storage.strip():
        raise ValueError("storage alias must not be empty")
    if isinstance(max_length, bool) or not isinstance(max_length, int):
        raise TypeError("max_length must be an integer")
    if max_length <= 0:
        raise ValueError("max_length must be positive")
    if "type_" in column_kwargs:
        raise TypeError("file_column() always uses String and does not accept type_")

    raw_info = column_kwargs.pop("info", None)
    if raw_info is not None and not isinstance(raw_info, Mapping):
        raise TypeError("info must be a mapping")
    info = dict(raw_info or {})
    if _MODEL_FILE_INFO_KEY in info:
        raise ValueError(f"column info key {_MODEL_FILE_INFO_KEY!r} is reserved")
    info[_MODEL_FILE_INFO_KEY] = _ModelFileConfig(upload_to=upload_to, storage=storage)
    return mapped_column(String(max_length), nullable=nullable, info=info, **column_kwargs)


def _get_model_file_config(column: Any) -> _ModelFileConfig | None:
    """读取 file_column 写入的私有列元数据。"""
    config = getattr(column, "info", {}).get(_MODEL_FILE_INFO_KEY)
    return config if isinstance(config, _ModelFileConfig) else None


def _resolve_upload_name(config: _ModelFileConfig, instance: Any, filename: str) -> str:
    """去掉客户端路径，再根据模型文件配置生成 Storage 名称。"""
    if not isinstance(filename, str):
        validate_storage_name(filename)  # type: ignore[arg-type]
    basename = validate_storage_name(PurePosixPath(filename.replace("\\", "/")).name)
    if callable(config.upload_to):
        return config.upload_to(instance, basename)
    return f"{config.upload_to}/{basename}" if config.upload_to else basename


def register_created_file(
    session: Any,
    instance: Any,
    field_name: str,
    storage_alias: str,
    path: str,
) -> None:
    """把本次真实创建的文件登记到当前 Session，供事务后核对。"""
    records = session.info.setdefault(_CREATED_FILES_KEY, [])
    records.append(
        _CreatedFileRecord(
            instance=instance,
            field_name=field_name,
            storage_alias=storage_alias,
            path=path,
        )
    )


__all__ = ("UploadTo", "file_column")
