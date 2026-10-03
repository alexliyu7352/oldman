"""Service-scoped YAML settings loading and management."""

from __future__ import annotations

import base64
import copy
import io
import secrets
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.tokens import CommentToken

from oldman.apps import AppRegistry
from oldman.conf.base import SettingsFileMissingError, new_yaml
from oldman.conf.schemas import DefaultSettings
from oldman.utils.files import atomic_write
from oldman.utils.hash_ids import generate_alphabet

if TYPE_CHECKING:
    from oldman.runtime.discovery import ServiceDefinition


class SettingsManager[T_Settings: DefaultSettings]:
    """Own one service definition, YAML file, Settings and App Registry."""

    def __init__(
        self,
        settings_class: type[T_Settings],
        service_definition: ServiceDefinition,
        config_file: str | Path,
    ) -> None:
        self.settings_class = settings_class
        self.service_definition = service_definition
        self.config_file = Path(config_file)
        self.registry = AppRegistry()
        self.settings: T_Settings | None = None
        self.app_settings: dict[str, BaseModel] = {}
        self._registered_packages: tuple[str, ...] | None = None
        self._last_diagnostics: tuple[str, ...] = ()

    def load(self) -> T_Settings:
        """Validate and publish the selected service's process settings."""
        data = self.read_config()
        settings = self._validate_config_data(
            data,
            require_web_secrets=True,
            bind_app_settings=True,
        )
        return settings

    def check_config(self) -> T_Settings:
        """Validate the complete YAML without writing or binding App settings."""
        data = self.read_config()
        return self._validate_config_data(
            data,
            require_web_secrets=True,
            bind_app_settings=False,
        )

    def read_config(self) -> dict[str, Any]:
        """Read the selected round-trip YAML without changing it."""
        if not self.config_file.exists():
            raise SettingsFileMissingError(f"settings.yaml 不存在，请先显式创建配置文件：{self.config_file}")
        return self._read_config_file()

    def _read_config_file(self, path: Path | None = None) -> dict[str, Any]:
        """Return one mapping while preserving comments for a later sync."""
        config_file = self.config_file if path is None else path
        yaml = self._round_trip_yaml()
        try:
            with config_file.open(encoding="utf-8") as stream:
                data = yaml.load(stream)
        except Exception as exc:  # pragma: no cover - parser error varies by ruamel
            raise RuntimeError(f"读取 settings.yaml 失败：{config_file}") from exc

        if data is None:
            return CommentedMap()
        if not isinstance(data, dict):
            raise RuntimeError(f"settings.yaml 顶层必须是 dict：{config_file}")
        return data

    def write_config(self, data: Mapping[str, Any]) -> None:
        """Validate and explicitly replace the selected YAML contents."""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        managed_data = self._materialize_web_security(data)
        self._validate_config_data(
            managed_data,
            require_web_secrets=True,
            bind_app_settings=False,
        )
        self._write_config_file(managed_data)

    def init_config(self) -> None:
        """Create a missing service YAML with the complete applicable defaults."""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        if self.config_file.exists():
            raise FileExistsError(f"settings.yaml 已存在：{self.config_file}")

        example_file = self.config_file.with_name(f"{self.config_file.stem}.example{self.config_file.suffix}")
        initial = self._read_config_file(example_file) if example_file.is_file() else CommentedMap()
        self._write_config_file(self._synchronize_config(initial))

    def sync_config(self) -> None:
        """Add missing defaults while preserving operator values and comments."""
        self._write_config_file(self._synchronize_config(self.read_config()))

    def _synchronize_config(self, existing: Mapping[str, Any]) -> dict[str, Any]:
        """Fill defaults in one in-memory mapping before any file is changed."""
        settings = self._validate_config_data(
            existing,
            require_web_secrets=False,
            bind_app_settings=False,
        )
        defaults = self._service_payload(settings.model_dump(mode="json"))
        merged = sync_model_mapping(existing, defaults, self.settings_class)

        raw_app_settings = existing.get("app_settings", {})
        app_settings = cast(
            dict[str, Any],
            (copy.deepcopy(raw_app_settings) if isinstance(raw_app_settings, Mapping) else CommentedMap()),
        )
        for label, instance in self.app_settings.items():
            current = app_settings.get(label, {})
            config = self.registry.get_by_label(label)
            settings_model = config.settings_model
            assert settings_model is not None
            app_settings[label] = sync_model_mapping(
                current if isinstance(current, Mapping) else {},
                instance.model_dump(mode="json"),
                settings_model,
            )
        if "app_settings" in merged:
            merged["app_settings"] = app_settings
        elif isinstance(merged, CommentedMap) and "apps" in merged:
            merged.insert(
                list(merged).index("apps") + 1,
                "app_settings",
                app_settings,
            )
        else:
            merged["app_settings"] = app_settings

        if _nested_key_missing(existing, "web", "messages", "enabled"):
            self._apply_admin_messages_default(merged)
        managed_data = self._materialize_web_security(merged)
        self._validate_config_data(
            managed_data,
            require_web_secrets=True,
            bind_app_settings=False,
        )
        return managed_data

    @property
    def diagnostics(self) -> tuple[str, ...]:
        """Return non-fatal advice from the last successful validation."""
        return self._last_diagnostics

    def inspect_diagnostics(self, data: Mapping[str, Any]) -> tuple[str, ...]:
        """Report keys the settings do not declare, at every level, and service/App usage warnings.

        Nested sections ignore undeclared keys rather than refuse them, so a misspelt key would
        otherwise be dropped without a word. App settings are left out: they refuse unknown keys
        outright.
        """
        global_data = {key: value for key, value in data.items() if key != "app_settings"}
        diagnostics = unknown_settings_keys(global_data, self.settings_class)
        if self.service_definition.application_base == "simple" and "admin" in self.registry.labels:
            diagnostics.append(
                "Admin is installed on a SimpleApplication service; its Web views "
                "will not be loaded. Use WebApplication when an Admin UI is required."
            )
        return tuple(dict.fromkeys(diagnostics))

    def _validate_config_data(
        self,
        data: Mapping[str, Any],
        *,
        require_web_secrets: bool,
        bind_app_settings: bool,
    ) -> T_Settings:
        """Resolve App metadata before validating the two settings namespaces."""
        packages, raw_app_settings = self._raw_app_metadata(data)
        self._ensure_registry(packages)

        global_data = cast(dict[str, Any], copy.deepcopy(data))
        global_data.pop("app_settings", None)

        settings = self._build_global_settings(global_data)
        if settings.apps != packages:
            raise ValueError("settings.apps must preserve the configured package order.")

        app_settings = self._validate_app_settings(raw_app_settings)
        self._validate_web_contract(
            settings,
            require_secrets=require_web_secrets,
        )
        if bind_app_settings:
            for label, instance in app_settings.items():
                self.registry.bind_settings(label, instance)
        self.settings = settings
        self.app_settings = app_settings
        self._last_diagnostics = self.inspect_diagnostics(data)
        return settings

    def _build_global_settings(self, data: Mapping[str, Any]) -> T_Settings:
        """Validate supplied YAML values through the YAML-only Settings source."""
        return cast(T_Settings, self.settings_class.model_validate(data))

    def _raw_app_metadata(
        self,
        data: Mapping[str, Any],
    ) -> tuple[tuple[str, ...], Mapping[str, Any]]:
        """Validate only the shapes needed before importing App metadata."""
        raw_packages = data.get("apps", [])
        if not isinstance(raw_packages, list):
            raise ValueError("settings.apps must be a YAML list of package paths.")
        packages: list[str] = []
        for index, package in enumerate(raw_packages):
            if not isinstance(package, str) or not package.strip():
                raise ValueError(f"settings.apps[{index}] must be a non-empty package path.")
            packages.append(package)

        raw_app_settings = data.get("app_settings", {})
        if not isinstance(raw_app_settings, Mapping):
            raise ValueError("settings.app_settings must be a YAML mapping.")
        return tuple(packages), raw_app_settings

    def _ensure_registry(self, packages: tuple[str, ...]) -> None:
        """Register one immutable App package list for this manager."""
        if self._registered_packages is None:
            self.registry.register_packages(packages)
            self._registered_packages = packages
            return
        if self._registered_packages != packages:
            raise RuntimeError("SettingsManager cannot switch its App package list; create a new process for a different service configuration.")

    def _validate_app_settings(
        self,
        raw_app_settings: Mapping[str, Any],
    ) -> dict[str, BaseModel]:
        """Validate only settings belonging to registered App labels."""
        registered_labels = set(self.registry.labels)
        for raw_label in raw_app_settings:
            label = str(raw_label)
            if label not in registered_labels:
                raise ValueError(f"app_settings.{label} is configured but App {label!r} is not installed.")

        validated: dict[str, BaseModel] = {}
        for config in self.registry:
            settings_model = config.settings_model
            if settings_model is None:
                if config.label in raw_app_settings:
                    raise ValueError(f"app_settings.{config.label} is configured, but App {config.label!r} does not define settings.")
                continue
            if not issubclass(settings_model, BaseModel):
                raise TypeError(f"App {config.label!r} settings_model must inherit pydantic.BaseModel.")

            raw_values = raw_app_settings.get(config.label, {})
            if not isinstance(raw_values, Mapping):
                raise ValueError(f"app_settings.{config.label} must be a mapping.")
            unknown = unknown_settings_keys(
                raw_values,
                settings_model,
                prefix=f"app_settings.{config.label}",
            )
            if unknown:
                raise ValueError("; ".join(unknown))
            try:
                instance = settings_model.model_validate(raw_values)
            except ValidationError as exc:
                raise ValueError(f"Invalid app_settings.{config.label}: {exc}") from exc
            validated[config.label] = instance
        return validated

    def _validate_web_contract(
        self,
        settings: T_Settings,
        *,
        require_secrets: bool,
    ) -> None:
        """Validate Web-only secret and Redis alias relationships without I/O."""
        if self.service_definition.application_base != "web":
            return

        if settings.web.session.enabled and settings.web.session.redis_alias not in settings.redis:
            raise ValueError(f"web.session.redis_alias {settings.web.session.redis_alias!r} is not defined in redis.")
        if settings.web.sse.enabled and settings.web.sse.redis_alias not in settings.redis:
            raise ValueError(f"web.sse.redis_alias {settings.web.sse.redis_alias!r} is not defined in redis.")
        if not require_secrets:
            return

        security = settings.web.security
        if security.secret_key is None:
            raise RuntimeError("settings.web.security.secret_key is empty; run the service settings sync command")
        # 只有真正开启指纹检查时才强制这把密钥：一个默认关闭的可选功能，不应该让每个
        # 部署都生成并保管一个用不到的秘密。
        if security.fingerprint.enabled and security.fingerprint.aes_secret_key is None:
            raise RuntimeError("settings.web.security.fingerprint.aes_secret_key is empty; run the service settings sync command")

    def _service_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Do not generate default Web settings for non-Web service types."""
        result = copy.deepcopy(dict(payload))
        if self.service_definition.application_base != "web":
            result.pop("web", None)
        return result

    def _materialize_web_security(
        self,
        data: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Fill persistent Web secrets only during an explicit write."""
        managed_data = cast(dict[str, Any], copy.deepcopy(data))
        if self.service_definition.application_base != "web":
            return managed_data

        # 公开 id 的字母表放在所有服务都有的 core 里，却只由 Web 服务生成：同一项目的其他服务复制同一个值，
        # 各自生成会让它们编出的 id 在 Web 里解错，最坏解成另一个合法 id。
        core = managed_data.setdefault("core", {})
        if isinstance(core, dict) and _is_blank_secret(core.get("id_alphabet")):
            core["id_alphabet"] = generate_alphabet()

        web = managed_data.setdefault("web", {})
        if not isinstance(web, dict):
            return managed_data
        security = web.setdefault("security", {})
        if not isinstance(security, dict):
            return managed_data
        if _is_blank_secret(security.get("secret_key")):
            security["secret_key"] = secrets.token_urlsafe(48)

        fingerprint = security.setdefault("fingerprint", {})
        if not isinstance(fingerprint, dict):
            return managed_data
        if _is_blank_secret(fingerprint.get("aes_secret_key")):
            fingerprint["aes_secret_key"] = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
        return managed_data

    def _apply_admin_messages_default(self, data: dict[str, Any]) -> None:
        """Enable cookie messages for Web Admin only when the user omitted it."""
        if self.service_definition.application_base != "web" or "admin" not in self.registry.labels:
            return
        web = data.setdefault("web", {})
        if not isinstance(web, dict):
            return
        messages = web.setdefault("messages", {})
        if not isinstance(messages, dict):
            return
        messages["enabled"] = True

    def _write_config_file(self, data: Mapping[str, Any]) -> None:
        """Render completely, then replace the settings file in one step (see atomic_write)."""
        documented_data = _commented_copy(data)
        sections: list[tuple[CommentedMap, type[BaseModel], int]] = [(documented_data, self.settings_class, 0)]
        raw_app_settings = documented_data.get("app_settings")
        if isinstance(raw_app_settings, Mapping):
            app_settings = documented_data["app_settings"] = _commented(raw_app_settings)
            for label, instance in self.app_settings.items():
                values = app_settings.get(label)
                if isinstance(values, Mapping):
                    # An App's fields sit two levels in: app_settings -> label -> field.
                    sections.append((_commented_value(app_settings, label), type(instance), 4))
        _describe_fields(documented_data, sections)

        rendered = io.StringIO()
        self._round_trip_yaml().dump(documented_data, rendered)
        # 整体替换而不是先清空再写：文件里有密钥，磁盘满或进程被杀时原文件必须完好。新建时仅属主可读写，
        # 已有文件沿用它的权限。
        # Through a link: services that share one settings file by linking to it stay together.
        atomic_write(self.config_file, rendered.getvalue(), follow_symlinks=True, new_file_mode=0o600)

    @staticmethod
    def _round_trip_yaml() -> YAML:
        """Return the project's round-trip formatting policy, a fresh object per dump (see new_yaml)."""
        return new_yaml()


