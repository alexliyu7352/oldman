"""Direct Sanic integration and Web logging lifecycle contracts."""

# ruff: noqa: E402 -- project settings must exist before importing runtime consumers.

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar, cast
from unittest.mock import AsyncMock, Mock, patch

import oldman.conf as conf
from oldman.conf.schemas import DefaultSettings

# Web consumers intentionally require project settings before import. Preserve an
# existing project instance, but provide the same bootstrap order in isolated tests.
conf.__dict__.setdefault("settings", DefaultSettings())

from oldman.logging import LOGGING_CONFIG_DEFAULTS
from oldman.runtime import ServiceBootstrapContext
from oldman.runtime.web import (
    Sanic,
    WebApplication,
    _create_sanic_app_factory,
    prepare_process_context,
)
from oldman.web.errors import OldmanErrorHandler
from oldman.web.routing import WebApp
from oldman.web.session import Session, SessionData

ROOT = Path(__file__).resolve().parents[1]


class ConcreteWebApplication(WebApplication):
    """Minimal concrete service used to exercise the Sanic lifecycle."""

    def prepare_server(self, app: WebApp) -> None:
        """Prepare one in-memory server description without opening a socket."""
        app.prepare(host="127.0.0.1", port=0, workers=1, motd=False)


class RuntimeSessionData(SessionData, kw_only=True):
    """Concrete runtime model used to verify application-level selection."""

    account_name: str = ""


class SessionWebApplication(ConcreteWebApplication):
    """Web service selecting one application-owned typed Session model."""

    SESSION_MODEL: ClassVar[type[SessionData]] = RuntimeSessionData


