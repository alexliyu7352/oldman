"""Pydantic settings sources shared by Oldman applications."""

from __future__ import annotations

import copy
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from ruamel.yaml import YAML

yaml = YAML()
yaml.indent(mapping=2, sequence=4, offset=2)


class SettingsFileMissingError(RuntimeError):
    """Raised when the selected YAML settings source cannot find its file."""


@dataclass
class SettingsSourceState:
    """State captured while one settings instance is loaded."""

    config_file: Path
    supplied_values: dict[str, Any] | None = None
    values: dict[str, Any] | None = None


_SOURCE_STATE: ContextVar[SettingsSourceState | None] = ContextVar(
    "oldman_settings_source_state",
    default=None,
)


@contextmanager
def settings_source_context(
    config_file: str | Path,
    *,
    values: Mapping[str, Any] | None = None,
) -> Iterator[SettingsSourceState]:
    """Bind one YAML file or its already-read values to a settings instance."""
    state = SettingsSourceState(
        Path(config_file),
        supplied_values=(copy.deepcopy(dict(values)) if values is not None else None),
    )
    token = _SOURCE_STATE.set(state)
    try:
        yield state
    finally:
        _SOURCE_STATE.reset(token)


class YamlConfigSettingsSource(PydanticBaseSettingsSource):
    """Load the YAML file selected by the active settings source context."""

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        state = _SOURCE_STATE.get()
        if state is None:
            return {}

        if state.supplied_values is not None:
            values = copy.deepcopy(state.supplied_values)
            state.values = copy.deepcopy(values)
            return values

        loader = YAML(typ="safe")
        try:
            with state.config_file.open(encoding="utf-8") as stream:
                loaded = loader.load(stream)
        except FileNotFoundError as exc:
            raise SettingsFileMissingError(f"settings.yaml 不存在，请先显式创建配置文件：{state.config_file}") from exc
        except Exception as exc:
            raise RuntimeError(f"读取 settings.yaml 失败：{state.config_file}") from exc

        if loaded is None:
            values: dict[str, Any] = {}
        elif isinstance(loaded, Mapping):
            values = copy.deepcopy(dict(loaded))
        else:
            raise RuntimeError(f"settings.yaml 顶层必须是 dict：{state.config_file}")

        state.values = copy.deepcopy(values)
        return values

    def __repr__(self) -> str:
        state = _SOURCE_STATE.get()
        config_file = state.config_file if state is not None else None
        return f"YamlConfigSettingsSource(config_file={config_file!r})"


class YamlBaseSettings(BaseSettings):
    """Base settings class whose only business-value source is YAML."""

    model_config = SettingsConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
    )

    @classmethod
    def model_validate(
        cls,
        obj: Any,
        *,
        strict: bool | None = None,
        extra: Any | None = None,
        from_attributes: bool | None = None,
        context: Any | None = None,
        by_alias: bool | None = None,
        by_name: bool | None = None,
    ) -> Self:
        """Keep explicit validation separate from constructor source selection."""
        if not isinstance(obj, Mapping):
            return super().model_validate(
                obj,
                strict=strict,
                extra=extra,
                from_attributes=from_attributes,
                context=context,
                by_alias=by_alias,
                by_name=by_name,
            )
        with settings_source_context("<model_validate>", values=obj):
            return super().model_validate(
                {},
                strict=strict,
                extra=extra,
                from_attributes=from_attributes,
                context=context,
                by_alias=by_alias,
                by_name=by_name,
            )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Ignore init, environment, dotenv and secrets as business settings."""
        del cls, init_settings, env_settings, dotenv_settings, file_secret_settings
        return (YamlConfigSettingsSource(settings_cls),)