def _is_blank_secret(value: object) -> bool:
    """Return whether an explicit write must generate one Web secret."""
    return value is None or (isinstance(value, str) and not value.strip())


def _nested_key_missing(data: Mapping[str, Any], *path: str) -> bool:
    """Return whether a nested mapping path is absent from raw settings."""
    current: object = data
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return True
        current = current[key]
    return False


def direct_model_class(annotation: Any) -> type[BaseModel] | None:
    """Return a directly nested Pydantic model class."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def _validation_alias_keys(alias: object) -> tuple[str, ...]:
    """Return top-level string keys accepted by one Pydantic validation alias."""
    if isinstance(alias, str):
        return (alias,)
    choices = getattr(alias, "choices", None)
    if choices is not None:
        keys: list[str] = []
        for choice in choices:
            keys.extend(_validation_alias_keys(choice))
        return tuple(keys)
    path = getattr(alias, "path", None)
    if path and isinstance(path[0], str):
        return (path[0],)
    return ()


def _field_for_input_key(
    model_class: type[BaseModel],
    key: str,
) -> tuple[str, FieldInfo] | None:
    """Resolve canonical fields and their normal Pydantic input aliases."""
    direct = model_class.model_fields.get(key)
    if direct is not None:
        return key, direct
    for field_name, field_info in model_class.model_fields.items():
        accepted = set(_validation_alias_keys(field_info.validation_alias))
        if isinstance(field_info.alias, str):
            accepted.add(field_info.alias)
        if key in accepted:
            return field_name, field_info
    return None


def _existing_field_key(
    data: Mapping[str, Any],
    model_class: type[BaseModel],
    field_name: str,
) -> str | None:
    """Find the user's canonical or aliased YAML key for one model field."""
    target = model_class.model_fields.get(field_name)
    if target is None:
        return field_name if field_name in data else None
    for raw_key in data:
        resolved = _field_for_input_key(model_class, str(raw_key))
        if resolved is not None and resolved[1] is target:
            return str(raw_key)
    return None


