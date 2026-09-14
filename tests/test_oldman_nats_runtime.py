"""Actual service entrypoints against owned TCP NATS; no production state resets."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from oldman.providers.nats import NATSConnection
from oldman.serializers import MsgspecModel

ROOT = Path(__file__).resolve().parents[1]
NATS_SERVER = os.environ.get("NATS_SERVER") or shutil.which("nats-server")
REDIS_SERVER = os.environ.get("REDIS_SERVER") or shutil.which("redis-server")


class Number(MsgspecModel):
    """A typed request whose echo proves hooks can reach a separate live receiver."""
    value: int


def _write_project(root: Path, url: str, mode: str, *, enabled: bool = True, web: bool = False) -> None:
    """Build only this test's service/config/apps using the existing bootstrap shape."""
    files = {
        "pyproject.toml": "[project]\nname='nats-runtime-test'\nversion='0'\n",
        "config/__init__.py": "",
        "config/schemas.py": "from oldman.conf import DefaultSettings\nclass Settings(DefaultSettings):\n    pass\n",
        "services/__init__.py": "",
        "example/__init__.py": "",
        "example/apps.py": '''
            from oldman.apps import AppConfig
            class Config(AppConfig):
                label = "example"
                display_name = "NATS lifecycle"
            app = Config()
        ''',
        "example/messages.py": '''
            from pathlib import Path
            from oldman.serializers import MsgspecModel
            class Number(MsgspecModel):
                value: int
            def record(value):
                with Path("trace.txt").open("a") as file:
                    file.write(value + "\\n")
        ''',
        "example/events.py": '''
            import asyncio
            from oldman.providers.nats import bus
            from example.messages import Number, record
            started = asyncio.Event()
            finished = False
            record("events-import")
            @bus.subscriber("hold")
            async def hold(message: Number) -> Number:
                global finished
                record("handler-start")
                started.set()
                try:
                    await asyncio.sleep(0.3)
                    return message
                finally:
                    await asyncio.sleep(0.02)
                    finished = True
                    record("handler-exit")
            @bus.subscriber("peer", peer=True)
            async def peer(message: Number) -> Number:
                return message
        ''',
        "services/worker.py": f'''
            import asyncio
            import sys
            from oldman.conf import settings
            from oldman.providers.nats import bus
            from oldman.runtime import SimpleApplication
            from example.messages import Number, record
            MODE = {mode!r}
            async def probe(stage):
                failed_start = MODE == "connect-fail" or (MODE == "peer-fail" and stage in ("before-stop", "after-stop"))
                if settings.nats_bus.enabled and not failed_start:
                    reply = await bus.request(Number(value=7), "remote", Number)
                    assert reply.value == 7
                else:
                    assert bus.broker._connection is None
                record(stage)
            class Worker(SimpleApplication):
                def prepare(self):
                    record("prepare")
                async def before_start(self):
                    assert not bus.broker.running
                    await probe("before-start")
                    if MODE == "start-fail":
                        raise ValueError("business-start-failure")
                async def main(self):
                    record("main")
                    if MODE == "normal":
                        from example.events import started
                        await started.wait()
                    elif MODE == "disabled":
                        assert "example.events" not in sys.modules
                    elif MODE == "shutdown":
                        asyncio.get_running_loop().call_soon(self.shutdown)
                        await asyncio.Event().wait()
                    else:
                        await asyncio.Event().wait()
                async def before_stop(self):
                    assert not bus.broker.running
                    if MODE in ("normal", "signal"):
                        from example.events import finished
                        assert finished, "business resources closed before handler left"
                    await probe("before-stop")
                    await asyncio.sleep(0.12)
                    await super().before_stop()
                async def after_stop(self):
                    await probe("after-stop")
                    await super().after_stop()
                async def before_command(self, name, *args, **kwargs):
                    assert "example.events" not in sys.modules
                    await probe("before-command")
                async def after_command(self, name, *args, **kwargs):
                    await probe("after-command")
                    await super().after_command(name, *args, **kwargs)
                def _close_logging(self):
                    record("logging-close")
                    assert bus.broker._connection is None
                    super()._close_logging()
        ''',
        "example/commands.py": '''
            from oldman.cli import Command
            from services.worker import probe
            class Probe(Command):
                name = "probe"
                help = "Probe RPC through a one-off command"
                async def handle(self):
                    await probe("command")
            class Fail(Command):
                name = "fail"
                help = "Fail after a successful RPC"
                async def handle(self):
                    await probe("command")
                    raise ValueError("command-failure")
        ''',
        "data/worker_settings.yaml": json.dumps({
            "apps": ["example"],
            "core": {"data_dir": str(root / "data")},
            "logging": {"dir": str(root / "logs"), "color": "never"},
            "process": {"pid_dir": str(root / "pids")},
            "i18n": {"use_i18n": False},
            "nats": {"DEFAULT": {"nats_url": url, "reconnect_time_wait": 0.02}},
            "nats_bus": {"enabled": enabled, "consume": True, "namespace": "runtime_test",
                         "peer_id": None if mode == "peer-fail" else "worker",
                         "startup_timeout": 0.2 if mode == "connect-fail" else 5, "graceful_timeout": 1},
        }),
    }
    if web:
        files["services/worker.py"] = f'''
            import os
            from oldman.conf import settings
            from oldman.providers.nats import bus
            from oldman.runtime import WebApplication
            from example.messages import Number, record
            MODE = {mode!r}
            async def probe(stage):
                if settings.nats_bus.enabled:
                    assert not bus.broker.running
                    reply = await bus.request(Number(value=7), "remote", Number)
                    assert reply.value == 7
                else:
                    assert bus.broker._connection is None
                record(stage)
            class Worker(WebApplication):
                def prepare_server(self, app):
                    assert bus.broker._connection is None
                    record("primary:" + str(os.getpid()))
                    app.prepare(host="127.0.0.1", port=settings.web.listen_port,
                                workers=1, motd=False, access_log=False)
                async def main_process_ready(self, app):
                    assert bus.broker._connection is None
                    record("primary-offline")
                    wait_for_ack = app.manager.wait_for_ack
                    def observed_ack():
                        wait_for_ack()
                        record("manager-ready")
                    app.manager.wait_for_ack = observed_ack
                async def before_server_start(self, app):
                    record("worker:" + str(os.getpid()))
                    await probe("before-start")
                    if MODE == "before-fail":
                        raise ValueError("expected-before-failure")
                async def after_server_start(self, app):
                    await probe("after-start")
                    if MODE == "after-fail":
                        raise ValueError("expected-after-failure")
                    if not settings.nats_bus.enabled:
                        record("web-ready")
                async def _start_nats_consuming(self):
                    await super()._start_nats_consuming()
                    record("web-ready")
                async def before_server_stop(self, app):
                    if MODE == "web-normal":
                        from example.events import finished
                        assert finished, "handler outlived its business dependencies"
                    await probe("before-stop")
                    if MODE == "stop-fail":
                        raise ValueError("expected-stop-failure")
                async def after_server_stop(self, app):
                    await probe("after-stop")
                    if MODE == "after-stop-fail":
                        raise ValueError("expected-after-stop-failure")
                async def _close_nats(self, original_error=None):
                    client = bus.broker._connection
                    await super()._close_nats(original_error)
                    assert bus.broker._connection is None
                    if client is not None:
                        assert client.is_closed
                    record("nats-closed")
                def _close_logging(self):
                    assert bus.broker._connection is None
                    record("logging-close")
                    super()._close_logging()
        '''
        files["example/views.py"] = '''
            from sanic.response import text
            from oldman.web.routing import get_app
            @get_app().get("/probe")
            async def probe(request):
                return text("ready")
        '''
        config = json.loads(files["data/worker_settings.yaml"])
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        config["web"] = {"listen_port": port, "session": {"enabled": False},
                         "sse": {"enabled": False}, "messages": {"enabled": False},
                         "static": {"url": "", "root": ""}}
        files["data/worker_settings.yaml"] = json.dumps(config)
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")


