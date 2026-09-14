"""Application command lifecycle regressions migrated from the foundation source."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

import oldman.conf as conf
from oldman.apps import AppRegistry
from oldman.cli import Command
from oldman.conf.schemas import DefaultSettings
from oldman.runtime import ServiceBootstrapContext
from oldman.runtime.base import BaseApplication
from oldman.runtime.simple import SimpleApplication


class DemoApplication(BaseApplication):
    """Minimal concrete application shared by constructor-only contracts."""

    def init(self) -> None:
        """Satisfy the service initialization contract without external resources."""

    def run(self, *args, **kwargs) -> None:
        """Satisfy the service execution contract without starting a loop."""


class OldmanApplicationLifecycleTest(unittest.TestCase):
    """Verify sync/async command dispatch, cleanup and PID isolation."""

    def setUp(self) -> None:
        """Provide configured settings and an isolated logging runtime for each contract."""
        self.settings = DefaultSettings()
        # ``settings`` is only annotated until project bootstrap completes, while
        # the module's ``__getattr__`` intentionally raises for premature access.
        self.settings_patch = patch.dict(conf.__dict__, {"settings": self.settings})
        self.settings_patch.start()
        self.apps = Mock()
        self.bootstrap_context = ServiceBootstrapContext(
            service_module="test_service",
            config_file=Path("data/test_service_settings.yaml"),
            settings=self.settings,
            apps=cast(Any, self.apps),
        )
        self.bootstrap_context_patch = patch(
            "oldman.runtime.base._get_bootstrap_context",
            return_value=self.bootstrap_context,
        )
        self.bootstrap_context_patch.start()
        self.logging_runtime = Mock(log_config={})
        self.logging_runtime.closed = False
        self.logging_runtime.installed_from_context = False
        self.initialize_patch = patch(
            "oldman.runtime.base.init_logging",
            return_value=self.logging_runtime,
        )
        self.initialize = self.initialize_patch.start()
        self.active_runtime_patch = patch("oldman.runtime.base.get_active_runtime", return_value=None)
        self.active_runtime_patch.start()

    def tearDown(self) -> None:
        """Restore process-wide settings and logging construction hooks."""
        self.bootstrap_context_patch.stop()
        self.active_runtime_patch.stop()
        self.initialize_patch.stop()
        self.settings_patch.stop()

    def test_application_holds_the_single_logging_runtime(self) -> None:
        """Application construction uses the final topology-free logging API."""
        application = DemoApplication("single-runtime")
        self.assertIs(self.logging_runtime, application.logging_runtime)
        self.assertIs(self.logging_runtime.log_config, application.log_config)
        self.assertEqual(
            {
                "logger_path": self.settings.logging.dir,
                "logger_level": self.settings.logging.level,
            },
            self.initialize.call_args.kwargs,
        )

    def test_application_identity_comes_from_the_bootstrapped_service_module(self) -> None:
        """PID and logging identity cannot drift from the selected service file."""
        context = ServiceBootstrapContext(
            service_module="music_web",
            config_file=Path("data/music_web_settings.yaml"),
            settings=self.settings,
            apps=AppRegistry(),
        )
        with patch(
            "oldman.runtime.base._get_bootstrap_context",
            return_value=context,
        ):
            application = DemoApplication()
            service_id = DemoApplication.get_service_id()

        self.assertIs(application.bootstrap_context, context)
        self.assertEqual("music_web", service_id)
        self.assertEqual("music_web", application.log_file_name)
        self.assertTrue(application.pid_file_path.endswith("music_web.pid"))

    def test_simple_init_confirms_models_without_loading_web_views(self) -> None:
        """A SimpleApplication completes the model stage and never enters views."""

        class DemoSimpleApplication(SimpleApplication):
            def prepare(self) -> None:
                pass

            async def main(self, *args, **kwargs) -> None:
                pass

        apps = Mock()
        context = ServiceBootstrapContext(
            service_module="worker",
            config_file=Path("data/worker_settings.yaml"),
            settings=self.settings,
            apps=apps,
        )
        with (
            patch(
                "oldman.runtime.base._get_bootstrap_context",
                return_value=context,
            ),
            patch("oldman.runtime.simple.storages"),
            patch.object(DemoSimpleApplication, "_setup_system_signals"),
        ):
            application = DemoSimpleApplication()
            application.init()

        apps.load_models.assert_called_once_with()
        apps.load_views.assert_not_called()

    def test_context_installed_runtime_is_reused_without_reopening_sinks(self) -> None:
        """A worker context installed before application construction is the local owner."""
        attached = Mock(
            log_config={"handlers": {"file": {}}},
            closed=False,
            installed_from_context=True,
            process_id=os.getpid(),
        )

        with patch("oldman.runtime.base.get_active_runtime", return_value=attached):
            application = DemoApplication("attached")

        self.assertIs(attached, application.logging_runtime)
        self.initialize.assert_not_called()

        application.configure_command_logging("attached-command")
        self.assertNotIn("mode", self.initialize.call_args.kwargs)
        self.assertNotIn("role", self.initialize.call_args.kwargs)

    def test_simple_cleanup_closes_logging_once(self) -> None:
        """Repeated cleanup calls must close the application logging owner exactly once."""

        class DemoSimpleApplication(SimpleApplication):
            def prepare(self) -> None:
                pass

            async def main(self, *args, **kwargs) -> None:
                pass

        application = DemoSimpleApplication("simple-cleanup")
        application._cleanup()
        application._cleanup()

        self.logging_runtime.close.assert_called_once_with()

    def test_simple_shutdown_defers_close_until_run_cleanup(self) -> None:
        """A running loop must unwind and clean pending work before logging closes."""

        class DemoSimpleApplication(SimpleApplication):
            def prepare(self) -> None:
                pass

            async def main(self, *args, **kwargs) -> None:
                pass

        application = DemoSimpleApplication("simple-shutdown")
        application.loop = loop = Mock()
        loop.is_running.return_value = True
        application._main_task = main_task = Mock()
        main_task.cancelling.return_value = 0

        application.shutdown()

        main_task.cancel.assert_called_once_with()
        loop.stop.assert_not_called()
        self.assertTrue(application._should_exit)
        self.logging_runtime.close.assert_not_called()

        # ``run()`` closes logging after the cancelled root finishes async cleanup.
        application.loop = None
        application._cleanup()
        self.logging_runtime.close.assert_called_once_with()

    def test_registered_pid_cleanup_runs_once_before_logging_closes(self) -> None:
        """Explicit shutdown must not leave an atexit callback logging after close."""
        callbacks: list[Callable[[], None]] = []
        events: list[str] = []

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(self.settings.process, "pid_dir", Path(tmp)),
            patch("oldman.runtime.base.os.getppid", return_value=1),
            patch("oldman.runtime.base.atexit.register", side_effect=callbacks.append),
            patch("oldman.runtime.base.atexit.unregister") as unregister,
        ):
            application = DemoApplication("pid-cleanup")
            Path(application.pid_file_path).write_text(str(os.getpid()), encoding="utf-8")
            self.logging_runtime.close.side_effect = lambda: events.append("close")
            with patch("oldman.runtime.base.logger.info", side_effect=lambda *args, **kwargs: events.append("log")):
                application._close_logging()
                application._close_logging()

            self.assertEqual(["log", "close"], events)
            self.assertFalse(Path(application.pid_file_path).exists())
            unregister.assert_called_once_with(callbacks[0])
            self.logging_runtime.close.assert_called_once_with()

    def test_async_command_failure_logs_cleanup_before_closing_runtime(self) -> None:
        """The async command path closes logging after its final cleanup log on failure."""
        events: list[str] = []

        class DemoSimpleApplication(SimpleApplication):
            def prepare(self) -> None:
                pass

            async def main(self, *args, **kwargs) -> None:
                pass

        async def fail() -> None:
            events.append("command")
            raise RuntimeError("boom")

        application = DemoSimpleApplication("async-failure")
        self.logging_runtime.close.side_effect = lambda: events.append("close")
        with (
            patch("oldman.runtime.simple.memory_cache.close", new=AsyncMock()),
            patch("oldman.runtime.simple.redis_client.close", new=AsyncMock()),
            patch("oldman.runtime.simple.logger.info", side_effect=lambda *args, **kwargs: events.append("log")),
            self.assertRaisesRegex(RuntimeError, "boom"),
        ):
            asyncio.run(application._run_async_cli_command("failing", fail))

        self.assertEqual("close", events[-1])
        self.assertIn("log", events[:-1])
        self.logging_runtime.close.assert_called_once_with()

    def test_simple_init_initializes_storage_before_business_prepare(self) -> None:
        events: list[str] = []

        class DemoSimpleApplication(SimpleApplication):
            def prepare(self) -> None:
                events.append("prepare")

            async def main(self, *args, **kwargs) -> None:
                pass

        application = DemoSimpleApplication("simple-storage-init")
        storage_registry = Mock()
        storage_registry.init_app.side_effect = lambda: events.append("storage")

        with (
            patch("oldman.runtime.simple.storages", storage_registry),
            patch.object(application, "_setup_system_signals"),
        ):
            application.init()
            application.prepare()

        self.assertEqual(["storage", "prepare"], events)
        storage_registry.init_app.assert_called_once_with()
        storage_registry.close.assert_not_called()

    def test_async_cli_initializes_storage_before_command_lifecycle(self) -> None:
        events: list[str] = []

        class DemoApp(BaseApplication):
            def init(self) -> None:
                pass

            def run(self, *args, **kwargs) -> None:
                pass

            async def before_command(
                self,
                command_name: str,
                *args,
                **kwargs,
            ) -> None:
                events.append(f"before:{command_name}")

            async def after_command(
                self,
                command_name: str,
                *args,
                **kwargs,
            ) -> None:
                events.append(f"after:{command_name}")

        async def command() -> str:
            events.append("command")
            return "ok"

        application = DemoApp("async-storage-command")
        storage_registry = Mock()
        storage_registry.init_app.side_effect = lambda: events.append("storage")

        with patch(
            "oldman.runtime.base.storages",
            storage_registry,
            create=True,
        ):
            result = asyncio.run(application._run_async_cli_command("probe", command))

        self.assertEqual("ok", result)
        self.assertEqual(
            ["storage", "before:probe", "command", "after:probe"],
            events,
        )
        storage_registry.init_app.assert_called_once_with()
        storage_registry.close.assert_not_called()

    def test_default_command_is_bound_to_an_instance(self) -> None:
        events: list[tuple[str, str]] = []

        class DemoApp(BaseApplication):
            @classmethod
            def get_default_commands(cls):
                return {"status": (cls.status, "status")}

            def init(self) -> None:
                pass

            def run(self, *args, **kwargs) -> None:
                pass

            def status(self, value: str) -> str:
                events.extend((("status", value), ("app", self.app_name)))
                return "ok"

        self.assertEqual("ok", DemoApp.execute_command("status", "payload"))
        self.assertEqual([("status", "payload"), ("app", "DemoApp")], events)

    def test_app_command_runs_inside_lifecycle_and_always_cleans_up(self) -> None:
        events: list[tuple[str, str]] = []

        class DemoApp(BaseApplication):
            def init(self) -> None:
                pass

            def run(self, *args, **kwargs) -> None:
                pass

            async def before_command(self, command_name: str, *args, **kwargs) -> None:
                events.append(("before", command_name))

            async def after_command(self, command_name: str, *args, **kwargs) -> None:
                events.append(("after", command_name))

        class CustomCommand(Command):
            name = "custom"
            help = "Run custom command."

            async def handle(self, value: str) -> str:
                events.append(("command", value))
                return "ok"

        self.assertEqual(
            "ok",
            DemoApp.execute_app_command(CustomCommand(), "payload"),
        )
        self.assertEqual([("before", "custom"), ("command", "payload"), ("after", "custom")], events)

    def test_command_pid_guard_removes_file_on_success_and_failure(self) -> None:
        class DemoApp(BaseApplication):
            def init(self) -> None:
                pass

            def run(self, *args, **kwargs) -> None:
                pass

        with tempfile.TemporaryDirectory() as tmp:
            pid_path = Path(tmp) / "command.pid"
            with patch.object(DemoApp, "get_command_pid_path", classmethod(lambda cls, command_name: str(pid_path))):
                class SuccessCommand(Command):
                    name = "success"
                    help = "Succeed."
                    check_pid = True

                    async def handle(self) -> str:
                        return "ok"

                self.assertEqual(
                    "ok",
                    DemoApp.execute_app_command(SuccessCommand()),
                )
                self.assertFalse(pid_path.exists())

                class FailureCommand(Command):
                    name = "failure"
                    help = "Fail."
                    check_pid = True

                    async def handle(self) -> None:
                        raise RuntimeError("boom")

                with self.assertRaisesRegex(RuntimeError, "boom"):
                    DemoApp.execute_app_command(FailureCommand())
                self.assertFalse(pid_path.exists())

    def test_safe_pid_names_cannot_escape_pid_directory(self) -> None:
        self.assertEqual("crawl_cn", BaseApplication.safe_pid_name("../crawl cn/电视"))
        with self.assertRaisesRegex(ValueError, "safe pid file name"):
            BaseApplication.safe_pid_name("../")


if __name__ == "__main__":
    unittest.main()