class OldmanWebRuntimeBoundariesTest(unittest.TestCase):
    """Verify the main process, worker factory and formatter ownership boundaries."""

    def setUp(self) -> None:
        """Install isolated settings and a process-local logging runtime mock."""
        self.settings = DefaultSettings()
        self.settings_patch = patch.dict(conf.__dict__, {"settings": self.settings})
        self.settings_patch.start()
        self.app_registry = Mock(packages=())
        self.bootstrap_context = ServiceBootstrapContext(
            service_module="web",
            config_file=Path("data/web_settings.yaml"),
            settings=self.settings,
            apps=cast(Any, self.app_registry),
        )
        self.bootstrap_context_patch = patch(
            "oldman.runtime.base._get_bootstrap_context",
            return_value=self.bootstrap_context,
        )
        self.bootstrap_context_patch.start()
        self.logging_runtime = Mock(
            log_config={
                "version": 1,
                "handlers": {
                    "console": {"class": "logging.StreamHandler"},
                    "file": {
                        "class": "oldman.logging.handlers.AtomicAppendFileHandler",
                        "filename": "/tmp/web.log",
                    },
                },
            },
            closed=False,
            installed_from_context=False,
            process_id=os.getpid(),
        )
        self.logging_runtime.child_context = Mock()
        self.runtime_context_patch = patch("oldman.runtime.web.prepare_process_context")
        self.prepare_runtime_context = self.runtime_context_patch.start()
        self.initialize_patch = patch(
            "oldman.runtime.base.init_logging",
            return_value=self.logging_runtime,
        )
        self.initialize = self.initialize_patch.start()
        self.active_runtime_patch = patch("oldman.runtime.base.get_active_runtime", return_value=None)
        self.active_runtime_patch.start()
        self.sse_extension = Mock()
        self.sse_runtime_patch = patch("oldman.runtime.web.sse", self.sse_extension)
        self.sse_runtime_patch.start()
        self.storage_registry = Mock()
        self.storage_runtime_patch = patch(
            "oldman.runtime.web.storages",
            self.storage_registry,
        )
        self.storage_runtime_patch.start()

    def tearDown(self) -> None:
        """Restore logging construction and process-wide settings."""
        self.storage_runtime_patch.stop()
        self.sse_runtime_patch.stop()
        self.active_runtime_patch.stop()
        self.initialize_patch.stop()
        self.runtime_context_patch.stop()
        self.bootstrap_context_patch.stop()
        self.settings_patch.stop()

    def test_web_main_process_initializes_the_coordinator_owner(self) -> None:
        """The Sanic primary initializes logging after fixing the process context."""
        events: list[str] = []
        self.prepare_runtime_context.side_effect = lambda: events.append("runtime-context")
        self.initialize.side_effect = lambda *args, **kwargs: (events.append("logging"), self.logging_runtime)[1]
        application = ConcreteWebApplication("web-main-role")

        self.assertEqual(["runtime-context", "logging"], events)
        self.assertNotIn("mode", self.initialize.call_args.kwargs)
        self.assertNotIn("role", self.initialize.call_args.kwargs)
        self.assertIs(self.logging_runtime, application.logging_runtime)

    def test_sanic_constructor_does_not_reapply_dict_config(self) -> None:
        """Sanic must retain handlers already owned and tracked by LoggingRuntime."""
        application = ConcreteWebApplication("sanic-config-owner")
        sanic_app = Mock()
        sanic_app.ctx = SimpleNamespace()
        sanic_app.router.routes_all = {}

        with (
            patch("oldman.runtime.web.Sanic", return_value=sanic_app) as sanic_type,
        ):
            application.init()

        self.assertFalse(sanic_type.call_args.kwargs["configure_logging"])
        self.assertIsInstance(
            sanic_type.call_args.kwargs["error_handler"],
            OldmanErrorHandler,
        )
        self.assertNotIn("log_config", sanic_type.call_args.kwargs)

    def test_sanic_fallback_error_format_comes_from_web_settings(self) -> None:
        """Allow each Web service to select Sanic's fallback response negotiation."""
        self.settings.web.fallback_error_format = "html"
        application = ConcreteWebApplication("sanic-error-format")
        sanic_app = Mock()
        sanic_app.ctx = SimpleNamespace()
        sanic_app.router.routes_all = {}

        with patch("oldman.runtime.web.Sanic", return_value=sanic_app):
            application.init()

        initial_config = sanic_app.update_config.call_args_list[0].args[0]
        self.assertEqual("html", initial_config["FALLBACK_ERROR_FORMAT"])

    def test_session_runtime_is_disabled_by_default(self) -> None:
        """A Web service without Session enabled installs no Session middleware."""
        application = SessionWebApplication("session-disabled")
        sanic_app = Mock()
        sanic_app.ctx = SimpleNamespace()
        sanic_app.router.routes_all = {}

        with (
            patch("oldman.runtime.web.Sanic", return_value=sanic_app),
            patch("oldman.runtime.web.session.init_app") as install_session,
        ):
            application.init()

        install_session.assert_not_called()

    def test_messages_runtime_is_disabled_by_default(self) -> None:
        """A Web service without Messages enabled installs no flash middleware."""
        application = ConcreteWebApplication("messages-disabled")
        sanic_app = Mock()
        sanic_app.ctx = SimpleNamespace()
        sanic_app.router.routes_all = {}

        with (
            patch("oldman.runtime.web.Sanic", return_value=sanic_app),
            patch("oldman.runtime.web.messages.init_app") as install_messages,
        ):
            application.init()

        install_messages.assert_not_called()

    def test_messages_initialize_before_session_when_both_are_enabled(self) -> None:
        """Registration order lets flash observe Session's final response."""
        self.settings.web.messages.enabled = True
        self.settings.web.session.enabled = True
        application = ConcreteWebApplication("messages-session-order")
        sanic_app = Mock()
        sanic_app.ctx = SimpleNamespace()
        sanic_app.router.routes_all = {}
        events: list[str] = []

        with (
            patch("oldman.runtime.web.Sanic", return_value=sanic_app),
            patch(
                "oldman.runtime.web.messages.init_app",
                side_effect=lambda app: events.append("messages"),
            ) as install_messages,
            patch(
                "oldman.runtime.web.session.init_app",
                side_effect=lambda app, **kwargs: events.append("session"),
            ) as install_session,
        ):
            application.init()

        self.assertEqual(["messages", "session"], events)
        install_messages.assert_called_once_with(sanic_app)
        install_session.assert_called_once_with(
            sanic_app,
            session_model=application.SESSION_MODEL,
        )

    def test_session_runtime_delegates_enabled_installation_and_model_selection(self) -> None:
        """A real Sanic app delegates installation and retains the selected model."""
        self.settings.web.session.enabled = True
        self.settings.web.session.redis_alias = "RUNTIME_SESSION"
        self.settings.web.static.url = ""
        self.settings.web.media.url = ""
        application = SessionWebApplication("session-enabled")
        manager = Session()

        with (
            patch("oldman.runtime.web.session", manager),
            patch.object(application, "_setup_system_signals"),
        ):
            sanic_app = application.create_app()

        try:
            self.assertIs(manager, sanic_app.ctx.session)
            self.assertIsNotNone(manager.interface)
            assert manager.interface is not None
            self.assertEqual("RUNTIME_SESSION", manager.interface.redis_alias)
            self.assertIs(RuntimeSessionData, manager.interface.session_model)
            self.assertEqual(1, len(sanic_app.request_middleware))
            self.assertEqual(1, len(sanic_app.response_middleware))
        finally:
            Sanic.unregister_app(sanic_app)

    def test_sse_extension_binds_before_app_views_are_loaded(self) -> None:
        """View decorators must see the process-local extension after it is bound."""
        application = ConcreteWebApplication("sse-runtime-order")
        sanic_app = Mock(spec=Sanic)
        sanic_app.ctx = SimpleNamespace()
        sanic_app.router.routes_all = {}
        events: list[str] = []
        self.sse_extension.init_app.side_effect = lambda app: events.append("sse")

        self.app_registry.load_views.side_effect = lambda: events.append("apps")
        with patch("oldman.runtime.web.Sanic", return_value=sanic_app):
            application.init()

        self.assertEqual(["sse", "apps"], events)
        self.sse_extension.init_app.assert_called_once_with(sanic_app)

    def test_web_runtime_loads_models_then_extensions_then_views(self) -> None:
        """Views see complete models and every decorator-backed Web extension."""
        events: list[str] = []
        apps = Mock()
        apps.load_models.side_effect = lambda: events.append("models")
        apps.load_views.side_effect = lambda: events.append("views")
        context = ServiceBootstrapContext(
            service_module="web",
            config_file=Path("data/web_settings.yaml"),
            settings=self.settings,
            apps=apps,
        )
        sanic_app = Mock(spec=Sanic)
        sanic_app.ctx = SimpleNamespace()
        sanic_app.router.routes_all = {}
        self.storage_registry.init_app.side_effect = lambda app: events.append(
            "storage"
        )
        self.sse_extension.init_app.side_effect = lambda app: events.append("sse")

        with (
            patch(
                "oldman.runtime.base._get_bootstrap_context",
                return_value=context,
            ),
            patch("oldman.runtime.web.Sanic", return_value=sanic_app),
        ):
            application = ConcreteWebApplication("stage-order")
            application.init()

        self.assertEqual(["storage", "sse", "models", "views"], events)

    def test_i18n_roots_only_include_apps_installed_in_this_service(self) -> None:
        """The built-in Admin catalog is not a hidden unconditional source."""
        from oldman.runtime.web import _translation_catalog_roots

        apps = Mock(packages=("reports_app",))
        context = ServiceBootstrapContext(
            service_module="web",
            config_file=Path("data/web_settings.yaml"),
            settings=self.settings,
            apps=apps,
        )
        with (
            patch(
                "oldman.runtime.base._get_bootstrap_context",
                return_value=context,
            ),
            patch(
                "oldman.runtime.web._package_locale_root",
                return_value=Path("/packages/reports/locales"),
            ),
        ):
            application = ConcreteWebApplication("catalog-roots")
            roots = _translation_catalog_roots(application)

        self.assertEqual(
            (
                Path(conf.PROJECT_BASE_PATH) / "locales",
                Path("/packages/reports/locales"),
            ),
            roots,
        )

    def test_runtime_initializes_web_extensions_before_app_views(self) -> None:
        """Every decorator-backed runtime exists before registered apps import."""
        events: list[str] = []

        class MediaSettingsWithoutRoot:
            storage = "default"
            url = "/media/"

            @property
            def root(self) -> str:
                raise AssertionError("Web runtime must not read media.root")

        self.settings.web.messages.enabled = True
        self.settings.web.session.enabled = True
        self.settings.web.static.url = ""
        self.settings.web.media = cast(Any, MediaSettingsWithoutRoot())
        application = ConcreteWebApplication("runtime-extension-order")
        sanic_app = Mock(spec=Sanic)
        sanic_app.ctx = SimpleNamespace()
        sanic_app.router.routes_all = {}
        messages_runtime = Mock()
        messages_runtime.init_app.side_effect = lambda app: events.append("messages")
        session_runtime = Mock()
        session_runtime.init_app.side_effect = lambda *args, **kwargs: events.append("session")
        self.storage_registry.init_app.side_effect = lambda app: events.append("storage")
        self.sse_extension.init_app.side_effect = lambda app: events.append("sse")

        with (
            patch("oldman.runtime.web.Sanic", return_value=sanic_app),
            patch("oldman.runtime.web.messages", messages_runtime),
            patch("oldman.runtime.web.session", session_runtime),
        ):
            self.app_registry.load_views.side_effect = lambda: events.append("apps")
            application.init()

        self.assertEqual(["messages", "session", "storage", "sse", "apps"], events)
        self.storage_registry.init_app.assert_called_once_with(sanic_app)
        sanic_app.static.assert_not_called()

    def test_sse_stop_listener_is_registered_before_runtime_resource_cleanup(self) -> None:
        """SSE can close Pub/Sub and streams before the runtime closes Redis pools."""
        application = ConcreteWebApplication("sse-stop-order")
        sanic_app = Mock(spec=Sanic)
        sanic_app.ctx = SimpleNamespace()
        sanic_app.router.routes_all = {}
        sse_stop = AsyncMock()
        self.sse_extension.init_app.side_effect = lambda app: app.register_listener(
            sse_stop,
            "before_server_stop",
        )

        with (
            patch("oldman.runtime.web.Sanic", return_value=sanic_app),
        ):
            application.init()

        stop_handlers = [call.args[0] for call in sanic_app.register_listener.call_args_list if call.args[1] == "before_server_stop"]
        self.assertEqual([sse_stop, application.before_server_stop], stop_handlers)

    def test_sanic_process_context_is_coordinated_before_logging_starts(self) -> None:
        """Match an existing spawn context and reject an incompatible global method early."""
        with (
            patch("oldman.runtime.web.Sanic.START_METHOD_SET", False),
            patch("oldman.runtime.web.multiprocessing.get_start_method", return_value=None),
            patch("oldman.runtime.web.Sanic._set_startup_method") as initialize,
        ):
            prepare_process_context()
            initialize.assert_called_once_with()

        with (
            patch("oldman.runtime.web.Sanic.START_METHOD_SET", False),
            patch("oldman.runtime.web.Sanic._get_startup_method", return_value="spawn"),
            patch("oldman.runtime.web.multiprocessing.get_start_method", return_value="spawn"),
            patch("oldman.runtime.web.Sanic._set_startup_method") as initialize,
        ):
            prepare_process_context()
            self.assertTrue(Sanic.START_METHOD_SET)
            initialize.assert_not_called()

        with (
            patch("oldman.runtime.web.Sanic.START_METHOD_SET", False),
            patch("oldman.runtime.web.Sanic._get_startup_method", return_value="spawn"),
            patch("oldman.runtime.web.multiprocessing.get_start_method", return_value="fork"),
        ):
            with self.assertRaisesRegex(RuntimeError, "requires multiprocessing start method 'spawn'.*'fork'"):
                prepare_process_context()

    def test_sanic_ext_cannot_install_a_competing_logging_runtime(self) -> None:
        """Reject Sanic-Ext logging instead of adding competing handlers."""
        application = ConcreteWebApplication("sanic-ext-logging")
        extensions = application.get_extension() or []
        self.assertNotIn(
            "LoggingExtension",
            {extension.__name__ for extension in extensions},
        )
        application.get_ext_config = Mock(return_value={"logging": True})  # type: ignore[method-assign]
        sanic_app = Mock()
        sanic_app.ctx = SimpleNamespace()
        sanic_app.router.routes_all = {}

        with (
            patch("oldman.runtime.web.Sanic", return_value=sanic_app),
            self.assertRaisesRegex(ValueError, "Sanic-Ext logging"),
        ):
            application.init()

    def test_runtime_config_cannot_reenable_sanic_message_colors(self) -> None:
        """Force Sanic's producer messages plain after applying project overrides."""
        application = ConcreteWebApplication("sanic-no-color")
        application.get_runtime_config = Mock(return_value={"NO_COLOR": False})  # type: ignore[method-assign]
        sanic_app = Mock()
        sanic_app.ctx = SimpleNamespace()
        sanic_app.router.routes_all = {}

        with (
            patch("oldman.runtime.web.Sanic", return_value=sanic_app),
        ):
            application.init()

        self.assertEqual({"NO_COLOR": True}, sanic_app.update_config.call_args_list[-1].args[0])

    def test_oldman_formatters_are_not_replaced_by_sanic_auto_formatters(self) -> None:
        """Neither defaults nor WebApplication may introduce Sanic formatters."""
        source = (ROOT / "oldman" / "runtime" / "web.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("sanic.logging.formatter", repr(LOGGING_CONFIG_DEFAULTS))
        self.assertNotIn("AutoAccessFormatter", source)
        self.assertNotIn("def sanic_logging_config", source)

    def test_primary_app_is_created_without_loading_the_worker_factory(self) -> None:
        """Only spawned server workers may execute the context-installing factory."""
        application = ConcreteWebApplication("primary")
        primary = Mock(serve_location="http://127.0.0.1:9000")
        primary.state.workers = 1
        application.create_app = Mock(return_value=primary)  # type: ignore[method-assign]
        application.prepare_server = Mock()  # type: ignore[method-assign]
        application._close_logging = Mock()  # type: ignore[method-assign]
        loader = Mock()

        with (
            patch("oldman.runtime.web.AppLoader", return_value=loader) as loader_type,
            patch("oldman.runtime.web.Sanic.serve") as serve,
        ):
            application.run()

        application.create_app.assert_called_once_with()
        loader.load.assert_not_called()
        loader_type.assert_called_once()
        serve.assert_called_once_with(primary=primary, app_loader=loader)
        application._close_logging.assert_called_once_with()

    def test_spawn_worker_bootstraps_before_importing_service_module(self) -> None:
        """A spawned worker rebuilds settings and Apps before importing service code."""
        files = {
            "pyproject.toml": "[project]\nname = 'spawn-worker-fixture'\nversion = '0'\n",
            "config/__init__.py": "",
            "config/schemas.py": """
                from oldman.conf import DefaultSettings

                class Settings(DefaultSettings):
                    marker: str
            """,
            "config/settings.py": """
                from typing import cast

                import oldman.conf as conf
                from config.schemas import Settings

                settings = cast(Settings, conf.settings)
            """,
            "data/web_settings.yaml": """
                apps: []
                app_settings: {}
                marker: worker-ready
                web:
                  security:
                    secret_key: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
                    fingerprint:
                      aes_secret_key: AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
            """,
            "services/__init__.py": "",
            "services/web.py": """
                import os
                from pathlib import Path

                from config.settings import settings
                from oldman.runtime import ServiceBootstrapContext, WebApplication

                assert settings.marker == "worker-ready"

                class SpawnWebApplication(WebApplication):
                    def __init__(
                        self,
                        app_name: str,
                        *,
                        config: ServiceBootstrapContext,
                    ) -> None:
                        assert config.settings is settings
                        self.app_name = app_name

                    def create_app(self):
                        Path(os.environ["OLDMAN_SPAWN_MARKER"]).write_text(
                            self.app_name,
                            encoding="utf-8",
                        )
                        return object()

                    def prepare_server(self, app) -> None:
                        pass
            """,
            "run.py": """
                import multiprocessing
                from pathlib import Path

                from oldman.runtime.web import _create_sanic_app_factory

                class AttachedRuntime:
                    def close(self) -> None:
                        pass

                class ChildContext:
                    def install(self) -> AttachedRuntime:
                        return AttachedRuntime()

                if __name__ == "__main__":
                    process = multiprocessing.get_context("spawn").Process(
                        target=_create_sanic_app_factory,
                        args=(
                            "web",
                            Path.cwd() / "data/web_settings.yaml",
                            "spawn-worker",
                            ChildContext(),
                        ),
                    )
                    process.start()
                    process.join(10)
                    if process.is_alive():
                        process.terminate()
                        process.join(5)
                        raise RuntimeError("spawn worker did not finish")
                    raise SystemExit(process.exitcode)
            """,
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for relative_path, source in files.items():
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(textwrap.dedent(source), encoding="utf-8")
            marker = root / "worker-marker.txt"
            environment = os.environ.copy()
            environment["OLDMAN_SPAWN_MARKER"] = str(marker)
            environment["PYTHONPATH"] = os.pathsep.join(
                filter(
                    None,
                    (str(ROOT), environment.get("PYTHONPATH")),
                )
            )
            completed = subprocess.run(
                [sys.executable, "run.py"],
                cwd=root,
                env=environment,
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )

            self.assertEqual(
                0,
                completed.returncode,
                completed.stdout + completed.stderr,
            )
            self.assertEqual("spawn-worker", marker.read_text(encoding="utf-8"))

    def test_worker_factory_installs_context_before_application_construction(self) -> None:
        """Every Sanic child installs its writer context before app construction."""
        events: list[str] = []
        context = Mock()
        attached = Mock()
        context.install.side_effect = lambda: (events.append("install"), attached)[1]
        native_app = Mock()

        class WorkerApplication:
            def __init__(
                self,
                app_name: str,
                *,
                config: ServiceBootstrapContext,
            ) -> None:
                events.append(f"construct:{app_name}")
                assert config is self_bootstrap_context

            def create_app(self) -> Any:
                events.append("create")
                return native_app

        self_bootstrap_context = self.bootstrap_context
        definition = Mock()
        with (
            patch(
                "oldman.runtime.web.bootstrap_service",
                side_effect=lambda *args, **kwargs: (
                    events.append("bootstrap"),
                    self_bootstrap_context,
                )[1],
            ),
            patch(
                "oldman.runtime.web.get_service_definition",
                return_value=definition,
            ),
            patch(
                "oldman.runtime.web.load_service_class",
                side_effect=lambda value: (
                    events.append("load-service"),
                    WorkerApplication,
                )[1],
            ),
            patch("oldman.runtime.web._find_project_root", return_value=ROOT),
            patch("oldman.runtime.web.Finalize") as finalize,
        ):
            result = _create_sanic_app_factory(
                "web",
                Path("data/web_settings.yaml"),
                "worker",
                context,
            )

        self.assertIs(native_app, result)
        self.assertEqual(
            [
                "install",
                "bootstrap",
                "load-service",
                "construct:worker",
                "create",
            ],
            events,
        )
        attached.close.assert_not_called()
        finalize.assert_called_once_with(None, attached.close, exitpriority=100)

    def test_reloader_factory_uses_the_same_writer_only_context(self) -> None:
        """Reloader and server children share the same topology-free factory path."""
        child_context = Mock()
        attached = child_context.install.return_value

        class ReloaderApplication:
            def __init__(
                self,
                app_name: str,
                *,
                config: ServiceBootstrapContext,
            ) -> None:
                del app_name
                assert config is self_bootstrap_context

            def create_app(self) -> Any:
                return Mock()

        self_bootstrap_context = self.bootstrap_context
        with (
            patch(
                "oldman.runtime.web.bootstrap_service",
                return_value=self_bootstrap_context,
            ),
            patch("oldman.runtime.web.get_service_definition", return_value=Mock()),
            patch(
                "oldman.runtime.web.load_service_class",
                return_value=ReloaderApplication,
            ),
            patch("oldman.runtime.web._find_project_root", return_value=ROOT),
            patch("oldman.runtime.web.Finalize") as finalize,
        ):
            _create_sanic_app_factory(
                "web",
                Path("data/web_settings.yaml"),
                "reloader",
                child_context,
            )

        child_context.install.assert_called_once_with()
        finalize.assert_called_once_with(None, attached.close, exitpriority=100)

    def test_worker_factory_closes_context_when_construction_fails(self) -> None:
        """A worker that cannot construct its application must release attached resources."""
        context = Mock()
        attached = context.install.return_value

        class BrokenApplication:
            def __init__(
                self,
                app_name: str,
                *,
                config: ServiceBootstrapContext,
            ) -> None:
                del app_name, config
                raise RuntimeError("worker-construction-failed")

        with (
            patch(
                "oldman.runtime.web.bootstrap_service",
                return_value=self.bootstrap_context,
            ),
            patch("oldman.runtime.web.get_service_definition", return_value=Mock()),
            patch(
                "oldman.runtime.web.load_service_class",
                return_value=BrokenApplication,
            ),
            patch("oldman.runtime.web._find_project_root", return_value=ROOT),
            self.assertRaisesRegex(RuntimeError, "worker-construction-failed"),
        ):
            _create_sanic_app_factory(
                "web",
                Path("data/web_settings.yaml"),
                "broken",
                context,
            )

        attached.close.assert_called_once_with()

    def test_worker_hook_keeps_logging_open_after_resource_cleanup(self) -> None:
        """Sanic still emits Worker complete after this hook, so finalization owns close."""
        events: list[str] = []
        application = ConcreteWebApplication("worker-close")
        self.logging_runtime.close.side_effect = lambda: events.append("close")

        with (
            patch("oldman.runtime.web.memory_cache.close", new=AsyncMock(side_effect=lambda: events.append("memory"))),
            patch("oldman.runtime.web.redis_client.close", new=AsyncMock(side_effect=lambda: events.append("redis"))),
            patch("oldman.runtime.web.db_manager.close", new=AsyncMock(side_effect=lambda: events.append("database"))),
            patch("oldman.runtime.web.logger.info", side_effect=lambda *args, **kwargs: events.append("log")),
        ):
            asyncio.run(
                application.after_server_stop(cast(Any, SimpleNamespace()))
            )

        self.assertEqual(["memory", "redis", "database", "log"], events)
        self.logging_runtime.close.assert_not_called()

    def test_worker_cleanup_closes_every_resource_even_when_one_fails(self) -> None:
        """一个资源关闭失败不能让后面的资源留着连接。"""
        events: list[str] = []
        application = ConcreteWebApplication("worker-close-failure")

        with (
            patch("oldman.runtime.web.memory_cache.close", new=AsyncMock(side_effect=RuntimeError("cache is stuck"))),
            patch("oldman.runtime.web.redis_client.close", new=AsyncMock(side_effect=lambda: events.append("redis"))),
            patch("oldman.runtime.web.db_manager.close", new=AsyncMock(side_effect=lambda: events.append("database"))),
            self.assertRaisesRegex(RuntimeError, "cache is stuck"),
        ):
            asyncio.run(application.after_server_stop(cast(Any, SimpleNamespace())))

        self.assertEqual(["redis", "database"], events)

    def test_publishers_close_before_the_resources_their_hooks_use(self) -> None:
        """taskiq 的 shutdown 钩子可能还要写库：引擎必须在它们之后才关，否则会惰性新建一个没人关的。"""
        events: list[str] = []
        application = ConcreteWebApplication("shutdown-order")

        async def close_publishers(self: object, original_error: object = None) -> None:
            del self, original_error
            events.append("publishers")

        async def after_server_stop(self: object, app: object) -> None:
            del self, app
            events.append("resources")

        with (
            patch.object(ConcreteWebApplication, "_close_publishers", close_publishers),
            patch.object(ConcreteWebApplication, "after_server_stop", after_server_stop),
        ):
            asyncio.run(application._services_after_server_stop(cast(Any, SimpleNamespace())))

        self.assertEqual(["publishers", "resources"], events)

    def test_prepare_server_derives_the_listener_from_the_web_settings(self) -> None:
        """默认监听参数来自配置，单进程只在没有多 worker、没有 auto_reload 时成立。"""
        application = WebApplication("listener")
        self.settings.web.listen_host = "127.0.0.1"
        self.settings.web.listen_port = 17997
        self.settings.web.access_log = True
        # 三个值显式写出来：靠 runtime_settings() 的默认值碰巧成立的话，默认值一改这条就空转了。
        self.settings.web.workers = 1
        self.settings.web.auto_reload = False
        self.settings.web.debug = False

        single = Mock()
        application.prepare_server(cast(Any, single))
        single.prepare.assert_called_once_with(
            host="127.0.0.1",
            port=17997,
            debug=False,
            motd=False,
            auto_reload=False,
            workers=1,
            access_log=True,
            single_process=True,
        )

        # Sanic 拒绝 single_process 和多 worker / auto_reload 同时出现。
        self.settings.web.workers = 4
        multi_worker = Mock()
        application.prepare_server(cast(Any, multi_worker))
        self.assertEqual({"workers": 4, "single_process": False}, {key: multi_worker.prepare.call_args.kwargs[key] for key in ("workers", "single_process")})

        self.settings.web.workers = 1
        self.settings.web.auto_reload = True
        reloading = Mock()
        application.prepare_server(cast(Any, reloading))
        self.assertEqual({"auto_reload": True, "single_process": False}, {key: reloading.prepare.call_args.kwargs[key] for key in ("auto_reload", "single_process")})

    def test_i18n_commands_are_not_owned_by_web_application(self) -> None:
        """Catalog commands belong to the CLI feature instead of Web services."""
        self.settings.i18n.use_i18n = True

        commands = WebApplication.get_default_commands()

        self.assertTrue({"start", "stop", "restart"} <= commands.keys())
        self.assertTrue(
            {
                "trans_init",
                "trans_extract",
                "trans_update",
                "trans_compile",
            }.isdisjoint(commands)
        )

    def test_web_application_uses_sanic_directly_without_an_adapter_package(self) -> None:
        """Internal code uses Sanic directly while the public class keeps its name."""
        application_source = (ROOT / "oldman" / "runtime" / "web.py").read_text(encoding="utf-8")
        adapter_root = ROOT / "oldman" / "web" / "runtime"

        self.assertIn("from sanic import Sanic", application_source)
        self.assertNotIn("RuntimeAdapter", application_source)
        self.assertFalse((adapter_root / "base.py").exists())
        self.assertFalse((adapter_root / "sanic_adapter.py").exists())
        self.assertFalse((adapter_root / "__init__.py").exists())


if __name__ == "__main__":
    unittest.main()
