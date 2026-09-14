"""Named storage registry and lazy proxy contracts."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

from oldman.conf.schemas import DefaultSettings, StorageBackendConfig, StoragesConfig
from oldman.storage import (
    FileSystemStorage,
    InMemoryStorage,
    Storage,
    StorageAliasNotConfigured,
    StorageConfigurationError,
    StorageProxy,
    StorageRegistry,
    default_storage,
    media_storage,
    memory_storage,
    storages,
)


class CountingStorage(InMemoryStorage):
    """Importable test backend that exposes construction timing and options."""

    constructions = 0

    def __init__(self, *, marker: str) -> None:
        type(self).constructions += 1
        super().__init__()
        self.marker = marker


class RetryStorage(InMemoryStorage):
    """Importable backend that can fail after allocating an attempted instance."""

    failures_remaining = 0
    attempts: list[RetryStorage] = []

    def __init__(self, *, marker: str) -> None:
        super().__init__()
        self.marker = marker
        type(self).attempts.append(self)
        if type(self).failures_remaining:
            type(self).failures_remaining -= 1
            raise RuntimeError("retryable construction failure")


class ThreadedCountingStorage(InMemoryStorage):
    """Importable backend that widens constructor races without doing I/O."""

    constructions = 0
    _counter_lock = threading.Lock()

    def __init__(self, *, marker: str) -> None:
        with type(self)._counter_lock:
            type(self).constructions += 1
        time.sleep(0.03)
        super().__init__()
        self.marker = marker


class _SimpleSettings:
    """Minimal SERVICE_CONFIGS-like object without media or Web sections."""

    def __init__(self, storages: StoragesConfig) -> None:
        self.storages = storages


class _FailingAttachContext:
    """Fail the first assignment after partially storing its value."""

    def __init__(self) -> None:
        self._storages: object | None = None
        self._has_storages = False
        self._failures_remaining = 1

    @property
    def storages(self) -> object:
        if not self._has_storages:
            raise AttributeError("storages")
        return self._storages

    @storages.setter
    def storages(self, value: object) -> None:
        self._storages = value
        self._has_storages = True
        if self._failures_remaining:
            self._failures_remaining -= 1
            raise RuntimeError("attach failed")

    @storages.deleter
    def storages(self) -> None:
        self._storages = None
        self._has_storages = False


def _memory_settings(
    *,
    media_alias: str = "default",
    custom_backend: str = "tests.test_oldman_storage_registry.CountingStorage",
    custom_options: Mapping[str, object] | None = None,
) -> DefaultSettings:
    return DefaultSettings.model_validate(
        {
            "storages": {
                "default": {
                    "backend": "oldman.storage.backends.memory.InMemoryStorage",
                },
                "custom": {
                    "backend": custom_backend,
                    "options": dict(custom_options or {"marker": "configured"}),
                },
            },
            "web": {
                "media": {"storage": media_alias, "url": "/uploads/"},
            },
        }
    )


class StorageRegistryTest(unittest.TestCase):
    """Resolve required aliases eagerly and custom aliases lazily."""

    def setUp(self) -> None:
        CountingStorage.constructions = 0
        ThreadedCountingStorage.constructions = 0
        RetryStorage.failures_remaining = 0
        RetryStorage.attempts = []

    def test_importing_public_package_does_not_require_configured_settings(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import oldman.storage as storage; "
                    "import oldman.conf as conf; "
                    "assert storage.storages is not None; "
                    "assert 'settings' not in vars(conf)"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)

    def test_using_before_initialization_fails_clearly(self) -> None:
        registry = StorageRegistry(lambda: _memory_settings())

        with self.assertRaisesRegex(StorageConfigurationError, "init_app"):
            registry.using("default")

    def test_required_aliases_are_eager_and_custom_alias_is_cached_lazily(self) -> None:
        settings_calls = 0

        def settings_factory() -> DefaultSettings:
            nonlocal settings_calls
            settings_calls += 1
            return _memory_settings()

        registry = StorageRegistry(settings_factory)

        registry.init_app()
        registry.init_app()

        self.assertEqual(1, settings_calls)
        self.assertEqual(0, CountingStorage.constructions)
        self.assertIs(registry.using("default"), registry.using("default"))
        self.assertIsInstance(registry.using("memory"), InMemoryStorage)

        first = registry.using("custom")
        second = registry.using("custom")

        self.assertIs(first, second)
        self.assertEqual(1, CountingStorage.constructions)
        self.assertEqual("configured", cast(CountingStorage, first).marker)
        self.assertEqual("custom", first.alias)

    def test_concurrent_custom_alias_resolution_publishes_one_instance(self) -> None:
        registry = StorageRegistry(lambda: _memory_settings(custom_backend=("tests.test_oldman_storage_registry.ThreadedCountingStorage")))
        registry.init_app()
        workers = 8
        start = threading.Barrier(workers)

        def resolve() -> Storage:
            start.wait(timeout=5)
            return registry.using("custom")

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(resolve) for _index in range(workers)]
            instances = [future.result(timeout=5) for future in futures]

        self.assertEqual(1, ThreadedCountingStorage.constructions)
        self.assertTrue(all(instance is instances[0] for instance in instances))

    def test_concurrent_init_serializes_core_and_same_app_installation(self) -> None:
        settings = _memory_settings()
        settings.storages.default = StorageBackendConfig(
            backend="tests.test_oldman_storage_registry.ThreadedCountingStorage",
            options={"marker": "required"},
        )
        settings_calls = 0
        settings_lock = threading.Lock()
        install_calls = 0
        install_lock = threading.Lock()
        workers = 8
        start = threading.Barrier(workers)
        app = SimpleNamespace(ctx=SimpleNamespace())

        def settings_factory() -> DefaultSettings:
            nonlocal settings_calls
            with settings_lock:
                settings_calls += 1
            return settings

        def install_media(*args: object, **kwargs: object) -> None:
            nonlocal install_calls
            del args, kwargs
            with install_lock:
                install_calls += 1
            time.sleep(0.03)

        registry = StorageRegistry(settings_factory)

        def initialize() -> None:
            start.wait(timeout=5)
            registry.init_app(app)

        with (
            patch("oldman.storage._web.install_media", side_effect=install_media),
            ThreadPoolExecutor(max_workers=workers) as executor,
        ):
            futures = [executor.submit(initialize) for _index in range(workers)]
            for future in futures:
                future.result(timeout=5)

        self.assertEqual(1, settings_calls)
        self.assertEqual(1, ThreadedCountingStorage.constructions)
        self.assertEqual(1, install_calls)
        self.assertIs(registry, app.ctx.storages)

    def test_nondefault_web_media_backend_is_deferred_until_app_install(self) -> None:
        registry = StorageRegistry(lambda: _memory_settings(media_alias="custom"))

        registry.init_app()

        self.assertEqual(0, CountingStorage.constructions)

        app = SimpleNamespace(ctx=SimpleNamespace())
        with patch("oldman.storage._web.install_media") as install_media:
            registry.init_app(app)

        self.assertEqual(1, CountingStorage.constructions)
        install_media.assert_called_once_with(
            app,
            storage=registry.using("custom"),
            url="/uploads/",
        )

    def test_named_media_alias_is_not_shadowed_by_the_media_selection(self) -> None:
        settings = DefaultSettings.model_validate(
            {
                "storages": {
                    "default": {
                        "backend": "oldman.storage.backends.memory.InMemoryStorage",
                    },
                    "media": {
                        "backend": "tests.test_oldman_storage_registry.CountingStorage",
                        "options": {"marker": "named-media"},
                    },
                },
                "web": {"media": {"storage": "default"}},
            }
        )
        registry = StorageRegistry(lambda: settings)
        registry.init_app()

        named_media = registry.using("media")

        self.assertIsInstance(named_media, CountingStorage)
        self.assertEqual("named-media", cast(CountingStorage, named_media).marker)
        self.assertEqual("media", named_media.alias)
        self.assertIsNot(registry.using("default"), named_media)

    def test_unknown_alias_lists_every_available_alias(self) -> None:
        registry = StorageRegistry(lambda: _memory_settings())
        registry.init_app()

        with self.assertRaises(StorageAliasNotConfigured) as raised:
            registry.using("missing")

        message = str(raised.exception)
        self.assertIn("'missing'", message)
        self.assertIn("custom", message)
        self.assertIn("default", message)
        self.assertIn("memory", message)

    def test_missing_web_media_alias_fails_only_during_app_install(self) -> None:
        registry = StorageRegistry(lambda: _memory_settings(media_alias="missing"))
        registry.init_app()
        app = SimpleNamespace(ctx=SimpleNamespace())

        with self.assertRaisesRegex(
            StorageConfigurationError,
            "media storage alias 'missing' is not configured",
        ):
            registry.init_app(app)

        self.assertFalse(hasattr(app.ctx, "storages"))

    def test_required_backend_import_errors_are_configuration_errors(self) -> None:
        settings = _memory_settings()
        settings.storages.default.backend = "missing.storage.Backend"
        registry = StorageRegistry(lambda: settings)

        with self.assertRaises(StorageConfigurationError) as raised:
            registry.init_app()

        self.assertIsInstance(raised.exception.__cause__, ImportError)

    def test_non_storage_backend_is_a_configuration_error(self) -> None:
        settings = _memory_settings()
        settings.storages.default.backend = "pathlib.Path"
        registry = StorageRegistry(lambda: settings)

        with self.assertRaisesRegex(StorageConfigurationError, "Storage subclass"):
            registry.init_app()

    def test_backend_module_execution_errors_are_configuration_errors(self) -> None:
        registry = StorageRegistry(lambda: _memory_settings())

        with (
            patch(
                "oldman.storage.registry.importlib.import_module",
                side_effect=RuntimeError("module initialization failed"),
            ),
            self.assertRaises(StorageConfigurationError) as raised,
        ):
            registry.init_app()

        self.assertIsInstance(raised.exception.__cause__, RuntimeError)

    def test_runtime_import_rejects_invalid_dotted_path_segments(self) -> None:
        invalid_paths = (
            "package..Storage",
            "package. .Storage",
            "package.mod. Storage",
            "package.some module.Storage",
            "package.123module.Storage",
        )

        for backend in invalid_paths:
            with self.subTest(backend=backend):
                settings = _memory_settings()
                settings.storages.default.backend = backend
                registry = StorageRegistry(lambda settings=settings: settings)

                with self.assertRaisesRegex(
                    StorageConfigurationError,
                    "must be a dotted import path",
                ):
                    registry.init_app()

    def test_required_constructor_option_errors_are_configuration_errors(self) -> None:
        settings = _memory_settings()
        settings.storages.default.options["unexpected"] = True
        registry = StorageRegistry(lambda: settings)

        with self.assertRaises(StorageConfigurationError) as raised:
            registry.init_app()

        self.assertIsInstance(raised.exception.__cause__, TypeError)

    def test_eager_construction_failure_leaves_clean_state_for_retry(self) -> None:
        settings = _memory_settings()
        settings.storages.default = StorageBackendConfig(
            backend="tests.test_oldman_storage_registry.RetryStorage",
            options={"marker": "required"},
        )
        RetryStorage.failures_remaining = 1
        registry = StorageRegistry(lambda: settings)

        with self.assertRaises(StorageConfigurationError) as raised:
            registry.init_app()

        self.assertIsInstance(raised.exception.__cause__, RuntimeError)
        self.assertEqual({}, registry._definitions)
        self.assertEqual({}, registry._instances)
        self.assertFalse(registry._initialized)

        registry.init_app()
        initialized = registry.using("default")

        self.assertEqual(2, len(RetryStorage.attempts))
        self.assertIs(RetryStorage.attempts[1], initialized)
        self.assertIsNot(RetryStorage.attempts[0], initialized)
        self.assertEqual("default", initialized.alias)
        self.assertIsInstance(registry.using("memory"), InMemoryStorage)

    def test_custom_construction_failure_is_not_cached_and_using_can_retry(self) -> None:
        settings = _memory_settings(
            custom_backend="tests.test_oldman_storage_registry.RetryStorage",
            custom_options={"marker": "custom"},
        )
        registry = StorageRegistry(lambda: settings)
        registry.init_app()
        RetryStorage.failures_remaining = 1

        with self.assertRaises(StorageConfigurationError) as raised:
            registry.using("custom")

        self.assertIsInstance(raised.exception.__cause__, RuntimeError)
        self.assertNotIn("custom", registry._instances)

        initialized = registry.using("custom")

        self.assertEqual(2, len(RetryStorage.attempts))
        self.assertIs(RetryStorage.attempts[1], initialized)
        self.assertIsNot(RetryStorage.attempts[0], initialized)
        self.assertIs(initialized, registry.using("custom"))
        self.assertEqual(2, len(RetryStorage.attempts))

    def test_custom_backend_errors_are_deferred_until_first_use(self) -> None:
        cases = (
            ("missing.storage.Backend", {"marker": "configured"}),
            ("pathlib.Path", {"marker": "configured"}),
            ("tests.test_oldman_storage_registry.CountingStorage", {"wrong": True}),
        )
        for backend, options in cases:
            with self.subTest(backend=backend, options=options):
                registry = StorageRegistry(
                    lambda backend=backend, options=options: _memory_settings(
                        custom_backend=backend,
                        custom_options=options,
                    )
                )
                registry.init_app()

                with self.assertRaises(StorageConfigurationError):
                    registry.using("custom")

    def test_filesystem_construction_does_not_create_location(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            location = Path(tmp) / "not-created"
            settings = _memory_settings()
            settings.storages.default = StorageBackendConfig(
                backend="oldman.storage.backends.filesystem.FileSystemStorage",
                options={"location": location},
            )
            registry = StorageRegistry(lambda: settings)

            registry.init_app()

            self.assertIsInstance(registry.using("default"), FileSystemStorage)
            self.assertFalse(location.exists())
            self.assertFalse(hasattr(registry, "close"))

    def test_settings_without_web_use_default_media_proxy(self) -> None:
        simple = _SimpleSettings(
            StoragesConfig.model_validate(
                {
                    "default": {
                        "backend": "oldman.storage.backends.memory.InMemoryStorage",
                    }
                }
            )
        )
        registry = StorageRegistry(lambda: cast(DefaultSettings, simple))

        with patch.dict(sys.modules, {"oldman.web": None, "sanic": None}):
            registry.init_app()

        async def assert_media_fallback() -> None:
            with patch("oldman.storage.registry.storages", registry):
                name = await media_storage.save("simple.txt", b"simple")
                self.assertTrue(await default_storage.exists(name))

        asyncio.run(assert_media_fallback())

    def test_app_initialization_attaches_registry_and_installs_selected_media_once(self) -> None:
        registry = StorageRegistry(lambda: _memory_settings(media_alias="custom"))
        app = SimpleNamespace(ctx=SimpleNamespace())

        with patch("oldman.storage._web.install_media") as install_media:
            registry.init_app(app)
            registry.init_app(app)

        self.assertIs(registry, app.ctx.storages)
        install_media.assert_called_once_with(
            app,
            storage=registry.using("custom"),
            url="/uploads/",
        )

    def test_equal_apps_are_installed_separately_by_object_identity(self) -> None:
        class EqualApp:
            def __init__(self) -> None:
                self.ctx = SimpleNamespace()

            def __eq__(self, other: object) -> bool:
                return isinstance(other, EqualApp)

            def __hash__(self) -> int:
                return 1

        registry = StorageRegistry(lambda: _memory_settings())
        first = EqualApp()
        second = EqualApp()

        with patch("oldman.storage._web.install_media") as install_media:
            registry.init_app(first)
            registry.init_app(second)

        self.assertEqual(2, install_media.call_count)
        self.assertIs(registry, first.ctx.storages)
        self.assertIs(registry, second.ctx.storages)

    def test_failed_media_install_does_not_prevent_retry_on_the_same_app(self) -> None:
        registry = StorageRegistry(lambda: _memory_settings())
        app = SimpleNamespace(ctx=SimpleNamespace())
        install_media = Mock(side_effect=[RuntimeError("route conflict"), None])

        with patch("oldman.storage._web.install_media", install_media):
            with self.assertRaisesRegex(RuntimeError, "route conflict"):
                registry.init_app(app)
            self.assertFalse(hasattr(app.ctx, "storages"))
            registry.init_app(app)

        self.assertEqual(2, install_media.call_count)
        self.assertIs(registry, app.ctx.storages)

    def test_failed_media_install_restores_an_existing_ctx_registry(self) -> None:
        registry = StorageRegistry(lambda: _memory_settings())
        previous_registry = object()
        app = SimpleNamespace(
            ctx=SimpleNamespace(storages=previous_registry),
        )
        install_media = Mock(side_effect=[RuntimeError("route conflict"), None])

        with patch("oldman.storage._web.install_media", install_media):
            with self.assertRaisesRegex(RuntimeError, "route conflict"):
                registry.init_app(app)
            self.assertIs(previous_registry, app.ctx.storages)
            registry.init_app(app)

        self.assertEqual(2, install_media.call_count)
        self.assertIs(registry, app.ctx.storages)

    def test_failed_ctx_attach_rolls_back_partial_assignment_and_can_retry(self) -> None:
        registry = StorageRegistry(lambda: _memory_settings())
        context = _FailingAttachContext()
        app = SimpleNamespace(ctx=context)

        with patch("oldman.storage._web.install_media") as install_media:
            with self.assertRaisesRegex(RuntimeError, "attach failed"):
                registry.init_app(app)
            self.assertFalse(hasattr(context, "storages"))
            install_media.assert_not_called()

            registry.init_app(app)

        install_media.assert_called_once_with(
            app,
            storage=registry.using("default"),
            url="/uploads/",
        )
        self.assertIs(registry, context.storages)

    def test_core_only_initialization_does_not_install_or_remember_an_app(self) -> None:
        registry = StorageRegistry(lambda: _memory_settings())

        with patch("oldman.storage._web.install_media") as install_media:
            registry.init_app()
            app = SimpleNamespace(ctx=SimpleNamespace())
            registry.init_app(app)

        install_media.assert_called_once_with(
            app,
            storage=registry.using("default"),
            url="/uploads/",
        )


class StorageProxyTest(unittest.IsolatedAsyncioTestCase):
    """Forward every public async Storage operation through a typed resolver."""

    async def test_proxy_forwards_storage_operations_to_current_cached_backend(self) -> None:
        backend = InMemoryStorage(alias="proxied")
        resolutions = 0

        def resolve() -> Storage:
            nonlocal resolutions
            resolutions += 1
            return backend

        proxy = StorageProxy(resolve)

        name = await proxy.save("example.txt", b"payload")
        self.assertTrue(await proxy.exists(name))
        self.assertEqual(7, (await proxy.stat(name)).size)
        stored = await proxy.open(name)
        self.assertEqual(b"payload", await stored.read())
        await stored.close()
        self.assertNotEqual(name, await proxy.get_available_name(name))
        await proxy.delete(name)
        self.assertFalse(await proxy.exists(name))

        self.assertEqual(7, resolutions)
        self.assertFalse(hasattr(proxy, "close"))

    def test_public_singletons_have_stable_registry_and_proxy_types(self) -> None:
        self.assertIsInstance(storages, StorageRegistry)
        self.assertIsInstance(default_storage, StorageProxy)
        self.assertIsInstance(media_storage, StorageProxy)
        self.assertIsInstance(memory_storage, StorageProxy)
        self.assertIsNot(default_storage, media_storage)

    async def test_public_proxies_resolve_default_media_and_memory_aliases(self) -> None:
        default_media_registry = StorageRegistry(lambda: _memory_settings())
        default_media_registry.init_app()

        with patch("oldman.storage.registry.storages", default_media_registry):
            shared_name = await default_storage.save("shared.txt", b"shared")
            self.assertTrue(await media_storage.exists(shared_name))
            self.assertFalse(await memory_storage.exists(shared_name))

        selected_media_registry = StorageRegistry(lambda: _memory_settings(media_alias="custom"))
        selected_media_registry.init_app()

        with patch("oldman.storage.registry.storages", selected_media_registry):
            media_name = await media_storage.save("selected.txt", b"selected")
            self.assertTrue(await default_storage.exists(media_name))
            self.assertFalse(await selected_media_registry.using("custom").exists(media_name))
            self.assertFalse(await memory_storage.exists(media_name))


if __name__ == "__main__":
    unittest.main()
