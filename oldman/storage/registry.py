"""Named storage registry and process-wide lazy storage proxies."""

from __future__ import annotations

import importlib
import threading
from collections.abc import Callable
from typing import Any, cast

from oldman.conf.schemas import DefaultSettings, StorageBackendConfig
from oldman.storage.backends.memory import InMemoryStorage
from oldman.storage.base import Storage, StorageContent
from oldman.storage.exceptions import (
    StorageAliasNotConfigured,
    StorageConfigurationError,
)
from oldman.storage.streams import FileInfo, StoredFile

SettingsFactory = Callable[[], DefaultSettings]
StorageResolver = Callable[[], Storage]


def _import_storage(path: str) -> type[Storage]:
    """Import and validate one configured Storage implementation."""
    segments = path.split(".")
    if len(segments) < 2 or not all(segment.isidentifier() for segment in segments):
        raise StorageConfigurationError(f"storage backend {path!r} must be a dotted import path")
    module_name, attribute = ".".join(segments[:-1]), segments[-1]
    try:
        value = getattr(importlib.import_module(module_name), attribute)
    except Exception as error:
        raise StorageConfigurationError(f"could not import storage backend {path!r}") from error
    if not isinstance(value, type) or not issubclass(value, Storage):
        raise StorageConfigurationError(f"storage backend {path!r} must be a Storage subclass")
    return cast(type[Storage], value)


class StorageRegistry:
    """Construct required named storages eagerly and custom storages on demand."""

    def __init__(self, settings_factory: SettingsFactory) -> None:
        self._settings_factory = settings_factory
        self._lock = threading.RLock()
        self._initialized = False
        self._definitions: dict[str, StorageBackendConfig] = {}
        self._instances: dict[str, Storage] = {}
        self._installed_apps: list[object] = []

    def init_app(self, app: object | None = None) -> None:
        """Initialize configured required storages once without backend I/O."""
        with self._lock:
            settings: DefaultSettings | None = None
            if not self._initialized:
                settings = self._initialize_core()
            if app is None or self._is_installed(app):
                return
            if settings is None:
                settings = self._resolve_settings()

            app_context = cast(Any, app).ctx
            try:
                previous_storages = app_context.storages
            except AttributeError:
                had_storages = False
                previous_storages = None
            else:
                had_storages = True

            try:
                app_context.storages = self
                web = getattr(settings, "web", None)
                media = getattr(web, "media", None)
                if media is not None:
                    if media.storage not in self._definitions and media.storage != "memory":
                        raise StorageConfigurationError(f"media storage alias {media.storage!r} is not configured")
                    from oldman.storage._web import install_media

                    install_media(
                        app,
                        storage=self.using(media.storage),
                        url=media.url,
                    )
            except BaseException:
                if had_storages:
                    app_context.storages = previous_storages
                else:
                    try:
                        del app_context.storages
                    except AttributeError:
                        pass
                raise
            self._installed_apps.append(app)

    def _resolve_settings(self) -> DefaultSettings:
        try:
            return self._settings_factory()
        except Exception as error:
            raise StorageConfigurationError("storage settings could not be resolved") from error

    def _initialize_core(self) -> DefaultSettings:
        settings = self._resolve_settings()
        definitions = {name: settings.storages[name] for name in settings.storages}
        self._definitions = definitions
        self._instances = {"memory": InMemoryStorage(alias="memory")}
        try:
            self._instances["default"] = self._construct("default")
        except BaseException:
            self._definitions = {}
            self._instances = {}
            raise

        self._initialized = True
        return settings

    def using(self, alias: str) -> Storage:
        """Return one cached storage by alias, constructing custom aliases lazily."""
        with self._lock:
            self._require_initialized()
            instance = self._instances.get(alias)
            if instance is not None:
                return instance
            if alias not in self._definitions:
                available = ", ".join(sorted({*self._definitions, "memory"}))
                raise StorageAliasNotConfigured(f"storage alias {alias!r} is not configured; available aliases: {available}")
            instance = self._construct(alias)
            self._instances[alias] = instance
            return instance

    def _construct(self, alias: str) -> Storage:
        definition = self._definitions[alias]
        backend = _import_storage(definition.backend)
        try:
            instance = backend(**definition.options)
            instance._bind_alias(alias)
        except Exception as error:
            raise StorageConfigurationError(f"could not construct storage alias {alias!r} with backend {definition.backend!r}") from error
        return instance

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise StorageConfigurationError("StorageRegistry.init_app() must be called before using storages")

    def _is_installed(self, app: object) -> bool:
        return any(installed is app for installed in self._installed_apps)


class StorageProxy:
    """Typed lazy proxy for one registry-selected Storage instance."""

    def __init__(self, resolver: StorageResolver) -> None:
        self._resolver = resolver

    async def save(
        self,
        name: str,
        content: StorageContent,
        *,
        overwrite: bool = False,
    ) -> str:
        return await self._resolver().save(name, content, overwrite=overwrite)

    async def open(self, name: str) -> StoredFile:
        return await self._resolver().open(name)

    async def delete(self, name: str) -> None:
        await self._resolver().delete(name)

    async def exists(self, name: str) -> bool:
        return await self._resolver().exists(name)

    async def stat(self, name: str) -> FileInfo:
        return await self._resolver().stat(name)

    async def get_available_name(self, name: str) -> str:
        return await self._resolver().get_available_name(name)


def _configured_settings() -> DefaultSettings:
    """Resolve process settings only when the global registry is initialized."""
    from oldman.conf import settings

    return settings


storages = StorageRegistry(_configured_settings)
default_storage = StorageProxy(lambda: storages.using("default"))
media_storage = StorageProxy(lambda: storages.using("default"))
memory_storage = StorageProxy(lambda: storages.using("memory"))


__all__ = (
    "StorageProxy",
    "StorageRegistry",
    "default_storage",
    "media_storage",
    "memory_storage",
    "storages",
)
