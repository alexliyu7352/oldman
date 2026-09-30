"""Application command lifecycle regressions migrated from the foundation source."""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

import oldman.conf as conf
from oldman.apps import AppRegistry
from oldman.cli import Command
from oldman.conf.schemas import DefaultSettings
from oldman.runtime import ServiceBootstrapContext
from oldman.runtime._process_group import GroupIdentity, _process_identity
from oldman.runtime.base import BaseApplication, _lock_pid_file, _release_pid_file, _write_pid
from oldman.runtime.simple import SimpleApplication

ROOT = Path(__file__).resolve().parents[1]


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
                "logger_level": logging.INFO,
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

    def test_a_failing_main_is_raised_with_its_traceback_logged(self) -> None:
        """It used to be logged as one line and swallowed: the service exited 0 on any error."""

        class FailingSimpleApplication(SimpleApplication):
            def prepare(self) -> None:
                pass

            async def main(self, *args, **kwargs) -> None:
                async def broken() -> None:
                    raise RuntimeError("Redis password is wrong")

                async with asyncio.TaskGroup() as group:
                    group.create_task(broken())

        application = FailingSimpleApplication("simple-failing")
        with (
            patch.object(FailingSimpleApplication, "init"),
            patch.object(FailingSimpleApplication, "_close_services", AsyncMock()),
            self.assertLogs("default", level="ERROR") as logs,
            self.assertRaises(ExceptionGroup),
        ):
            application.run()
        failure = next(record for record in logs.records if "运行异常" in record.getMessage())
        self.assertIsNotNone(failure.exc_info)
        self.assertIn("RuntimeError: Redis password is wrong", logging.Formatter().format(failure))

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

    def test_a_command_instance_never_removes_the_running_services_pid_file(self) -> None:
        """A stop command run by systemd (parent PID 1) deleted the running service's PID file as it exited."""
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(self.settings.process, "pid_dir", Path(tmp)),
            patch("oldman.runtime.base.os.getppid", return_value=1),
        ):
            application = DemoApplication("stop-command")
            pid_file = Path(application.pid_file_path)
            pid_file.write_text("4242", encoding="utf-8")  # the running service's
            application._close_logging()
            application._close_logging()

            self.assertEqual("4242", pid_file.read_text(encoding="utf-8"))
            self.logging_runtime.close.assert_called_once_with()

    def test_the_pid_file_path_does_not_follow_the_working_directory(self) -> None:
        with patch.object(self.settings.process, "pid_dir", Path("relative-pids")):
            application = DemoApplication("relative")
        self.assertEqual(os.path.join(os.getcwd(), "relative-pids", "test_service.pid"), application.pid_file_path)

    def test_a_run_removes_its_pid_file_before_its_identity_record_and_both_before_the_lock(self) -> None:
        # In between, a stop found the PID file without its record and blamed an earlier version.
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.settings.process, "pid_dir", Path(tmp)):
            application = DemoApplication("exiting")
            pid_path = Path(application.pid_file_path)
            fd = _lock_pid_file(str(pid_path))
            application._pid_fd = fd
            _write_pid(fd, os.getpid())
            boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            application._identity_path.write_text(GroupIdentity(os.getpid(), os.getpid(), 12345, boot_id).to_json())
            seen: list[tuple[bool, bool]] = []
            unlink = Path.unlink

            def record_state(path: Path, *args: Any, **kwargs: Any) -> None:
                if path == application._identity_path:
                    try:
                        os.fstat(fd)
                        locked = True
                    except OSError:
                        locked = False
                    seen.append((pid_path.exists(), locked))
                unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", record_state):
                application.delete_pid_file()
            self.assertEqual([(False, True)], seen, "(PID file still there, lock still held) when the record went")
            self.assertFalse(application._identity_path.exists())

    def test_a_holder_does_not_remove_a_pid_file_that_replaced_its_own(self) -> None:
        # Its file was removed and a new run made its own at the path: releasing must leave that one alone.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "service.pid")
            fd = _lock_pid_file(path)
            os.remove(path)
            Path(path).write_text("4242")
            _release_pid_file(fd, path)
            self.assertEqual("4242", Path(path).read_text())

    def test_stop_cleanup_removes_only_the_identity_record_it_read(self) -> None:
        # A record written since stop read the one it stopped by belongs to another run.
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.settings.process, "pid_dir", Path(tmp)):
            application = DemoApplication("cleanup")
            boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            written_since = GroupIdentity(4343, 4343, 2, boot_id).to_json()
            application._identity_path.write_text(written_since)
            application._remove_records(GroupIdentity(4242, 4242, 1, boot_id).to_json())
            self.assertEqual(written_since, application._identity_path.read_text())

    def test_an_app_command_pid_path_does_not_follow_the_working_directory(self) -> None:
        # A command that changed directory looked for its own file elsewhere and left it behind.
        with patch.object(self.settings.process, "pid_dir", Path("relative-pids")):
            path = DemoApplication.get_command_pid_path("sync")
        self.assertEqual(os.path.join(os.getcwd(), "relative-pids", "test_service.sync.pid"), path)

    def test_an_app_command_pid_file_is_never_another_services_pid_file(self) -> None:
        # Service a_b and command b of service a both used pids/a_b.pid and kept each other from running.
        def context(service_module: str) -> ServiceBootstrapContext:
            return ServiceBootstrapContext(service_module, Path(f"data/{service_module}_settings.yaml"), self.settings, cast(Any, self.apps))

        with patch("oldman.runtime.base._get_bootstrap_context", return_value=context("a")):
            command_file = DemoApplication.get_command_pid_path("b")
        with patch("oldman.runtime.base._get_bootstrap_context", return_value=context("a_b")):
            service_file = DemoApplication("service").pid_file_path
        self.assertNotEqual(service_file, command_file)

    def test_stop_from_inside_the_running_service_is_refused_in_plain_words(self) -> None:
        # A process group of the test's own stands for the running service the caller is in, so the
        # test does not depend on the group the test runner happens to be in.
        service = subprocess.Popen(["sleep", "60"], start_new_session=True)
        self.addCleanup(service.wait)
        self.addCleanup(service.kill)
        identity = _process_identity(service.pid)
        assert identity is not None
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(self.settings.process, "pid_dir", Path(tmp)),
            patch("oldman.runtime.base.os.getpgrp", return_value=service.pid),
        ):
            application = DemoApplication("inside")
            Path(application.pid_file_path).write_text(str(service.pid))
            application._identity_path.write_text(GroupIdentity(service.pid, service.pid, identity[1], boot_id).to_json())
            with self.assertRaisesRegex(RuntimeError, "cannot be called from inside the running service"):
                application.stop()
        self.assertIsNone(service.poll(), "stop signalled the group it was called from")
        # The refusal used to close the logging of the service it was called in.
        self.logging_runtime.close.assert_not_called()

    def test_a_start_refused_inside_a_running_service_leaves_its_logging_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.settings.process, "pid_dir", Path(tmp)):
            application = DemoApplication("inside")
            holder = os.open(application.pid_file_path, os.O_RDWR | os.O_CREAT)
            self.addCleanup(os.close, holder)
            fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)  # the running service's lock
            with self.assertRaisesRegex(RuntimeError, "already running"):
                application.start()
        self.logging_runtime.close.assert_not_called()

    def test_the_command_line_closes_the_logging_of_the_instance_it_built(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.settings.process, "pid_dir", Path(tmp)):
            self.assertEqual(0, DemoApplication.execute_command("stop"))
        self.logging_runtime.close.assert_called_once_with()

    def test_start_locks_the_pid_file_now_at_the_path_not_one_just_removed(self) -> None:
        """A run that exits removes its file before unlocking; a lock won on that removed file guarded nothing."""
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.settings.process, "pid_dir", Path(tmp)):
            application = DemoApplication("replaced")
            path = Path(application.pid_file_path)
            path.write_text("1")
            real_flock = fcntl.flock
            replaced: list[bool] = []

            def flock_after_the_file_is_replaced(fd: int, operation: int) -> None:
                if not replaced:
                    # Between this start opening the file and locking it, the previous run removes
                    # the file and releases its lock, and another start creates a new file there.
                    path.unlink()
                    path.write_text("")
                    replaced.append(True)
                real_flock(fd, operation)

            seen: dict[str, str] = {}

            def run(*args: Any, **kwargs: Any) -> None:
                probe = os.open(path, os.O_RDWR)
                try:
                    with self.assertRaises(BlockingIOError, msg="the file at the path is not the locked one"):
                        real_flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally:
                    os.close(probe)
                seen["pid"] = path.read_text()

            @contextmanager
            def own_group() -> Iterator[GroupIdentity]:
                yield GroupIdentity(os.getpid(), os.getpid(), 1, "boot")

            with (
                patch("oldman.runtime.base.fcntl.flock", side_effect=flock_after_the_file_is_replaced),
                patch("oldman.runtime.base.service_process_group", own_group),
                patch.object(application, "run", side_effect=run),
            ):
                application.start()
            self.assertEqual(str(os.getpid()), seen["pid"])

    def test_a_forked_child_leaving_through_the_release_keeps_the_parents_file_and_lock(self) -> None:
        """Its copy of the descriptor is closed: releasing it read and closed a descriptor it no longer had."""
        with tempfile.TemporaryDirectory() as tmp:
            pid_path = os.path.join(tmp, "service_sync.pid")
            script = textwrap.dedent(
                f"""
                import fcntl, os
                from oldman.runtime.base import BaseApplication

                class Service(BaseApplication):
                    SERVICE_NAME = "Service"
                    def init(self): pass
                    def run(self, *args, **kwargs): pass

                fd = Service.create_command_pid_file({pid_path!r}, "sync")
                child = os.fork()
                if child == 0:
                    # As a child that returns from the command through the guard's finally.
                    try:
                        Service.delete_command_pid_file({pid_path!r}, fd)
                    except BaseException:
                        os._exit(2)
                    os._exit(0)
                _, status = os.waitpid(child, 0)
                probe = os.open({pid_path!r}, os.O_RDWR)
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held = False
                except BlockingIOError:
                    held = True
                print(os.waitstatus_to_exitcode(status), os.path.exists({pid_path!r}), held)
                """
            )
            completed = subprocess.run(
                [sys.executable, "-c", script],
                env={**os.environ, "PYTHONPATH": str(ROOT)},
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=30,
            )
        self.assertEqual("0 True True", completed.stdout.strip().splitlines()[-1], completed.stdout + completed.stderr)

    def test_a_command_lock_ends_with_the_command_not_with_a_forked_child(self) -> None:
        """A command that dies while a child it forked lives on: the child must not keep the command locked."""
        with tempfile.TemporaryDirectory() as tmp:
            pid_path = os.path.join(tmp, "service_sync.pid")
            child_pid_file = os.path.join(tmp, "child.pid")
            script = textwrap.dedent(
                f"""
                import os, time
                from oldman.runtime.base import BaseApplication

                class Service(BaseApplication):
                    SERVICE_NAME = "Service"
                    def init(self): pass
                    def run(self, *args, **kwargs): pass

                Service.create_command_pid_file({pid_path!r}, "sync")
                child = os.fork()
                if child == 0:
                    time.sleep(10)
                    os._exit(0)
                with open({child_pid_file!r}, "w") as f:
                    f.write(str(child))
                os._exit(0)  # the command dies: no cleanup, no unlock
                """
            )
            subprocess.run(
                [sys.executable, "-c", script],
                env={**os.environ, "PYTHONPATH": str(ROOT)},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=30,
            )
            child = int(Path(child_pid_file).read_text())
            # Not this test's child: kill it below only while it is the same process.
            child_identity = _process_identity(child)
            try:
                probe = os.open(pid_path, os.O_RDWR)
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally:
                    os.close(probe)
            finally:
                if child_identity is not None and _process_identity(child) == child_identity:
                    os.kill(child, signal.SIGKILL)

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
            patch("oldman.cache.memory_cache.close", new=AsyncMock()),
            patch("oldman.providers.redis.redis_client.close", new=AsyncMock()),
            patch("oldman.runtime.base.logger.info", side_effect=lambda *args, **kwargs: events.append("log")),
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

    def test_app_command_runs_after_command_before_publishers_invalidations_and_resources(self) -> None:
        """N-1: after_command ran after taskiq and NATS were closed, so it could no longer enqueue or publish.

        A command that commits and returns at once must not lose the invalidation either (asyncio.run would cancel it).
        """
        events: list[str] = []

        class DemoApp(BaseApplication):
            def init(self) -> None:
                pass

            def run(self, *args, **kwargs) -> None:
                pass

            async def after_command(self, command_name: str, *args, **kwargs) -> None:
                events.append("after")

        class CommitCommand(Command):
            name = "commit"
            help = "Commit and return."

            async def handle(self) -> None:
                events.append("command")

        with (
            patch.object(DemoApp, "_close_publishers", AsyncMock(side_effect=lambda *args: events.append("publishers"))),
            patch.object(DemoApp, "_close_shared_resources", AsyncMock(side_effect=lambda: events.append("resources"))),
            patch("oldman.db.sqlalchemy.cache.wait_for_invalidations", AsyncMock(side_effect=lambda: events.append("invalidations"))),
        ):
            DemoApp.execute_app_command(CommitCommand())

        self.assertEqual(["command", "after", "publishers", "invalidations", "resources"], events)

    def test_app_command_closes_resources_when_the_invalidation_wait_is_cancelled(self) -> None:
        """A Ctrl+C while the command waits for the invalidations cancels the wait; the resources still close."""
        events: list[str] = []

        class DemoApp(BaseApplication):
            def init(self) -> None:
                pass

            def run(self, *args, **kwargs) -> None:
                pass

            async def after_command(self, command_name: str, *args, **kwargs) -> None:
                events.append("after")

        class CommitCommand(Command):
            name = "commit"
            help = "Commit and return."

            async def handle(self) -> None:
                events.append("command")

        with (
            patch.object(DemoApp, "_close_shared_resources", AsyncMock(side_effect=lambda: events.append("resources"))),
            patch("oldman.db.sqlalchemy.cache.wait_for_invalidations", AsyncMock(side_effect=asyncio.CancelledError)),
            self.assertRaises(asyncio.CancelledError),
        ):
            DemoApp.execute_app_command(CommitCommand())

        self.assertEqual(["command", "after", "resources"], events)

    def test_simple_service_waits_for_model_cache_invalidations_after_the_stop_hooks(self) -> None:
        """before_stop cancels background tasks; invalidations are not among them and finish before the resources close."""
        events: list[str] = []

        class DemoSimpleApplication(SimpleApplication):
            def prepare(self) -> None:
                pass

            async def main(self, *args, **kwargs) -> None:
                events.append("main")

            async def before_stop(self) -> None:
                events.append("before_stop")

            async def after_stop(self) -> None:
                events.append("after_stop")

        application = DemoSimpleApplication("simple-invalidations")
        with (
            patch.object(DemoSimpleApplication, "_close_shared_resources", AsyncMock(side_effect=lambda: events.append("resources"))),
            patch("oldman.db.sqlalchemy.cache.wait_for_invalidations", AsyncMock(side_effect=lambda: events.append("invalidations"))),
        ):
            asyncio.run(application._run_async())

        self.assertEqual(["main", "before_stop", "after_stop", "invalidations", "resources"], events)

    def test_simple_service_closes_resources_when_the_invalidation_wait_is_cancelled(self) -> None:
        events: list[str] = []

        class DemoSimpleApplication(SimpleApplication):
            def prepare(self) -> None:
                pass

            async def main(self, *args, **kwargs) -> None:
                events.append("main")

            async def after_stop(self) -> None:
                events.append("after_stop")

        application = DemoSimpleApplication("simple-cancelled-wait")
        with (
            patch.object(DemoSimpleApplication, "_close_shared_resources", AsyncMock(side_effect=lambda: events.append("resources"))),
            patch("oldman.db.sqlalchemy.cache.wait_for_invalidations", AsyncMock(side_effect=asyncio.CancelledError)),
            self.assertRaises(asyncio.CancelledError),
        ):
            asyncio.run(application._run_async())

        self.assertEqual(["main", "after_stop", "resources"], events)

    def test_taskiq_worker_waits_for_model_cache_invalidations_before_closing_clients(self) -> None:
        """Run in a child: importing oldman.tasks.distributed needs taskiq settings and must not leak into this process."""
        probe = textwrap.dedent(
            """
            import asyncio, json
            from unittest.mock import AsyncMock, patch
            from oldman import conf
            from oldman.conf.schemas import DefaultSettings

            conf._publish_settings(DefaultSettings.model_validate({"taskiq": {"enabled": True, "namespace": "Close_Order"}}))
            from oldman.tasks.distributed.worker import close_worker_resources

            events = []

            def step(label):
                return AsyncMock(side_effect=lambda: events.append(label))

            with (
                patch("oldman.db.sqlalchemy.cache.wait_for_invalidations", step("invalidations")),
                patch("oldman.db.db_manager.close", step("database")),
                patch("oldman.cache.memory_cache.close", step("memory")),
                patch("oldman.providers.redis.redis_client.close", step("redis")),
            ):
                asyncio.run(close_worker_resources())
            print(json.dumps(events))

            # A cancelled wait still closes the clients.
            events.clear()
            with (
                patch("oldman.db.sqlalchemy.cache.wait_for_invalidations", AsyncMock(side_effect=asyncio.CancelledError)),
                patch("oldman.db.db_manager.close", step("database")),
                patch("oldman.cache.memory_cache.close", step("memory")),
                patch("oldman.providers.redis.redis_client.close", step("redis")),
            ):
                try:
                    asyncio.run(close_worker_resources())
                except asyncio.CancelledError:
                    events.append("cancelled")
            print(json.dumps(events))
            """
        )
        completed = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(0, completed.returncode, completed.stderr)
        waited, cancelled = (json.loads(line) for line in completed.stdout.strip().splitlines()[-2:])
        self.assertEqual("invalidations", waited[0])
        self.assertEqual({"database", "memory", "redis"}, set(waited[1:]))
        self.assertEqual({"database", "memory", "redis"}, set(cancelled[:-1]))
        self.assertEqual("cancelled", cancelled[-1])

    def test_process_worker_waits_for_model_cache_invalidations_during_cleanup(self) -> None:
        from oldman.tasks.worker import BaseWorker

        events: list[str] = []

        class DemoWorker(BaseWorker):
            async def initialize(self) -> None:
                pass

        worker = DemoWorker(1, Mock())
        with (
            patch.object(worker.task_manager, "stop_all", AsyncMock(side_effect=lambda: events.append("stop_all"))),
            patch.object(worker.comm_manager, "cleanup", Mock(side_effect=lambda: events.append("communication"))),
            patch("oldman.db.sqlalchemy.cache.wait_for_invalidations", AsyncMock(side_effect=lambda: events.append("invalidations"))),
        ):
            asyncio.run(worker.cleanup())

        self.assertEqual(["stop_all", "invalidations", "communication"], events)

    def test_process_worker_cleans_up_communication_when_the_invalidation_wait_is_cancelled(self) -> None:
        from oldman.tasks.worker import BaseWorker

        events: list[str] = []

        class DemoWorker(BaseWorker):
            async def initialize(self) -> None:
                pass

        worker = DemoWorker(1, Mock())
        with (
            patch.object(worker.comm_manager, "cleanup", Mock(side_effect=lambda: events.append("communication"))),
            patch("oldman.db.sqlalchemy.cache.wait_for_invalidations", AsyncMock(side_effect=asyncio.CancelledError)),
            self.assertRaises(asyncio.CancelledError),
        ):
            asyncio.run(worker.cleanup())

        self.assertEqual(["communication"], events)

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

    def test_current_is_the_service_this_process_constructed(self) -> None:
        """Code outside the service class reaches the instance that runs, never a new one."""
        first = DemoApplication("first")
        self.assertIs(first, DemoApplication.current())

        # One process bootstraps one service, so a later instance is that service again.
        second = DemoApplication("second")
        self.assertIs(second, DemoApplication.current())

    def test_current_on_a_base_class_answers_for_any_service_of_that_kind(self) -> None:
        """Reusable Apps do not know the project's service class; they ask a base class."""
        application = DemoApplication("generic")

        self.assertIs(application, BaseApplication.current())
        # The running service is not a SimpleApplication, so that question has no answer.
        self.assertIsNone(SimpleApplication.current())

    def test_current_is_none_where_no_service_was_constructed(self) -> None:
        """A shell, a bootstrap_service() script or a Taskiq worker child imports code freely."""
        from oldman.runtime import base

        with patch.object(base, "_current_service", None):
            self.assertIsNone(BaseApplication.current())
            self.assertIsNone(DemoApplication.current())

    def test_a_service_without_a_web_server_has_no_runtime_app(self) -> None:
        """Every service answers runtime_app, so callers only check for None."""
        DemoApplication("no-server")

        running = BaseApplication.current()
        assert running is not None
        self.assertIsNone(running.runtime_app)


if __name__ == "__main__":
    unittest.main()