def sync_model_mapping(
    existing: Mapping[str, Any],
    defaults: Mapping[str, Any],
    model_class: type[BaseModel],
) -> dict[str, Any]:
    """Add missing schema fields without replacing operator values or aliases."""
    merged = cast(dict[str, Any], copy.deepcopy(existing))
    for field_name, default in defaults.items():
        existing_key = _existing_field_key(merged, model_class, field_name)
        if existing_key is None:
            merged[field_name] = copy.deepcopy(default)
            continue

        field_info = model_class.model_fields.get(field_name)
        nested_model = direct_model_class(field_info.annotation) if field_info is not None else None
        current = merged[existing_key]
        if nested_model is not None and isinstance(current, Mapping) and isinstance(default, Mapping):
            merged[existing_key] = sync_model_mapping(
                current,
                default,
                nested_model,
            )
    return merged


def deep_merge_missing(
    existing: dict[str, Any],
    defaults: dict[str, Any],
    *,
    model_class: type[BaseModel] | None = None,
) -> dict[str, Any]:
    """Add missing values with optional schema-aware recursion."""
    if model_class is not None:
        return sync_model_mapping(existing, defaults, model_class)
    merged = copy.deepcopy(existing)
    for key, value in defaults.items():
        merged.setdefault(key, copy.deepcopy(value))
    return merged