def _write_task_project(root: Path, nats_url: str, redis_url: str, mode: str, *, refused_url: str) -> None:
    """Reuse the tiny CLI project; only dedicated execution entrypoints differ."""
    _write_project(root, nats_url, mode)
    sources = {
        "services/worker.py": '''
            from oldman.runtime import TaskiqWorkerApplication
            from oldman.providers.nats import bus
            from example.messages import record
            class Worker(TaskiqWorkerApplication):
                def run(self, *args, **kwargs):
                    assert bus.broker._connection is None
                    record("parent-offline")
                    try:
                        return super().run(*args, **kwargs)
                    finally:
                        assert bus.broker._connection is None
                        record("parent-closed")
        ''',
        "services/timer.py": '''
            import traceback
            from oldman.runtime import TaskiqSchedulerApplication
            from oldman.providers.nats import bus
            from example.messages import record
            class Timer(TaskiqSchedulerApplication):
                async def main(self, *args, **kwargs):
                    try:
                        await super().main(*args, **kwargs)
                    except BaseException:
                        record(traceback.format_exc())
                        raise
                    finally:
                        assert bus.broker._connection is None
                        record("scheduler-closed")
        ''',
        "example/events.py": 'raise RuntimeError("Taskiq must not import App events, even with consume=true")',
        "example/tasks.py": f'''
            import asyncio, os, sys
            from taskiq import TaskiqEvents
            from oldman.providers.nats import bus
            from oldman.tasks.distributed import broker
            from example.messages import Number, record
            MODE = {mode!r}
            def kind():
                return "scheduler" if broker.is_scheduler_process else "worker" if broker.is_worker_process else "client"
            if MODE == "budget":
                original_connect = bus._connect
                async def delayed_connect():
                    await asyncio.sleep(0.35)
                    await original_connect()
                bus._connect = delayed_connect
            if MODE in ("resources-fail", "shutdown-fail"):
                from oldman.db import db_manager
                original_close = db_manager.close
                async def failed_resource_close():
                    await original_close()
                    raise ValueError("expected-task-resource-failure")
                db_manager.close = failed_resource_close
            async def probe(stage):
                assert "example.events" not in sys.modules
                assert not bus.broker.running and not bus.broker.subscribers
                assert bus.broker._connection is not broker.client
                reply = await bus.request(Number(value=7), "remote", Number)
                assert reply.value == 7
                record(kind() + "-" + stage)
            original_stop = bus.stop
            async def observed_stop():
                client = bus.broker._connection
                await original_stop()
                assert bus.broker._connection is None
                assert client is None or client.is_closed
                record(kind() + "-core-closed")
            bus.stop = observed_stop
            @broker.on_event(TaskiqEvents.WORKER_STARTUP)
            @broker.on_event(TaskiqEvents.CLIENT_STARTUP)
            async def started(state):
                if kind() == "client":
                    return
                await probe("start")
                if MODE == "budget":
                    await asyncio.sleep(0.35)
                    record("startup-hook-finished")
                if MODE == "startup-fail":
                    raise ValueError("expected-task-startup-failure")
            @broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
            @broker.on_event(TaskiqEvents.CLIENT_SHUTDOWN)
            async def stopped(state):
                if kind() == "client":
                    return
                await probe("stop")
                if MODE == "shutdown-fail":
                    raise ValueError("expected-task-shutdown-failure")
            @broker.task()
            async def rpc() -> int:
                await probe("task")
                return os.getpid()
        ''',
        "example/commands.py": '''
            from oldman.cli import Command
            from example.tasks import rpc
            class Submit(Command):
                name = "submit"
                help = "Run a real Taskiq task which calls a separate Core receiver"
                async def handle(self):
                    task = await rpc.kiq()
                    result = await task.wait_result(timeout=8)
                    result.raise_for_error()
                    print("task-pid:" + str(result.return_value))
        ''',
    }
    config = json.loads((root / "data/worker_settings.yaml").read_text())
    config["redis"] = {"DEFAULT": {"redis_url": redis_url}}
    config["taskiq"] = {"enabled": True, "namespace": "Runtime_Probe", "workers": 1,
                        "max_async_tasks": 1, "startup_timeout": 3, "startup_attempts": 1,
                        "shutdown_timeout": 2, "stop_timeout": 6, "schedule_update_interval": 1}
    if mode == "budget":
        config["taskiq"]["startup_timeout"] = 0.55
    if mode == "connect-fail":
        config["nats"]["REFUSED"] = {"nats_url": refused_url, "reconnect_time_wait": 0.02}
        config["nats_bus"]["nats_alias"] = "REFUSED"
    for service in ("worker", "timer"):
        sources[f"data/{service}_settings.yaml"] = json.dumps(config)
    for relative, content in sources.items():
        (root / relative).write_text(textwrap.dedent(content), encoding="utf-8")


