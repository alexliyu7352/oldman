"""Real transport checks in a fresh process, without touching service settings.

Set NATS_SERVER and REDIS_SERVER to local binaries. Each check owns its servers,
namespace, Redis data and temporary directory; no configured user service is used.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import pty
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
NATS_SERVER = os.environ.get("NATS_SERVER") or shutil.which("nats-server")
REDIS_SERVER = os.environ.get("REDIS_SERVER") or shutil.which("redis-server")


@unittest.skipUnless(NATS_SERVER and REDIS_SERVER, "Real task checks require NATS_SERVER and REDIS_SERVER")
class DistributedTaskIntegrationTest(unittest.TestCase):
    """Run the public objects and native Receiver against owned real facilities."""

    def test_transport_lifecycle(self) -> None:
        """Include failure, ignored results, renewal while waiting, and loop reuse."""
        report = self._run_case("--exercise")
        self.assertEqual(["slow", "ok", "fail", "ignored"], report["executed"])
        self.assertEqual(0, report["pending"])
        self.assertEqual(2, report["reopened_loops"])

    def test_worker_service_lifecycle(self) -> None:
        """Exercise real service discovery, native spawned children and group stop."""
        report = self._run_case("--worker")
        self.assertEqual(2, len(report["worker_pids"]))
        self.assertEqual(0, report["stop_status"])
        self.assertEqual(4, report["runtime_replacements"])
        self.assertEqual(1, report["startup_failure_status"])
        self.assertEqual(0, report["forced_stop_status"])
        self.assertEqual(2, report["terminal_stops"])

    def test_scheduler_service_lifecycle(self) -> None:
        """Real CLI sources, one-time cancellation and native delayed retry."""
        report = self._run_case("--scheduler")
        self.assertEqual(1, report["once"])
        self.assertEqual(0, report["cancelled"])
        self.assertEqual(2, report["retry_attempts"])
        self.assertEqual([0, 0], report["stop_statuses"])

    def test_scheduler_failure_recovery_and_drain(self) -> None:
        """Pause real facilities to fail publish/post_send in the same service."""
        report = self._run_case("--scheduler-faults")
        self.assertEqual(3, report["queued"])
        self.assertEqual(0, report["stop_status"])
        self.assertEqual(1, report["source_closes"])

    def test_existing_publisher_lifecycles(self) -> None:
        """Existing services and App commands publish without their own startup."""
        report = self._run_case("--publishers")
        self.assertEqual(9, report["queued"])
        self.assertTrue(report["web_closed"])

    def test_online_broadcast(self) -> None:
        """Two native workers share durable/broadcast concurrency and close normally."""
        report = self._run_case("--broadcast")
        self.assertEqual(2, report["broadcast_copies"])
        self.assertEqual(1, report["maximum_per_process"])
        self.assertTrue(report["slow_consumer_logged"])

    def test_lost_confirmations_and_result_failures(self) -> None:
        """Drop real NATS replies and deny real Redis writes, not mocked errors."""
        report = self._run_case("--confirmation-faults")
        self.assertEqual(1, report["dropped_pubacks"])
        self.assertEqual(3, report["dropped_acks"])
        self.assertEqual(5, report["executions"])
        self.assertEqual(0, report["remaining_messages"])

    def test_resource_races_backlog_and_capacity(self) -> None:
        """Two real processes initialize one queue; conflicts never alter backlog."""
        report = self._run_case("--resource-faults")
        self.assertEqual(2, report["creators"])
        self.assertEqual(2, report["rejected_conflicts"])
        self.assertGreater(report["retained_messages"], 0)

    def test_full_broker_tls_failure_cleanup(self) -> None:
        """The real broker preserves certificate errors within its cleanup budget."""
        report = self._run_case("--tls-faults")
        self.assertEqual(2, report["certificate_failures"])
        self.assertLess(report["maximum_seconds"], 7)

    def test_existing_cache_and_settings_with_shared_redis_options(self) -> None:
        """Run existing real checks with only their configuration isolated."""
        report = self._run_case("--shared-redis")
        self.assertGreater(report["checks"], 2)

    def test_scheduler_stop_deadline(self) -> None:
        """An unfinished post_send is handled by the same single stop command."""
        report = self._run_case("--scheduler-force-stop")
        self.assertEqual(0, report["stop_status"])
        self.assertTrue(report["forced"])

    def test_prefetch_and_merger_are_bounded(self) -> None:
        """Native admission and per-source buffering remain distinct limits."""
        report = self._run_case("--prefetch")
        self.assertEqual([2, 2], report["maximum_executions"])
        self.assertEqual([20, 20], report["completed"])

    def _run_case(self, mode: str) -> dict[str, Any]:
        """Each serial case owns real facilities and a fresh configured process."""
        with tempfile.TemporaryDirectory(prefix="oldman-taskiq-transport-", dir="/tmp") as directory:
            root = Path(directory)
            ports: list[int] = []
            for _ in range(2):
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1", 0))
                    ports.append(probe.getsockname()[1])
            nats_port, redis_port = ports
            nats_config = root / "nats.conf"
            nats_config.write_text(
                f'listen: "127.0.0.1:{nats_port}"\njetstream {{ store_dir: "{root / "jetstream"}", max_file_store: 134217728 }}\n',
                encoding="utf-8",
            )
            processes: list[subprocess.Popen[bytes]] = []
            with (root / "servers.log").open("wb") as log:
                try:
                    processes.append(subprocess.Popen([str(NATS_SERVER), "-c", str(nats_config)], stdout=log, stderr=log))
                    processes.append(subprocess.Popen([
                        str(REDIS_SERVER), "--bind", "127.0.0.1", "--port", str(redis_port), "--dir", directory,
                        "--save", "", "--appendonly", "no", "--maxmemory", "128mb", "--maxmemory-policy", "noeviction",
                    ], stdout=log, stderr=log))
                    (root / "servers.json").write_text(json.dumps([process.pid for process in processes]))
                    deadline = time.monotonic() + 5
                    for port in ports:
                        while True:
                            try:
                                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                                    break
                            except OSError:
                                if time.monotonic() >= deadline or any(p.poll() is not None for p in processes):
                                    self.fail((root / "servers.log").read_text())
                                time.sleep(0.02)
                    result = subprocess.run(
                        [sys.executable, "-m", "tests.test_oldman_distributed_tasks", mode, str(nats_port), str(redis_port), directory],
                        cwd=ROOT, capture_output=True, text=True, timeout=80,
                    )
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    return json.loads(result.stdout.strip().splitlines()[-1])
                finally:
                    for process in processes:
                        if process.poll() is None:
                            os.kill(process.pid, signal.SIGCONT)  # A failed fault probe must not leave an owned facility paused.
                            process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                            self.fail("Test facility needed forced cleanup; normal close did not complete")


def exercise(nats_port: int, redis_port: int, root: Path) -> None:
    """A subprocess owns one Settings identity; no production reset is needed."""
    from oldman import conf
    from oldman.conf.schemas import DefaultSettings

    settings = DefaultSettings.model_validate({
        "nats": {"DEFAULT": {"nats_url": f"nats://127.0.0.1:{nats_port}"}},
        "redis": {"DEFAULT": {"redis_url": f"redis://127.0.0.1:{redis_port}/0?decode_responses=true"}},
        "taskiq": {
            "enabled": True, "namespace": "Transport_Test", "consume_queues": ["empty", "busy"],
            "max_async_tasks": 1, "max_prefetch": 0, "ack_wait": 0.3,
            "publish_timeout": 1, "ack_timeout": 1, "result_ex_time": 30,
        },
    })
    conf._publish_settings(settings)
    from redis.asyncio import Redis
    from redis.exceptions import ConnectionError as RedisConnectionError
    from taskiq import TaskiqEvents
    from taskiq.exceptions import SendTaskError

    from oldman.tasks.distributed import broker, schedule_source
    from oldman.tasks.distributed.broker import TaskiqBroker
    from oldman.tasks.distributed.receiver import RenewingReceiver

    executed: list[str] = []

    async def job(kind: str) -> Any:
        """Record actual execution separately from results that could overwrite."""
        executed.append(kind)
        if kind == "slow":
            await asyncio.sleep(1.1)
        if kind == "fail":
            raise ValueError("预期失败")
        if kind == "ignored":
            return object()
        return {"名称": kind}

    task = broker.task(task_name="transport.job", queue_name="busy")(job)

    async def run() -> dict[str, Any]:
        """The publisher cannot create consumers; the Worker performs execution."""
        try:
            await task.kiq("too-early")
        except SendTaskError as error:
            assert isinstance(error.__cause__, RuntimeError)
        else:
            raise AssertionError("Publication before startup must fail")
        worker = TaskiqBroker(settings)
        worker.is_worker_process = True
        worker.task(task_name="transport.job", queue_name="busy")(job)
        finish = asyncio.Event()
        listener: asyncio.Task[None] | None = None
        try:
            await broker.startup()
            assert (await broker.js.stream_info(broker.stream_name)).state.consumer_count == 0
            jobs = [await task.kiq(kind) for kind in ("slow", "ok", "fail")]
            ignored = await task.kicker().with_labels(ignore_result=True).kiq("ignored")
            await worker.startup()
            receiver = RenewingReceiver(worker, max_async_tasks=1, max_prefetch=0, run_startup=False)
            listener = asyncio.create_task(receiver.listen(finish))
            async with asyncio.timeout(8):
                results = [await item.wait_result(timeout=5) for item in jobs]
                while "ignored" not in executed or worker._deliveries:
                    await asyncio.sleep(0.02)
            assert results[0].return_value == {"名称": "slow"}
            assert results[1].return_value == {"名称": "ok"}
            assert results[2].is_err and "预期失败" in str(results[2].error)
            assert not await ignored.is_ready()
            assert executed == ["slow", "ok", "fail", "ignored"], executed
            info = await broker.js.consumer_info(broker.stream_name, "workers_busy")
            assert info.num_ack_pending == 0 and info.num_redelivered == 0, info
            assert (await broker.js.stream_info(broker.stream_name)).state.messages == 0
            async with Redis(connection_pool=broker.results.redis_pool) as redis:
                keys = await redis.keys("oldman_taskiq_Transport_Test_results*")
                assert len(keys) == 3 and all(isinstance(key, bytes) for key in keys), keys
                assert 0 < await redis.ttl(keys[0]) <= 30
            scheduled = await task.schedule_by_time(
                schedule_source, datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=1), "ok",
            )
            records = await schedule_source.get_schedules()
            matching = [item for item in records if item.schedule_id == scheduled.schedule_id]
            assert len(matching) == 1 and matching[0].task_id
            stable_id = matching[0].task_id
            await schedule_source.add_schedule(matching[0])
            records = await schedule_source.get_schedules()
            assert all(item.task_id == stable_id for item in records if item.schedule_id == scheduled.schedule_id)
            await schedule_source.delete_schedule(scheduled.schedule_id)
            return {"executed": executed, "pending": info.num_ack_pending}
        finally:
            finish.set()
            if listener is not None:
                await asyncio.wait_for(listener, 5)
            await worker.shutdown()
            await broker.shutdown()
            assert worker.client.is_closed and broker.client.is_closed
            assert not worker._deliveries and not worker._subscriptions
            await asyncio.sleep(0)
            assert not (asyncio.all_tasks() - {asyncio.current_task()}), asyncio.all_tasks()

    report = asyncio.run(run())

    async def reopen() -> None:
        """The same public objects can reopen after a clean close on another loop."""
        async with broker:
            assert schedule_source is broker.schedule_source
            assert broker.client.is_connected
        assert broker.results.closed and broker.client.is_closed

    asyncio.run(reopen())
    asyncio.run(reopen())

    async def failure_cleanup() -> None:
        """A partial startup and a failed native hook both close independent pools."""
        raw = settings.model_dump()
        raw["redis"]["DEFAULT"]["redis_url"] = f"unix://{root / 'missing.sock'}"
        raw["redis"]["DEFAULT"]["retry_attempts"] = 0
        broken_start = TaskiqBroker(DefaultSettings.model_validate(raw))
        try:
            await broken_start.startup()
        except RedisConnectionError:
            pass
        else:
            raise AssertionError("An unavailable result/schedule facility must fail startup")
        assert broken_start.client.is_closed and broken_start.results.closed
        assert broken_start.schedule_source._closed

        failed_hook = TaskiqBroker(settings)

        @failed_hook.on_event(TaskiqEvents.CLIENT_SHUTDOWN)
        async def fail_shutdown(state: Any) -> None:
            """An application hook failure must not leak framework-owned resources."""
            raise ValueError("expected shutdown hook failure")

        await failed_hook.startup()
        try:
            await failed_hook.shutdown()
        except ExceptionGroup as error:
            assert "expected shutdown hook failure" in str(error.exceptions[0])
        else:
            raise AssertionError("The real shutdown failure must propagate")
        assert failed_hook.client.is_closed and failed_hook.results.closed and failed_hook.schedule_source._closed
        try:
            await failed_hook.startup()
        except RuntimeError as error:
            assert "cleanup failed" in str(error)
        else:
            raise AssertionError("An incompletely closed lifecycle must not claim safe reuse")
        failed_context = TaskiqBroker(settings)
        failed_context.on_event(TaskiqEvents.CLIENT_SHUTDOWN)(fail_shutdown)
        try:
            async with failed_context:
                raise LookupError("original context body failure")
        except LookupError as error:
            assert str(error) == "original context body failure"
        else:
            raise AssertionError("Context cleanup must not hide the body exception")
        assert failed_context.client.is_closed and failed_context.results.closed and failed_context.schedule_source._closed
        await asyncio.sleep(0)
        assert not (asyncio.all_tasks() - {asyncio.current_task()})

    asyncio.run(failure_cleanup())
    report["reopened_loops"] = 2
    print(json.dumps(report, ensure_ascii=False))


def exercise_worker(nats_port: int, redis_port: int, root: Path) -> None:
    """Create an isolated real project, not a mocked Application or process tree."""
    project = root / "project"
    sources = {
        "pyproject.toml": '[project]\nname="taskiq-worker-probe"\nversion="0"\n',
        "config/__init__.py": "",
        "config/schemas.py": "from oldman.conf import DefaultSettings\nclass Settings(DefaultSettings):\n    pass\n",
        "services/__init__.py": "",
        "services/mail_jobs.py": """
            from oldman.runtime import TaskiqWorkerApplication
            class MailJobs(TaskiqWorkerApplication):
                pass
        """,
        "job_app/__init__.py": "",
        "job_app/apps.py": """
            from oldman.apps import AppConfig
            class Config(AppConfig):
                label = "jobs"
                display_name = "Jobs"
            app = Config()
        """,
        "job_app/views.py": "raise RuntimeError('Worker must never load Web views')\n",
        "job_app/tasks.py": """
            import asyncio
            import os
            import time
            from oldman.providers.redis import redis_client
            from oldman.tasks.distributed import broker

            @broker.task(queue_name="busy")
            async def report_pid() -> int:
                client = await redis_client.using("DEFAULT").async_get_conn()
                await client.rpush("worker-probe:executed", str(os.getpid()))
                await asyncio.sleep(0.5)
                return os.getpid()

            @broker.task(queue_name="busy")
            async def crash_once() -> int:
                client = await redis_client.using("DEFAULT").async_get_conn()
                attempts = await client.incr("worker-probe:crash-attempts")
                if attempts == 1:
                    os._exit(67)  # Crash after starting, before a result or ACK.
                return attempts

            @broker.task(queue_name="busy")
            async def stuck() -> None:
                client = await redis_client.using("DEFAULT").async_get_conn()
                await client.set("worker-probe:stuck", str(os.getpid()))
                time.sleep(60)  # Deliberately block the loop to exercise the stop deadline.
        """,
    }
    for relative, body in sources.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body), encoding="utf-8")
    data = project / "data"
    data.mkdir()
    config = {
        "apps": ["job_app"], "logging": {"dir": str(project / "logs")}, "process": {"pid_dir": str(project / "pids")},
        "nats": {"DEFAULT": {"nats_url": f"nats://127.0.0.1:{nats_port}"}},
        "redis": {"DEFAULT": {"redis_url": f"redis://127.0.0.1:{redis_port}/0"}},
        "taskiq": {"enabled": True, "namespace": "Worker_Probe", "workers": 2, "max_async_tasks": 1,
                   "consume_queues": ["empty", "busy"], "startup_timeout": 4, "startup_attempts": 2,
                   "shutdown_timeout": 2, "stop_timeout": 6, "ack_wait": 1},
    }
    (data / "mail_jobs_settings.yaml").write_text(json.dumps(config), encoding="utf-8")
    environment = {**os.environ, "PROJECT_ROOT": str(project), "PYTHONPATH": os.pathsep.join((str(project), str(ROOT)))}
    command = [str(Path(sys.executable).parent / "oldman"), "mail_jobs"]
    with (root / "worker.log").open("w+") as log:
        process = subprocess.Popen([*command, "start"], cwd=project, env=environment, stdout=log, stderr=log, start_new_session=True)
        try:
            # The publisher is a separate process; only its selected service is bootstrapped.
            publish = subprocess.run([sys.executable, "-c", textwrap.dedent("""
                import asyncio, json
                from oldman import bootstrap_service
                context = bootstrap_service('mail_jobs')
                context.apps.load_tasks()
                from job_app.tasks import report_pid
                from oldman.tasks.distributed import broker
                async def main():
                    async with broker:
                        jobs = [await report_pid.kiq() for _ in range(6)]
                        results = [await job.wait_result(timeout=15) for job in jobs]
                        print(json.dumps(sorted(set(result.return_value for result in results))))
                asyncio.run(main())
            """)], cwd=project, env=environment, capture_output=True, text=True, timeout=25)
            log.flush()
            assert publish.returncode == 0, publish.stdout + publish.stderr + (root / "worker.log").read_text()
            worker_pids = json.loads(publish.stdout.strip().splitlines()[-1])
            assert len(worker_pids) == 2 and all(os.getpgid(pid) == process.pid for pid in worker_pids), worker_pids
            replacements = 0

            def child_pids() -> set[int]:
                """Observe native spawn children, excluding Python's resource tracker."""
                children = Path(f"/proc/{process.pid}/task/{process.pid}/children").read_text().split()
                pids = set()
                for value in children:
                    try:
                        if b"spawn_main" in Path(f"/proc/{value}/cmdline").read_bytes():
                            pids.add(int(value))
                    except FileNotFoundError:
                        pass
                return pids

            for _ in range(4):
                before = child_pids()
                assert len(before) == 2, before
                os.kill(min(before), signal.SIGKILL)
                deadline = time.monotonic() + 6
                while True:
                    current = child_pids()
                    if len(current) == 2 and current != before:
                        replacements += 1
                        break
                    assert process.poll() is None and time.monotonic() < deadline, (root / "worker.log").read_text()
                    time.sleep(0.1)
            # Observing a new PID alone does not prove that the replacement can
            # execute tasks; confirm real work before testing normal shutdown.
            recovered = subprocess.run(publish.args, cwd=project, env=environment, capture_output=True, text=True, timeout=25)
            assert recovered.returncode == 0, recovered.stdout + recovered.stderr + (root / "worker.log").read_text()
            assert set(json.loads(recovered.stdout.strip().splitlines()[-1])) == child_pids()
            redelivered = subprocess.run([sys.executable, "-c", textwrap.dedent("""
                import asyncio
                from oldman import bootstrap_service
                context = bootstrap_service('mail_jobs')
                context.apps.load_tasks()
                from job_app.tasks import crash_once
                from oldman.tasks.distributed import broker
                async def main():
                    async with broker:
                        task = await crash_once.kiq()
                        result = await task.wait_result(timeout=10)
                        assert result.return_value == 2
                        async with asyncio.timeout(2):
                            while (await broker.js.stream_info(broker.stream_name)).state.messages:
                                await asyncio.sleep(0.02)
                asyncio.run(main())
            """)], cwd=project, env=environment, capture_output=True, text=True, timeout=15)
            assert redelivered.returncode == 0, redelivered.stdout + redelivered.stderr
            # restart must stop the entire old group before the new process can
            # claim the same PID file. Keep ownership of both actual processes.
            previous = process
            process = subprocess.Popen([*command, "restart"], cwd=project, env=environment, stdout=log, stderr=log, start_new_session=True)
            previous.wait(timeout=12)
            assert previous.returncode == 0
            deadline = time.monotonic() + 8
            identity_path = project / "pids/mail_jobs.pid"
            while not identity_path.exists() or identity_path.read_text() != str(process.pid):
                assert process.poll() is None and time.monotonic() < deadline, (root / "worker.log").read_text()
                time.sleep(0.05)
            restarted = subprocess.run(publish.args, cwd=project, env=environment, capture_output=True, text=True, timeout=25)
            assert restarted.returncode == 0, restarted.stdout + restarted.stderr + (root / "worker.log").read_text()
            assert set(json.loads(restarted.stdout.strip().splitlines()[-1])) == child_pids()
            stopped = subprocess.run([*command, "stop"], cwd=project, env=environment, capture_output=True, text=True, timeout=15)
            assert stopped.returncode == 0, stopped.stdout + stopped.stderr + (root / "worker.log").read_text()
            process.wait(timeout=5)
            assert process.returncode == 0, (root / "worker.log").read_text()
            from oldman.processes.subprocess import _live_process_group_pids

            assert not _live_process_group_pids(process.pid)
            assert not (project / "pids/mail_jobs.pid").exists()
            assert not (project / "pids/mail_jobs.taskiq.json").exists()
            assert "Traceback" not in (root / "worker.log").read_text(), (root / "worker.log").read_text()
            report = {"worker_pids": worker_pids, "stop_status": stopped.returncode, "runtime_replacements": replacements}
        finally:
            if process.poll() is None:
                # Only test-owned processes are a fallback target, never a pass criterion.
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)

    report["terminal_stops"] = exercise_worker_terminal(command, project, environment)

    # Initial failure is bounded and exits nonzero, unlike runtime replacements.
    failed_config = {**config, "nats": {"DEFAULT": {"nats_url": "nats://127.0.0.1:1"}}}
    failed_config["taskiq"] = {**config["taskiq"], "startup_timeout": 1.5, "shutdown_timeout": 0.5, "stop_timeout": 2}
    (data / "mail_jobs_settings.yaml").write_text(json.dumps(failed_config), encoding="utf-8")
    failed = subprocess.run([*command, "start"], cwd=project, env=environment, capture_output=True, text=True, timeout=15, start_new_session=True)
    assert failed.returncode == 1 and "failed all 2 startup attempts" in failed.stdout + failed.stderr, f"exit={failed.returncode}\n" + failed.stdout + failed.stderr
    report["startup_failure_status"] = failed.returncode

    # A fresh namespace avoids consuming any deliberately stuck previous delivery.
    config["taskiq"]["namespace"] = "Worker_Stop_Probe"
    config["taskiq"]["stop_timeout"] = 2
    (data / "mail_jobs_settings.yaml").write_text(json.dumps(config), encoding="utf-8")
    with (root / "stuck-worker.log").open("w+") as log:
        process = subprocess.Popen([*command, "start"], cwd=project, env=environment, stdout=log, stderr=log, start_new_session=True)
        try:
            posted = subprocess.run([sys.executable, "-c", textwrap.dedent("""
                import asyncio
                from oldman import bootstrap_service
                context = bootstrap_service('mail_jobs')
                context.apps.load_tasks()
                from job_app.tasks import stuck
                from oldman.tasks.distributed import broker
                from redis.asyncio import Redis
                async def main():
                    async with broker:
                        await stuck.kiq()
                        async with Redis(connection_pool=broker.results.redis_pool) as client:
                            async with asyncio.timeout(10):
                                while not await client.get('worker-probe:stuck'):
                                    await asyncio.sleep(0.05)
                asyncio.run(main())
            """)], cwd=project, env=environment, capture_output=True, text=True, timeout=15)
            assert posted.returncode == 0, posted.stdout + posted.stderr + (root / "stuck-worker.log").read_text()
            started = time.monotonic()
            stopped = subprocess.run([*command, "stop"], cwd=project, env=environment, capture_output=True, text=True, timeout=8)
            assert stopped.returncode == 0, stopped.stdout + stopped.stderr + (root / "stuck-worker.log").read_text()
            assert 2 <= time.monotonic() - started < 6
            process.wait(timeout=3)
            assert process.returncode == -signal.SIGKILL
            from oldman.processes.subprocess import _live_process_group_pids

            assert not _live_process_group_pids(process.pid)
            report["forced_stop_status"] = stopped.returncode
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
    print(json.dumps(report))