def unknown_settings_keys(
    data: Mapping[str, Any],
    model_class: type[BaseModel],
    prefix: str = "",
) -> list[str]:
    """Report unknown keys while respecting Pydantic field aliases."""
    diagnostics: list[str] = []
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        resolved = _field_for_input_key(model_class, str(key))
        if resolved is None:
            if model_class.model_config.get("extra") == "allow":
                continue
            diagnostics.append(f"unknown settings key '{path}'")
            continue

        nested_model = direct_model_class(resolved[1].annotation)
        if nested_model is not None and isinstance(value, Mapping):
            diagnostics.extend(unknown_settings_keys(value, nested_model, path))
    return diagnostics


def apply_schema_descriptions(
    data: Mapping[str, Any],
    model_class: type[BaseModel],
    *,
    indent: int = 0,
) -> CommentedMap:
    """Put each field's description one line above its key, exactly once, keeping every other comment."""
    documented = _commented_copy(data)
    _describe_fields(documented, [(documented, model_class, indent)])
    return documented


def _commented(mapping: Mapping[str, Any]) -> CommentedMap:
    return mapping if isinstance(mapping, CommentedMap) else CommentedMap(mapping)


def _commented_copy(data: Mapping[str, Any]) -> CommentedMap:
    return copy.deepcopy(data) if isinstance(data, CommentedMap) else CommentedMap(copy.deepcopy(dict(data)))