@unittest.skipUnless(NATS_SERVER, "Set NATS_SERVER to an executable, not an existing endpoint")
class NatsRuntimeTest(unittest.IsolatedAsyncioTestCase):
    """One local server at a time; actual CLI processes own their resource lifecycle."""

    async def asyncSetUp(self) -> None:
        """Start a separate real RPC receiver for the service startup/shutdown hooks."""
        self.directory = tempfile.TemporaryDirectory(prefix="oldman-nats-runtime-", dir="/tmp")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.log = self.enterContext(open(self.root / "nats.log", "wb"))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.url = f"nats://127.0.0.1:{port}"
        self.server = subprocess.Popen([str(NATS_SERVER), "-a", "127.0.0.1", "-p", str(port),
                                        "-js", "-sd", str(self.root / "jetstream")],
                                       stdout=self.log, stderr=self.log, start_new_session=True)
        self.addAsyncCleanup(self.stop_process, self.server)
        self.remote = NATSConnection(servers=[self.url], namespace="runtime_test", reconnect_time_wait=0.01)

        @self.remote.subscriber("remote")
        async def remote(message: Number) -> Number:
            """An external subscriber remains alive while the CLI process stops."""
            return message

        await self.remote.start()
        self.addAsyncCleanup(self.remote.stop)

    async def stop_process(self, process: subprocess.Popen) -> None:
        """Fallback cleanup only; tests assert normal exit before this runs."""
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.to_thread(process.wait, 3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                await asyncio.to_thread(process.wait, 3)

    async def test_start_waits_for_subscriptions_before_immediate_rpc(self) -> None:
        """A delayed TCP segment must not let a premature PONG declare readiness."""
        from nats.aio.client import Client

        release, received = asyncio.Event(), asyncio.Event()
        connections: set[asyncio.Task] = set()

        async def proxy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            """Keep wire order intact while delaying the segment starting with SUB."""
            owner = asyncio.current_task()
            assert owner is not None
            connections.add(owner)
            remote_reader, remote_writer = await asyncio.open_connection("127.0.0.1", int(self.url.rsplit(":", 1)[1]))

            async def upstream() -> None:
                """Forward every byte; the barrier is only a network delay."""
                while line := await reader.readline():
                    if line.startswith(b"SUB "):
                        received.set()
                        await release.wait()
                    remote_writer.write(line)
                    await remote_writer.drain()

            async def downstream() -> None:
                """Let server PONGs reach the real client without delay."""
                while data := await remote_reader.read(65536):
                    writer.write(data)
                    await writer.drain()

            forwarding = [asyncio.create_task(upstream()), asyncio.create_task(downstream())]
            try:
                await asyncio.wait(forwarding, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in forwarding:
                    task.cancel()
                await asyncio.gather(*forwarding, return_exceptions=True)
                writer.close()
                remote_writer.close()
                await asyncio.gather(writer.wait_closed(), remote_writer.wait_closed(), return_exceptions=True)
                connections.discard(owner)

        async with await asyncio.start_server(proxy, "127.0.0.1", 0) as listener:
            port = listener.sockets[0].getsockname()[1]
            receiver = NATSConnection([f"nats://127.0.0.1:{port}"], namespace="runtime_test", allow_reconnect=False)

            @receiver.subscriber("startup-echo")
            async def echo(message: Number) -> Number:
                """Use the real router, serializer and server for the first RPC."""
                return message

            starting = asyncio.create_task(receiver.start())
            try:
                await asyncio.wait_for(received.wait(), 2)
                with self.assertRaises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(starting), 0.05)
                release.set()
                await asyncio.wait_for(starting, 2)
                reply = await self.remote.request(Number(value=7), "startup-echo", Number)
                self.assertEqual(reply.value, 7)
                client = receiver.broker._connection
                assert client is not None
                self.assertEqual(client._send_ping, Client._send_ping.__get__(client, Client))
            finally:
                release.set()
                await asyncio.gather(starting, return_exceptions=True)
                try:
                    await receiver.stop()
                finally:
                    for task in tuple(connections):
                        task.cancel()
                    await asyncio.gather(*connections, return_exceptions=True)

    async def test_start_sender_timeout_and_cancellation_close_resources(self) -> None:
        """A stalled sender cannot report readiness or prevent startup cleanup."""
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                receiver = NATSConnection([self.url], namespace="runtime_test", startup_timeout=0.05)
                await receiver._connect()
                client = receiver.broker._connection
                assert client is not None and client._flusher_task is not None
                client._flusher_task.cancel()
                await asyncio.gather(client._flusher_task, return_exceptions=True)
                # Model a native sender blocked on I/O; the connection and its
                # reader/heartbeat/cleanup remain real and unchanged.
                client._flusher_task = asyncio.create_task(asyncio.Event().wait())
                starting = asyncio.create_task(receiver._start_consuming())
                try:
                    if cancel:
                        await asyncio.sleep(0)
                        starting.cancel()
                    with self.assertRaises(asyncio.CancelledError if cancel else TimeoutError):
                        await starting
                    self.assertTrue(client.is_closed)
                    self.assertTrue(client._flusher_task.done())
                    self.assertIsNone(receiver.broker._connection)
                finally:
                    await receiver.stop()

    def launch(self, mode: str, *, command: str = "start", enabled: bool = True,
               url: str | None = None, web: bool = False) -> subprocess.Popen:
        """Use the actual project CLI and existing service discovery/Settings loader."""
        project = self.root / mode
        _write_project(project, url or self.url, mode, enabled=enabled, web=web)
        environment = {**os.environ, "PYTHONPATH": str(ROOT)}
        if web:
            synchronized = subprocess.run([sys.executable, "-m", "oldman.cli", "worker", "settings", "sync"],
                                          cwd=project, env=environment, capture_output=True, text=True, timeout=10)
            self.assertEqual(synchronized.returncode, 0, synchronized.stdout + synchronized.stderr)
        process = subprocess.Popen([sys.executable, "-m", "oldman.cli", "worker", command], cwd=project,
                                   env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, start_new_session=True)
        self.addAsyncCleanup(self.stop_process, process)
        return process

    async def wait_trace(self, mode: str, value: str, process: subprocess.Popen) -> list[str]:
        """Wait for a concrete business marker; fail promptly if the service exits."""
        path = self.root / mode / "trace.txt"
        async with asyncio.timeout(10):
            while True:
                lines = path.read_text().splitlines() if path.exists() else []
                if value in lines:
                    return lines
                if process.poll() is not None:
                    self.fail(f"Service exited before {value}: {process.communicate()[0]}")
                await asyncio.sleep(0.01)

    async def finish(self, mode: str, process: subprocess.Popen, *, success: bool | None, web: bool = False) -> list[str]:
        """Capture ordinary exit and check no cleanup error was hidden by forced teardown."""
        try:
            output, _ = await asyncio.to_thread(process.communicate, timeout=12)
        except subprocess.TimeoutExpired as error:
            trace = self.root / mode / "trace.txt"
            self.fail(f"Exit timed out: {error.output!r}; trace={trace.read_text() if trace.exists() else 'missing'}")
        if success is not None:
            self.assertEqual(process.returncode == 0, success, output)
        if web and success is None:
            expected = {"before-fail": "expected-before-failure", "after-fail": "expected-after-failure",
                        "stop-fail": "expected-stop-failure", "after-stop-fail": "expected-after-stop-failure",
                        "peer-fail": "peer=True subscriber requires", "connect-fail": "NATS startup timed out"}
            self.assertIn(expected[mode], output)
        self.assertNotIn("Event loop stopped before Future completed", output)
        self.assertNotIn("Task was destroyed", output)
        trace = self.root / mode / "trace.txt"
        self.assertTrue(trace.exists(), output)
        lines = trace.read_text().splitlines()
        # Sanic's manager uses os._exit on worker failure, bypassing primary finally.
        if not web or process.returncode == 0:
            self.assertEqual(lines[-1], "logging-close", output)
            self.assertEqual(lines.count("logging-close"), 1, output)
        return lines

    async def test_normal_and_signal_shutdown_keep_handler_dependencies(self) -> None:
        """Natural return and real signals drain handlers before hooks; repeat signals are safe."""
        for mode, sig in (("normal", None), ("signal", signal.SIGINT), ("signal", signal.SIGTERM)):
            with self.subTest(mode=mode, signal=sig):
                trace = self.root / mode / "trace.txt"
                if trace.exists():
                    trace.unlink()
                process = self.launch(mode)
                await self.wait_trace(mode, "main", process)
                reply = asyncio.create_task(self.remote.request(Number(value=3), "hold", Number))
                try:
                    await self.wait_trace(mode, "handler-start", process)
                    if sig is not None:
                        process.send_signal(sig)
                        await self.wait_trace(mode, "before-stop", process)
                        process.send_signal(sig)
                    self.assertEqual((await reply).value, 3)
                    lines = await self.finish(mode, process, success=True)
                    self.assertEqual(lines, ["events-import", "prepare", "before-start", "main", "handler-start",
                                             "handler-exit", "before-stop", "after-stop", "logging-close"])
                finally:
                    if not reply.done():
                        reply.cancel()
                    await asyncio.gather(reply, return_exceptions=True)

    async def test_disabled_shutdown_and_startup_failures(self) -> None:
        """Keep disabled/legacy business behavior, but fail required NATS startup."""
        for mode, enabled, success in (("disabled", False, True), ("shutdown", True, True),
                                       ("start-fail", True, True), ("peer-fail", True, False)):
            with self.subTest(mode=mode):
                process = self.launch(mode, enabled=enabled)
                lines = await self.finish(mode, process, success=success)
                self.assertIn("before-stop", lines)
                self.assertIn("after-stop", lines)
                self.assertEqual("main" in lines, mode in ("disabled", "shutdown"))
                self.assertEqual("events-import" in lines, enabled)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            process = self.launch("connect-fail", url=f"nats://127.0.0.1:{sock.getsockname()[1]}")
            lines = await self.finish("connect-fail", process, success=False)
        self.assertNotIn("before-start", lines)
        self.assertNotIn("main", lines)
        self.assertIn("after-stop", lines)

    async def test_commands_send_without_loading_events_and_close_on_failure(self) -> None:
        """Both command outcomes preserve before/body/after and final connection cleanup."""
        for command in ("probe", "fail"):
            with self.subTest(command=command):
                process = self.launch(command, command=command)
                lines = await self.finish(command, process, success=command == "probe")
                self.assertEqual(lines, ["before-command", "command", "after-command", "logging-close"])

    async def test_web_worker_hooks_and_handler_drain(self) -> None:
        """A real spawned Sanic worker owns Core; hooks deliberately do not call super."""
        process = self.launch("web-normal", web=True)
        lines = await self.wait_trace("web-normal", "web-ready", process)
        await self.wait_trace("web-normal", "manager-ready", process)
        primary = next(line for line in lines if line.startswith("primary:"))
        worker = next(line for line in lines if line.startswith("worker:"))
        self.assertNotEqual(primary.split(":")[1], worker.split(":")[1])
        self.assertLess(lines.index("after-start"), lines.index("web-ready"))
        reply = asyncio.create_task(self.remote.request(Number(value=3), "hold", Number))
        try:
            await self.wait_trace("web-normal", "handler-start", process)
            process.send_signal(signal.SIGTERM)
            self.assertEqual((await reply).value, 3)
            lines = await self.finish("web-normal", process, success=True, web=True)
        finally:
            if not reply.done():
                reply.cancel()
            await asyncio.gather(reply, return_exceptions=True)
        order = ["handler-exit", "before-stop", "after-stop", "nats-closed", "logging-close"]
        self.assertEqual([line for line in lines if line in order], order)
        self.assertIn("primary-offline", lines)

    async def test_web_failed_hooks_and_disabled_bus(self) -> None:
        """Partial startup and either failed shutdown hook still close the actual client."""
        for mode in ("before-fail", "after-fail", "peer-fail", "stop-fail", "after-stop-fail", "web-disabled"):
            with self.subTest(mode=mode):
                enabled = mode != "web-disabled"
                process = self.launch(mode, web=True, enabled=enabled)
                if mode in ("stop-fail", "after-stop-fail", "web-disabled"):
                    await self.wait_trace(mode, "web-ready", process)
                    await self.wait_trace(mode, "manager-ready", process)
                    process.send_signal(signal.SIGTERM)
                lines = await self.finish(mode, process, success=None if enabled else True, web=True)
                self.assertEqual(lines.count("nats-closed"), int(enabled))
                self.assertEqual("events-import" in lines, enabled)
                self.assertEqual("after-stop" in lines, mode in ("after-stop-fail", "web-disabled"))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            process = self.launch("connect-fail", web=True, url=f"nats://127.0.0.1:{sock.getsockname()[1]}")
            lines = await self.finish("connect-fail", process, success=None, web=True)
            self.assertNotIn("before-start", lines)
            self.assertIn("nats-closed", lines)

    @unittest.skipUnless(REDIS_SERVER, "Dedicated Taskiq entrypoints require an owned Redis executable")
    async def test_taskiq_worker_scheduler_and_native_hooks(self) -> None:
        """Actual child/task and scheduler hooks can RPC without becoming Core receivers."""
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        redis = subprocess.Popen([str(REDIS_SERVER), "--bind", "127.0.0.1", "--port", str(port),
                                  "--save", "", "--appendonly", "no", "--dir", str(self.root)],
                                 stdout=self.log, stderr=self.log, start_new_session=True)
        self.addAsyncCleanup(self.stop_process, redis)
        refused = self.enterContext(socket.socket())
        refused.bind(("127.0.0.1", 0))
        refused_url = f"nats://127.0.0.1:{refused.getsockname()[1]}"
        for service, mode in (("worker", "normal"), ("timer", "normal"),
                              ("worker", "startup-fail"), ("timer", "shutdown-fail"),
                              ("worker", "budget"), ("timer", "resources-fail"),
                              ("worker", "connect-fail"), ("timer", "connect-fail")):
            case = f"{service}-{mode}"
            with self.subTest(service=service, mode=mode):
                project = self.root / case
                _write_task_project(project, self.url, f"redis://127.0.0.1:{port}/0", mode, refused_url=refused_url)
                environment = {**os.environ, "PYTHONPATH": str(ROOT)}
                command = [sys.executable, "-m", "oldman.cli", service]
                process = subprocess.Popen([*command, "start"], cwd=project, env=environment,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
                self.addAsyncCleanup(self.stop_process, process)
                try:
                    kind = "scheduler" if service == "timer" else "worker"
                    if mode != "connect-fail":
                        await self.wait_trace(case, f"{kind}-start", process)
                    if mode not in ("startup-fail", "budget", "connect-fail"):
                        if service == "worker":
                            submitted = await asyncio.to_thread(subprocess.run, [*command, "submit"], cwd=project,
                                                                env=environment, capture_output=True, text=True, timeout=12)
                            self.assertEqual(submitted.returncode, 0, submitted.stdout + submitted.stderr)
                            task_pid = int(submitted.stdout.split("task-pid:")[1].splitlines()[0])
                            self.assertNotEqual(task_pid, process.pid)
                        stopped = await asyncio.to_thread(subprocess.run, [*command, "stop"], cwd=project,
                                                          env=environment, capture_output=True, text=True, timeout=10)
                        self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr)
                    output, _ = await asyncio.to_thread(process.communicate, timeout=10)
                    self.assertEqual(process.returncode == 0, mode == "normal", output)
                    lines = (project / "trace.txt").read_text().splitlines()
                    from oldman.processes.subprocess import _live_process_group_pids

                    self.assertFalse(_live_process_group_pids(process.pid))
                    if mode == "connect-fail":
                        self.assertNotIn(f"{kind}-start", lines)
                        self.assertIn(f"{kind}-core-closed", lines)
                        self.assertNotIn("Taskiq Scheduler is ready", output)
                        self.assertNotIn("All 1 Taskiq worker processes are ready", output)
                        self.assertIn("NATS startup timed out", output)
                        continue
                    self.assertLess(lines.index(f"{kind}-stop"), lines.index(f"{kind}-core-closed"), lines)
                    if service == "worker":
                        self.assertIn("parent-offline", lines)
                        self.assertIn("parent-closed", lines)
                        if mode == "normal":
                            self.assertIn("worker-task", lines)
                    else:
                        self.assertIn("scheduler-closed", lines)
                    if mode == "budget":
                        self.assertNotIn("startup-hook-finished", lines)
                        self.assertNotIn("All 1 Taskiq worker processes are ready", output)
                        self.assertIn("TimeoutError", output)
                    elif mode != "normal":
                        self.assertIn("expected-task-", output + "\n".join(lines))
                    self.assertNotIn("Task was destroyed", output)
                finally:
                    await self.stop_process(process)


if __name__ == "__main__":
    unittest.main()