def exercise_worker_terminal(command: list[str], project: Path, environment: dict[str, str]) -> int:
    """Type Ctrl+C into real zsh terminals, with and without shell job control."""
    from dataclasses import replace

    from oldman.processes.subprocess import _live_process_group_pids
    from oldman.runtime._taskiq_process import GroupIdentity, stop_process_group
    from tests.test_oldman_logging_tty_runtime import _PtyReader

    for job_control in (True, False):
        shell_pid, terminal = pty.fork()
        if shell_pid == 0:
            os.chdir(project)
            os.execve("/usr/bin/zsh", ["zsh", "-f", "-i"], environment)
        reader = _PtyReader(terminal)
        owner: GroupIdentity | None = None
        reaped = False
        try:
            prefix = "" if job_control else "unsetopt monitor\n"
            os.write(terminal, (prefix + shlex.join([*command, "start"]) + "\n").encode())
            deadline = time.monotonic() + 10
            while "All 2 Taskiq worker processes are ready" not in reader.partial_output:
                assert time.monotonic() < deadline, reader.partial_output
                time.sleep(0.05)
            owner = GroupIdentity.from_json((project / "pids/mail_jobs.taskiq.json").read_text())
            assert os.tcgetpgrp(terminal) == owner.pgid != shell_pid
            # A stale record must not signal either the service or its shell.
            try:
                stop_process_group(replace(owner, start_ticks=owner.start_ticks + 1), 1)
            except RuntimeError as error:
                assert "stale" in str(error)
            else:
                raise AssertionError("A stale identity must be rejected")
            os.write(terminal, b"\x03")
            deadline = time.monotonic() + 10
            while _live_process_group_pids(owner.pgid):
                assert time.monotonic() < deadline, reader.partial_output
                time.sleep(0.05)
            os.write(terminal, b"print -r -- __OLDMAN_STATUS_${?}__\n")
            deadline = time.monotonic() + 3
            while "__OLDMAN_STATUS_0__" not in reader.partial_output:
                assert time.monotonic() < deadline, reader.partial_output
                time.sleep(0.05)
            assert os.tcgetpgrp(terminal) == shell_pid
            os.write(terminal, b"exit\n")
            deadline = time.monotonic() + 3
            while True:
                ended, status = os.waitpid(shell_pid, os.WNOHANG)
                if ended:
                    reaped = True
                    assert os.waitstatus_to_exitcode(status) == 0
                    break
                assert time.monotonic() < deadline, reader.partial_output
                time.sleep(0.05)
        finally:
            if owner is not None and _live_process_group_pids(owner.pgid):
                os.killpg(owner.pgid, signal.SIGKILL)
            if not reaped:
                os.kill(shell_pid, signal.SIGKILL)
                os.waitpid(shell_pid, 0)
            output = reader.finish()
        assert "Traceback" not in output and "Taskiq service stop failed" not in output, output
    return 2