def _commented_value(mapping: CommentedMap, key: Any) -> CommentedMap:
    """The mapping under `key` as a CommentedMap, replacing a plain dict so it can carry comments."""
    value = mapping[key] = _commented(mapping[key])
    return value


def _description_placements(
    mapping: CommentedMap,
    model_class: type[BaseModel],
    indent: int,
) -> list[tuple[CommentedMap, Any, str, int]]:
    """Each described field of `model_class` present in `mapping`, nested models included."""
    placements: list[tuple[CommentedMap, Any, str, int]] = []
    for key, value in list(mapping.items()):
        resolved = _field_for_input_key(model_class, str(key))
        if resolved is None:
            continue
        field_info = resolved[1]
        nested_model = direct_model_class(field_info.annotation)
        if nested_model is not None and isinstance(value, Mapping):
            placements.extend(_description_placements(_commented_value(mapping, key), nested_model, indent + 2))
        if field_info.description:
            placements.append((mapping, key, field_info.description, indent))
    return placements


def _describe_fields(document: CommentedMap, sections: list[tuple[CommentedMap, type[BaseModel], int]]) -> None:
    """Describe every field of every section once, however often the file has been written before.

    ruamel does not keep a comment line on the key it stands above: reading the file back puts it
    at the end of whatever precedes the key (the previous value, the head of the mapping), so "does
    this key already have its description" cannot be answered by looking at the key — that is how
    each sync used to add every description again. Instead, every comment line that is exactly one
    of the descriptions is removed wherever it sits, and each description is then put back above
    its key. Other comments stay; copies left by earlier versions merge into one.
    """
    placements = [placement for mapping, model, indent in sections for placement in _description_placements(mapping, model, indent)]
    _drop_comment_lines(document, {f"# {text}" for _mapping, _key, text, _indent in placements})
    for mapping, key, text, indent in placements:
        mapping.yaml_set_comment_before_after_key(key, before=text, indent=indent)


def _drop_comment_lines(node: Any, lines: set[str]) -> None:
    """Remove every full comment line in `lines` from the comments of `node` and everything under it."""
    comments = getattr(node, "ca", None)
    if comments is not None:
        _drop_from_slots(comments.comment, lines)
        _drop_from_slots([comments.end], lines)
        for slots in comments.items.values():
            _drop_from_slots(slots, lines)
    if isinstance(node, Mapping):
        children: Iterable[Any] = node.values()
    elif isinstance(node, list):
        children = node
    else:
        children = ()
    for child in children:
        _drop_comment_lines(child, lines)


def _drop_from_slots(slots: list[Any] | None, lines: set[str]) -> None:
    """A slot is a list of whole comment lines, or one comment that begins on the line of a value."""
    for slot in slots or ():
        if isinstance(slot, list):
            kept = []
            for token in slot:
                token.value = "".join(line for line in token.value.splitlines(keepends=True) if line.strip() not in lines)
                if token.value:
                    kept.append(token)
            # In place: ruamel may hold the same list for a mapping and the key above it.
            slot[:] = kept
        elif isinstance(slot, CommentToken):
            # The first line ends the value's own line (a newline or an end-of-line comment): never removed.
            first, *rest = slot.value.splitlines(keepends=True) or [""]
            slot.value = first + "".join(line for line in rest if line.strip() not in lines)


__all__ = [
    "SettingsFileMissingError",
    "SettingsManager",
    "apply_schema_descriptions",
    "deep_merge_missing",
    "direct_model_class",
    "sync_model_mapping",
    "unknown_settings_keys",
]