def exercise_scheduler(nats_port: int, redis_port: int, root: Path) -> None:
    """Use the shipped service classes and actual CLI, never a Scheduler mock."""
    project = root / "project"
    sources = {
        "pyproject.toml": '[project]\nname="taskiq-scheduler-probe"\nversion="0"\n',
        "config/__init__.py": "",
        "config/schemas.py": "from oldman.conf import DefaultSettings\nclass Settings(DefaultSettings):\n    pass\n",
        "services/__init__.py": "",
        "services/task_worker.py": "from oldman.runtime import TaskiqWorkerApplication\nclass Worker(TaskiqWorkerApplication):\n    pass\n",
        "services/task_scheduler.py": "from oldman.runtime import TaskiqSchedulerApplication\nclass Scheduler(TaskiqSchedulerApplication):\n    pass\n",
        "job_app/__init__.py": "",
        "job_app/apps.py": "from oldman.apps import AppConfig\nclass Config(AppConfig):\n    label='jobs'\n    display_name='Jobs'\napp=Config()\n",
        "job_app/views.py": "raise RuntimeError('Task services must not import views')\n",
        "job_app/tasks.py": """
            from oldman.providers.redis import redis_client
            from oldman.tasks.distributed import broker

            @broker.task(queue_name="busy", schedule=[
                {"interval": 2, "args": ["fixed_interval"]},
                {"cron": "* * * * *", "args": ["fixed_cron"]},
            ])
            async def record(kind: str) -> str:
                client = await redis_client.using("DEFAULT").async_get_conn()
                await client.rpush("scheduler-probe:events", kind)
                return kind

            @broker.task(queue_name="busy", retry_on_error=True, delay=1)
            async def retry_once() -> int:
                client = await redis_client.using("DEFAULT").async_get_conn()
                count = await client.incr("scheduler-probe:attempts")
                if count == 1:
                    raise ValueError("Expected first-attempt failure")
                return count
        """,
    }
    for relative, body in sources.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body), encoding="utf-8")
    data = project / "data"
    data.mkdir()
    config = {
        "apps": ["job_app"], "logging": {"dir": str(project / "logs")}, "process": {"pid_dir": str(project / "pids")},
        "nats": {"DEFAULT": {"nats_url": f"nats://127.0.0.1:{nats_port}"}},
        "redis": {"DEFAULT": {"redis_url": f"redis://127.0.0.1:{redis_port}/0"}},
        "taskiq": {"enabled": True, "namespace": "Scheduler_Probe", "workers": 1, "max_async_tasks": 1,
                   "consume_queues": ["busy"], "startup_timeout": 4, "startup_attempts": 2,
                   "shutdown_timeout": 2, "stop_timeout": 6, "ack_wait": 1, "schedule_update_interval": 1},
    }
    for service in ("task_worker", "task_scheduler"):
        (data / f"{service}_settings.yaml").write_text(json.dumps(config), encoding="utf-8")
    environment = {**os.environ, "PROJECT_ROOT": str(project), "PYTHONPATH": os.pathsep.join((str(project), str(ROOT)))}
    executable = str(Path(sys.executable).parent / "oldman")
    processes: list[subprocess.Popen[str]] = []
    with (root / "scheduler.log").open("w+") as log:
        try:
            for service in ("task_worker", "task_scheduler"):
                processes.append(subprocess.Popen([executable, service, "start"], cwd=project, env=environment,
                                                  stdout=log, stderr=log, text=True, start_new_session=True))
            completed = subprocess.run([sys.executable, "-c", textwrap.dedent("""
                import asyncio, datetime, json
                from oldman import bootstrap_service
                context = bootstrap_service('task_worker')
                context.apps.load_tasks()
                from job_app.tasks import record, retry_once
                from oldman.tasks.distributed import broker, schedule_source
                from redis.asyncio import Redis
                async def main():
                    async with broker:
                        now = datetime.datetime.now(datetime.UTC)
                        await record.schedule_by_time(schedule_source, now, 'once')
                        cancelled = await record.schedule_by_time(schedule_source, now + datetime.timedelta(seconds=30), 'cancelled')
                        await schedule_source.delete_schedule(cancelled.schedule_id)
                        interval = await record.schedule_by_interval(schedule_source, 2, 'dynamic_interval')
                        cron = await record.schedule_by_cron(schedule_source, '* * * * *', 'dynamic_cron')
                        retry = await retry_once.kiq()
                        async with Redis(connection_pool=broker.results.redis_pool) as client:
                            async with asyncio.timeout(15):
                                while int(await client.get('scheduler-probe:attempts') or 0) < 1:
                                    await asyncio.sleep(0.05)
                                # The first failed attempt is not a final result.
                                assert not await retry.is_ready()
                                result = await retry.wait_result(timeout=12)
                                assert not result.is_err and result.return_value == 2
                                while True:
                                    events = [value.decode() for value in await client.lrange('scheduler-probe:events', 0, -1)]
                                    if (events.count('once') == 1 and events.count('fixed_interval') >= 2
                                        and events.count('dynamic_interval') >= 2 and 'fixed_cron' in events and 'dynamic_cron' in events):
                                        break
                                    await asyncio.sleep(0.1)
                                await schedule_source.delete_schedule(interval.schedule_id)
                                await schedule_source.delete_schedule(cron.schedule_id)
                                assert 'cancelled' not in events
                                remaining = await schedule_source.get_schedules()
                                assert not remaining, remaining
                                print(json.dumps({'once': events.count('once'), 'cancelled': events.count('cancelled'), 'retry_attempts': result.return_value}))
                asyncio.run(main())
            """)], cwd=project, env=environment, capture_output=True, text=True, timeout=25)
            assert completed.returncode == 0, completed.stdout + completed.stderr + (root / "scheduler.log").read_text()
            report = json.loads(completed.stdout.strip().splitlines()[-1])
            statuses = []
            for service, process in reversed(list(zip(("task_worker", "task_scheduler"), processes, strict=True))):
                stopped = subprocess.run([executable, service, "stop"], cwd=project, env=environment, capture_output=True, text=True, timeout=10)
                assert stopped.returncode == 0, stopped.stdout + stopped.stderr + (root / "scheduler.log").read_text()
                process.wait(timeout=5)
                assert process.returncode == 0, (root / "scheduler.log").read_text()
                from oldman.processes.subprocess import _live_process_group_pids

                assert not _live_process_group_pids(process.pid)
                statuses.append(stopped.returncode)
            report["stop_statuses"] = statuses
            output = (root / "scheduler.log").read_text()
            assert "Expected first-attempt failure" in output  # A real exception, not a fabricated result.
            assert "Task exception was never retrieved" not in output and "Event loop stopped before" not in output, output
        finally:
            for process in processes:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
    print(json.dumps(report))


def exercise_scheduler_faults(nats_port: int, redis_port: int, root: Path, *, force_stop: bool = False) -> None:
    """Instrument only fault timing; real library calls must produce the errors."""
    project = root / "project"
    sources = {
        "pyproject.toml": '[project]\nname="taskiq-scheduler-faults"\nversion="0"\n',
        "config/__init__.py": "",
        "config/schemas.py": "from oldman.conf import DefaultSettings\nclass Settings(DefaultSettings):\n    pass\n",
        "services/__init__.py": "",
        "services/timer.py": "from oldman.runtime import TaskiqSchedulerApplication\nclass Timer(TaskiqSchedulerApplication):\n    pass\n",
        "job_app/__init__.py": "",
        "job_app/apps.py": "from oldman.apps import AppConfig\nclass Config(AppConfig):\n    label='jobs'\n    display_name='Jobs'\napp=Config()\n",
        "job_app/tasks.py": """
            import asyncio, json, os, signal
            from pathlib import Path
            from taskiq import TaskiqEvents
            from oldman.tasks.distributed import broker, schedule_source

            @broker.task()
            async def job(kind: str) -> str:
                return kind

            @broker.on_event(TaskiqEvents.CLIENT_STARTUP)
            async def setup_faults(state):
                if not broker.is_scheduler_process:
                    return
                root = Path(os.environ['TASKIQ_PROBE_ROOT'])
                nats_pid, redis_pid = json.loads((root / 'servers.json').read_text())
                original_kick = broker.kick
                original_post = schedule_source.post_send
                original_close = schedule_source.shutdown
                native_ids = []
                async def kick(message):
                    if message.labels.get('probe') == 'nats' and not (root / 'nats-failed').exists():
                        (root / 'nats-failed').write_text('attempted')
                        os.kill(nats_pid, signal.SIGSTOP)
                        try:
                            return await original_kick(message)
                        finally:
                            os.kill(nats_pid, signal.SIGCONT)
                    return await original_kick(message)
                async def post(task):
                    if task.args == ['redis'] and not (root / 'redis-failed').exists():
                        (root / 'redis-failed').write_text('attempted')
                        os.kill(redis_pid, signal.SIGSTOP)
                        try:
                            return await original_post(task)
                        finally:
                            os.kill(redis_pid, signal.SIGCONT)
                    if task.args == ['wait']:
                        (root / 'post-waiting').write_text('started')
                        while not (root / 'release-post').exists():
                            await asyncio.sleep(0.05)
                    await original_post(task)
                    native_ids.append(task.schedule_id)
                    (root / 'post-complete.json').write_text(json.dumps(native_ids))
                async def close():
                    path = root / 'source-closes'
                    path.write_text(str(int(path.read_text()) + 1 if path.exists() else 1))
                    await original_close()
                broker.kick = kick
                schedule_source.post_send = post
                schedule_source.shutdown = close
        """,
    }
    for relative, body in sources.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body), encoding="utf-8")
    data = project / "data"
    data.mkdir()
    config = {
        "apps": ["job_app"], "logging": {"dir": str(project / "logs")}, "process": {"pid_dir": str(project / "pids")},
        "nats": {"DEFAULT": {"nats_url": f"nats://127.0.0.1:{nats_port}"}},
        "redis": {"DEFAULT": {"redis_url": f"redis://127.0.0.1:{redis_port}/0", "connection_socket_timeout": 0.2, "retry_attempts": 0}},
        "taskiq": {"enabled": True, "namespace": "Scheduler_Faults", "startup_timeout": 4, "startup_attempts": 1,
                   "publish_timeout": 0.2, "shutdown_timeout": 2, "stop_timeout": 6, "schedule_update_interval": 30},
    }
    if force_stop:
        config["taskiq"]["stop_timeout"] = 2
    (data / "timer_settings.yaml").write_text(json.dumps(config), encoding="utf-8")
    environment = {**os.environ, "PROJECT_ROOT": str(project), "TASKIQ_PROBE_ROOT": str(root),
                   "PYTHONPATH": os.pathsep.join((str(project), str(ROOT)))}
    executable = str(Path(sys.executable).parent / "oldman")
    prepare = subprocess.run([sys.executable, "-c", textwrap.dedent("""
        import asyncio, datetime, json
        from oldman import bootstrap_service
        context = bootstrap_service('timer')
        context.apps.load_tasks()
        from job_app.tasks import job
        from oldman.tasks.distributed import broker, schedule_source
        async def main():
            async with broker:
                now = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=1)
                for kind in ('nats', 'redis', 'wait'):
                    await job.kicker().with_labels(probe=kind).schedule_by_time(schedule_source, now, kind)
        asyncio.run(main())
    """)], cwd=project, env=environment, capture_output=True, text=True, timeout=10)
    assert prepare.returncode == 0, prepare.stdout + prepare.stderr
    process: subprocess.Popen[str] | None = None
    stopped: subprocess.Popen[str] | None = None
    with (root / "scheduler.log").open("w+") as log:
        try:
            process = subprocess.Popen([executable, "timer", "start"], cwd=project, env=environment,
                                       stdout=log, stderr=log, text=True, start_new_session=True)
            deadline = time.monotonic() + 12
            while True:
                path = root / "post-complete.json"
                if path.exists() and len(json.loads(path.read_text())) == 2 and (root / "post-waiting").exists():
                    break
                assert process.poll() is None and time.monotonic() < deadline, (root / "scheduler.log").read_text()
                time.sleep(0.05)
            # Same PID recovered both failures before the 30-second source refresh.
            stopped = subprocess.Popen([executable, "timer", "stop"], cwd=project, env=environment,
                                       stdout=log, stderr=log, text=True)
            time.sleep(0.6)
            assert stopped.poll() is None and process.poll() is None, (root / "scheduler.log").read_text()
            if force_stop:
                stopped.wait(timeout=6)
                process.wait(timeout=3)
                assert stopped.returncode == 0 and process.returncode == -signal.SIGKILL
                from oldman.processes.subprocess import _live_process_group_pids

                assert not _live_process_group_pids(process.pid)
                print(json.dumps({"stop_status": 0, "forced": True}))
                return
            (root / "release-post").write_text("release")
            stopped.wait(timeout=8)
            process.wait(timeout=3)
            assert stopped.returncode == process.returncode == 0, (root / "scheduler.log").read_text()
            assert len(json.loads((root / "post-complete.json").read_text())) == 3
            assert (root / "source-closes").read_text() == "1"
            check = subprocess.run([sys.executable, "-c", textwrap.dedent("""
                import asyncio, json
                from oldman import bootstrap_service
                bootstrap_service('timer')
                from oldman.tasks.distributed import broker, schedule_source
                async def main():
                    async with broker:
                        assert not await schedule_source.get_schedules()
                        count = (await broker.js.stream_info(broker.stream_name)).state.messages
                        assert count == 3, count
                        print(json.dumps({'queued': count, 'stop_status': 0, 'source_closes': 1}))
                asyncio.run(main())
            """)], cwd=project, env=environment, capture_output=True, text=True, timeout=10)
            assert check.returncode == 0, check.stdout + check.stderr
            output = (root / "scheduler.log").read_text()
            assert "SendTaskError" in output and "TimeoutError" in output, output
            assert "Task exception was never retrieved" not in output, output
            config["nats"]["DEFAULT"]["nats_url"] = "nats://127.0.0.1:1"
            config["taskiq"]["startup_timeout"] = 0.3
            (data / "timer_settings.yaml").write_text(json.dumps(config), encoding="utf-8")
            failed = subprocess.run([executable, "timer", "start"], cwd=project, env=environment,
                                    capture_output=True, text=True, timeout=8, start_new_session=True)
            assert failed.returncode == 1 and "Connection refused" in failed.stdout + failed.stderr, (failed.returncode, failed.stdout, failed.stderr)
            print(check.stdout.strip().splitlines()[-1])
        finally:
            for pid in json.loads((root / "servers.json").read_text()):
                os.kill(pid, signal.SIGCONT)
            (root / "release-post").write_text("release")
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            if stopped is not None and stopped.poll() is None:
                stopped.kill()
                stopped.wait(timeout=5)


def exercise_publishers(nats_port: int, redis_port: int, root: Path) -> None:
    """Boot real existing Application entry points without starting task Workers."""
    project = root / "project"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        web_port = listener.getsockname()[1]
    sources = {
        "pyproject.toml": '[project]\nname="taskiq-publisher-probe"\nversion="0"\n',
        "config/__init__.py": "",
        "config/schemas.py": "from oldman.conf import DefaultSettings\nclass Settings(DefaultSettings):\n    pass\n",
        "services/__init__.py": "",
        "services/worker.py": """
            from oldman.runtime import SimpleApplication
            from job_app.work import emit, record_close
            class Worker(SimpleApplication):
                def prepare(self):
                    pass
                async def main(self):
                    await emit('simple')
                async def before_command(self, name, *args, **kwargs):
                    await emit('before_' + name)  # Intentionally no super call.
                async def after_command(self, name, *args, **kwargs):
                    await emit('after_' + name)
                def run(self, *args, **kwargs):
                    try:
                        return super().run(*args, **kwargs)
                    finally:
                        record_close('simple')
                async def _run_async_cli_command(self, name, func, *args, **kwargs):
                    try:
                        return await super()._run_async_cli_command(name, func, *args, **kwargs)
                    finally:
                        record_close(name)
        """,
        "services/web.py": """
            import os
            from oldman.runtime import WebApplication
            from job_app.work import emit, record_close
            class Web(WebApplication):
                async def before_server_start(self, app):
                    await emit('web-start')  # Intentionally no super call.
                async def after_server_stop(self, app):
                    await emit('web-stop')
                async def _services_after_server_stop(self, app):
                    await super()._services_after_server_stop(app)
                    record_close('web')
                def prepare_server(self, app):
                    app.prepare(host='127.0.0.1', port=int(os.environ['TASKIQ_PROBE_WEB_PORT']),
                                motd=False, access_log=False, single_process=True)
        """,
        "job_app/__init__.py": "",
        "job_app/apps.py": "from oldman.apps import AppConfig\nclass Config(AppConfig):\n    label='jobs'\n    display_name='Jobs'\napp=Config()\n",
        "job_app/tasks.py": "raise RuntimeError('Publishers must not automatically import every App task module')\n",
        "job_app/views.py": """
            from sanic.response import json
            from oldman.web.routing import get_app
            from job_app.work import emit
            @get_app().get('/publish')
            async def publish(request):
                task = await emit('web-request')
                return json({'task_id': task.task_id})
        """,
        "job_app/work.py": """
            import json, os
            from pathlib import Path
            from oldman.tasks.distributed import broker
            @broker.task()
            async def record(kind: str) -> str:
                return kind
            async def emit(kind: str):
                return await record.kiq(kind)
            def record_close(name: str):
                Path(os.environ['TASKIQ_PROBE_ROOT'], name + '-closed.json').write_text(json.dumps({
                    'closed': broker.client.is_closed and broker.results.closed and broker.schedule_source._closed,
                    'pid': os.getpid(),
                }))
        """,
        "job_app/commands.py": """
            from oldman.cli import Command
            from job_app.work import emit
            class Publish(Command):
                name = 'publish'
                help = 'Publish one test task.'
                async def handle(self):
                    await emit('command')
            class Fail(Command):
                name = 'fail'
                help = 'Fail after entering the real publisher lifecycle.'
                async def handle(self):
                    raise ValueError('expected command failure')
        """,
    }
    for relative, body in sources.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body), encoding="utf-8")
    data = project / "data"
    data.mkdir()
    config = {
        "apps": ["job_app"], "logging": {"dir": str(project / "logs")}, "process": {"pid_dir": str(project / "pids")},
        "nats": {"DEFAULT": {"nats_url": f"nats://127.0.0.1:{nats_port}"}},
        "redis": {"DEFAULT": {"redis_url": f"redis://127.0.0.1:{redis_port}/0"}},
        "taskiq": {"enabled": True, "namespace": "Publisher_Probe", "startup_timeout": 3, "startup_attempts": 1},
        "i18n": {"use_i18n": False},
        "web": {"session": {"enabled": False}, "sse": {"enabled": False}, "messages": {"enabled": False}},
    }
    for service in ("worker", "web"):
        (data / f"{service}_settings.yaml").write_text(json.dumps(config), encoding="utf-8")
    environment = {**os.environ, "PROJECT_ROOT": str(project), "TASKIQ_PROBE_ROOT": str(root),
                   "TASKIQ_PROBE_WEB_PORT": str(web_port), "PYTHONPATH": os.pathsep.join((str(project), str(ROOT)))}
    executable = str(Path(sys.executable).parent / "oldman")
    for command, expected, name in (("start", 0, "simple"), ("publish", 0, "publish"), ("fail", 1, "fail")):
        result = subprocess.run([executable, "worker", command], cwd=project, env=environment, capture_output=True, text=True, timeout=10)
        assert result.returncode == expected, result.stdout + result.stderr
        assert json.loads((root / f"{name}-closed.json").read_text())["closed"]
        if command == "fail":
            assert "expected command failure" in result.stdout + result.stderr
    synchronized = subprocess.run([executable, "web", "settings", "sync"], cwd=project, env=environment,
                                  capture_output=True, text=True, timeout=10)
    assert synchronized.returncode == 0, synchronized.stdout + synchronized.stderr
    with (root / "web.log").open("w+") as log:
        process = subprocess.Popen([executable, "web", "start"], cwd=project, env=environment,
                                   stdout=log, stderr=log, text=True, start_new_session=True)
        try:
            deadline = time.monotonic() + 12
            while True:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{web_port}/publish", timeout=1) as response:
                        assert json.load(response)["task_id"]
                    break
                except urllib.error.URLError:
                    assert process.poll() is None and time.monotonic() < deadline, (root / "web.log").read_text()
                    time.sleep(0.05)
            result = subprocess.run([executable, "web", "stop"], cwd=project, env=environment, capture_output=True, text=True, timeout=8)
            assert result.returncode == 0, result.stdout + result.stderr
            process.wait(timeout=10)
            assert process.returncode == 0, (root / "web.log").read_text()
            assert json.loads((root / "web-closed.json").read_text())["closed"]
            assert "Traceback" not in (root / "web.log").read_text(), (root / "web.log").read_text()
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
    # The Shell path is explicit and reuses the same public objects on two loops.
    check = subprocess.run([sys.executable, "-c", textwrap.dedent("""
        import asyncio, json
        from oldman import bootstrap_service
        bootstrap_service('worker')
        from oldman.tasks.distributed import broker
        async def inspect():
            async with broker:
                info = await broker.js.stream_info(broker.stream_name)
                assert info.state.messages == 9, info.state
                assert info.state.consumer_count == 0
                return info.state.messages
        queued = asyncio.run(inspect())
        assert asyncio.run(inspect()) == queued
        print(json.dumps({'queued': queued, 'web_closed': True}))
    """)], cwd=project, env=environment, capture_output=True, text=True, timeout=10)
    assert check.returncode == 0, check.stdout + check.stderr
    config["nats"]["DEFAULT"]["nats_url"] = "nats://127.0.0.1:1"
    config["taskiq"]["startup_timeout"] = 0.3
    (data / "worker_settings.yaml").write_text(json.dumps(config), encoding="utf-8")
    failed = subprocess.run([executable, "worker", "start"], cwd=project, env=environment, capture_output=True, text=True, timeout=8)
    assert failed.returncode == 1 and "Connection refused" in failed.stdout + failed.stderr, (failed.returncode, failed.stdout, failed.stderr)
    print(check.stdout.strip().splitlines()[-1])


def exercise_broadcast(nats_port: int, redis_port: int, root: Path) -> None:
    """Observe real executions, not result keys overwritten by broadcast copies."""
    from oldman import conf
    from oldman.conf.schemas import DefaultSettings

    project = root / "project"
    sources = {
        "pyproject.toml": '[project]\nname="taskiq-broadcast-probe"\nversion="0"\n',
        "config/__init__.py": "",
        "config/schemas.py": "from oldman.conf import DefaultSettings\nclass Settings(DefaultSettings):\n    pass\n",
        "services/__init__.py": "",
        "services/jobs.py": "from oldman.runtime import TaskiqWorkerApplication\nclass Jobs(TaskiqWorkerApplication):\n    pass\n",
        "job_app/__init__.py": "",
        "job_app/apps.py": "from oldman.apps import AppConfig\nclass Config(AppConfig):\n    label='jobs'\n    display_name='Jobs'\napp=Config()\n",
        "job_app/tasks.py": '''
            import asyncio, os
            from oldman.providers.redis import redis_client
            from oldman.tasks.distributed import broker
            active = 0

            @broker.task(task_name="broadcast.probe", queue_name="busy", retry_on_error=True, delay=1)
            async def probe(kind: str) -> int:
                global active
                active += 1
                client = await redis_client.using("DEFAULT").async_get_conn()
                try:
                    await client.rpush("broadcast:events", f"{kind}:{os.getpid()}:{active}")
                    await asyncio.sleep(0.08 if kind == "flood" else 0.2)
                    if kind == "fail":
                        raise ValueError("Expected broadcast failure without retry")
                    return os.getpid()
                finally:
                    active -= 1
        ''',
    }
    for relative, body in sources.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body), encoding="utf-8")
    config = {
        "apps": ["job_app"], "logging": {"dir": str(project / "logs")}, "process": {"pid_dir": str(project / "pids")},
        "nats": {"DEFAULT": {"nats_url": f"nats://127.0.0.1:{nats_port}"}},
        "redis": {"DEFAULT": {"redis_url": f"redis://127.0.0.1:{redis_port}/0"}},
        "taskiq": {"enabled": True, "namespace": "Broadcast_Probe", "workers": 2, "max_async_tasks": 1,
                   "consume_queues": ["empty", "busy"], "startup_timeout": 5, "startup_attempts": 1,
                   "shutdown_timeout": 2, "stop_timeout": 6, "ack_wait": 0.3},
    }
    (project / "data").mkdir()
    (project / "data/jobs_settings.yaml").write_text(json.dumps(config), encoding="utf-8")
    conf._publish_settings(DefaultSettings.model_validate(config))
    from redis.asyncio import Redis
    from taskiq.exceptions import SendTaskError

    from oldman.processes.subprocess import _live_process_group_pids
    from oldman.tasks.distributed import broker, schedule_source

    async def never_called(kind: str) -> int:
        """Only the real spawned workers are allowed to execute this task."""
        raise AssertionError(kind)

    task = broker.task(task_name="broadcast.probe", queue_name="busy", retry_on_error=True)(never_called)
    environment = {**os.environ, "PROJECT_ROOT": str(project), "PYTHONPATH": os.pathsep.join((str(project), str(ROOT)))}
    command = [str(Path(sys.executable).parent / "oldman"), "jobs"]

    async def run() -> dict[str, Any]:
        """Broadcast before/after workers, then verify the live mixed workload."""
        async with broker, Redis.from_url(f"redis://127.0.0.1:{redis_port}/0", decode_responses=True) as client:
            await task.kicker().with_labels(broadcast=True).kiq("offline")
            with (root / "broadcast.log").open("w+") as log:
                process = subprocess.Popen([*command, "start"], cwd=project, env=environment, stdout=log, stderr=log, start_new_session=True)
                try:
                    async with asyncio.timeout(10):
                        while "All 2 Taskiq worker processes are ready" not in (root / "broadcast.log").read_text():
                            assert process.poll() is None, (root / "broadcast.log").read_text()
                            await asyncio.sleep(0.05)
                    ordinary = [await task.kiq("normal") for _ in range(6)]
                    broadcast = await task.kicker().with_labels(broadcast=True, ignore_result=False, retry_on_error=True).kiq("live")
                    failed = await task.kicker().with_labels(broadcast=True).kiq("fail")
                    await task.kicker().with_labels(broadcast=True, queue_name="other").kiq("other_queue")
                    # Even a valid task envelope outside this namespace is not received.
                    from taskiq import TaskiqMessage

                    wire = broker.formatter.dumps(TaskiqMessage(task_id="other", task_name="broadcast.probe", labels={"broadcast": True}, args=["other_namespace"], kwargs={}))
                    await broker.client.publish("oldman.taskiq.Other.broadcast.busy", wire.message)
                    for job in ordinary:
                        assert not (await job.wait_result(timeout=8)).is_err
                    async with asyncio.timeout(8):
                        while len(await client.lrange("broadcast:events", 0, -1)) < 10:
                            await asyncio.sleep(0.05)
                    await asyncio.sleep(0.4)
                    events = [cast(str, item).split(":") for item in await client.lrange("broadcast:events", 0, -1)]
                    assert len(events) == 10, events
                    live_pids = {pid for kind, pid, _ in events if kind == "live"}
                    assert len(live_pids) == 2 and all(os.getpgid(int(pid)) == process.pid for pid in live_pids), events
                    assert len([event for event in events if event[0] == "fail"]) == 2
                    assert max(int(event[2]) for event in events) == 1, events
                    assert not await broadcast.is_ready() and not await failed.is_ready()
                    assert not await schedule_source.get_schedules()
                    assert "broadcast" not in task.labels and task.labels["retry_on_error"] is True
                    # A burst exceeds the native per-subscription buffer while
                    # Receiver is busy; oversized transient copies are dropped.
                    for _ in range(220):
                        await task.kicker().with_labels(broadcast=True).kiq("flood")
                    async with asyncio.timeout(5):
                        while "slow consumer" not in (root / "broadcast.log").read_text().lower():
                            await asyncio.sleep(0.05)
                    stopped = await asyncio.to_thread(subprocess.run, [*command, "stop"], cwd=project, env=environment, capture_output=True, text=True, timeout=10)
                    assert stopped.returncode == 0, stopped.stdout + stopped.stderr + (root / "broadcast.log").read_text()
                    await asyncio.to_thread(process.wait, timeout=4)
                    assert process.returncode == 0 and not _live_process_group_pids(process.pid), (root / "broadcast.log").read_text()
                    assert (await broker.js.stream_info(broker.stream_name)).state.messages == 0
                    await task.kicker().with_labels(broadcast=True).kiq("offline_after")
                    count = await client.llen("broadcast:events")
                    # Restart the same service: Core has no backlog to replay.
                    process = subprocess.Popen([*command, "start"], cwd=project, env=environment, stdout=log, stderr=log, start_new_session=True)
                    normal = await task.kiq("after_restart")
                    assert not (await normal.wait_result(timeout=10)).is_err
                    await asyncio.sleep(0.3)
                    assert await client.llen("broadcast:events") == count + 1
                    stopped = await asyncio.to_thread(subprocess.run, [*command, "stop"], cwd=project, env=environment, capture_output=True, text=True, timeout=10)
                    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
                    await asyncio.to_thread(process.wait, timeout=4)
                    assert process.returncode == 0 and not _live_process_group_pids(process.pid)
                    await broker.client.close()
                    try:
                        await task.kicker().with_labels(broadcast=True).kiq("disconnected")
                    except SendTaskError as error:
                        assert isinstance(error.__cause__, RuntimeError)
                    else:
                        raise AssertionError("A known offline broadcaster must fail")
                    return {"broadcast_copies": len(live_pids), "maximum_per_process": 1, "slow_consumer_logged": True}
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)

    print(json.dumps(asyncio.run(run())))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--exercise":
        exercise(int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]))
    elif len(sys.argv) > 1 and sys.argv[1] == "--worker":
        exercise_worker(int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]))
    elif len(sys.argv) > 1 and sys.argv[1] == "--scheduler":
        exercise_scheduler(int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]))
    elif len(sys.argv) > 1 and sys.argv[1] == "--scheduler-faults":
        exercise_scheduler_faults(int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]))
    elif len(sys.argv) > 1 and sys.argv[1] == "--scheduler-force-stop":
        exercise_scheduler_faults(int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]), force_stop=True)
    elif len(sys.argv) > 1 and sys.argv[1] == "--publishers":
        exercise_publishers(int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]))
    elif len(sys.argv) > 1 and sys.argv[1] == "--broadcast":
        exercise_broadcast(int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]))
    elif len(sys.argv) > 1 and sys.argv[1] == "--confirmation-faults":
        from tests.taskiq_fault_checks import exercise_confirmations

        exercise_confirmations(int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]))
    elif len(sys.argv) > 1 and sys.argv[1] == "--resource-faults":
        from tests.taskiq_fault_checks import exercise_resources

        exercise_resources(int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]))
    elif len(sys.argv) > 1 and sys.argv[1] == "--tls-faults":
        from tests.taskiq_fault_checks import exercise_tls

        exercise_tls(int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]))
    elif len(sys.argv) > 1 and sys.argv[1] == "--shared-redis":
        from tests.taskiq_fault_checks import exercise_shared_redis

        exercise_shared_redis(int(sys.argv[3]))
    elif len(sys.argv) > 1 and sys.argv[1] == "--prefetch":
        from tests.taskiq_fault_checks import exercise_prefetch

        exercise_prefetch(int(sys.argv[2]), int(sys.argv[3]))
    else:
        unittest.main()
