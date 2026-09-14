"""Focused faults used by the owned-server distributed integration runner."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast


def exercise_confirmations(nats_port: int, redis_port: int, root: Path) -> None:
    """Run actual native request timeouts, ACK cleanup and result failure paths."""
    del root
    from oldman import conf
    from oldman.conf.schemas import DefaultSettings

    raw = {
        "nats": {"DEFAULT": {"nats_url": f"nats://127.0.0.1:{nats_port}"}},
        "redis": {"DEFAULT": {"redis_url": f"redis://127.0.0.1:{redis_port}/0", "retry_attempts": 0}},
        "taskiq": {"enabled": True, "namespace": "Confirmation_Test", "consume_queues": ["jobs"],
                   "ack_wait": 0.3, "publish_timeout": 0.2, "ack_timeout": 0.15, "duplicate_window": 2},
    }
    settings = DefaultSettings.model_validate(raw)
    conf._publish_settings(settings)

    from nats.aio.msg import Msg
    from nats.errors import TimeoutError as NatsTimeoutError
    from pydantic_core import PydanticSerializationError
    from redis.asyncio import Redis
    from taskiq.exceptions import SendTaskError

    from oldman.tasks.distributed import broker
    from oldman.tasks.distributed.broker import TaskiqBroker
    from oldman.tasks.distributed.receiver import RenewingMessage, RenewingReceiver

    executions: list[str] = []

    async def job(kind: str) -> Any:
        """Count executions outside the result key that might be overwritten."""
        executions.append(kind)
        return object() if kind in {"unsupported", "ignored"} else {"名称": kind}

    task = broker.task(task_name="confirmation.job", queue_name="jobs")(job)

    async def run() -> dict[str, int]:
        """A callback drops only replies already received from the real server."""
        redis = Redis.from_url(f"redis://127.0.0.1:{redis_port}/0")
        await redis.execute_command("ACL", "SETUSER", "taskiq_faults", "on", ">isolated-only", "~*", "+@all")
        worker_raw = settings.model_dump()
        worker_raw["redis"]["DEFAULT"]["redis_url"] = f"redis://taskiq_faults:isolated-only@127.0.0.1:{redis_port}/0"
        worker = TaskiqBroker(DefaultSettings.model_validate(worker_raw))
        worker.is_worker_process = True
        worker.task(task_name="confirmation.job", queue_name="jobs")(job)
        drops = {"puback_remaining": 1, "ack_remaining": 0, "puback": 0, "ack": 0}

        def install_reply_drop(client, *, publisher: bool) -> None:
            """Ignore selected wire replies before native Future completion.

            The native request still sends to NATS and waits for its own timeout.
            No task body, broker method or exception is replaced. This simulates
            reply loss after the server has already stored/acknowledged a task.
            """
            subject = bytes(client._resp_sub_prefix).decode() + "*"
            subscription = next(sub for sub in client._subs.values() if sub.subject == subject)
            callback = subscription._cb

            async def receive(message: Msg) -> None:
                """Keep resource API replies and all unselected native traffic."""
                if publisher and drops["puback_remaining"] and message.data.startswith(b"{"):
                    response = json.loads(message.data)
                    if response.get("stream") == broker.stream_name and "seq" in response:
                        drops["puback_remaining"] -= 1
                        drops["puback"] += 1
                        return
                if not publisher and drops["ack_remaining"] and message.data == b"":
                    drops["ack_remaining"] -= 1
                    drops["ack"] += 1
                    return
                await callback(message)

            subscription._cb = receive

        deliveries = None
        try:
            await broker.startup()
            await worker.startup()
            install_reply_drop(broker.client, publisher=True)
            install_reply_drop(worker.client, publisher=False)
            receiver = RenewingReceiver(worker, max_async_tasks=1, max_prefetch=0, run_startup=False)
            deliveries = worker.listen()

            first = await task.kiq("lost-puback")
            info = await broker.js.stream_info(broker.stream_name)
            assert drops["puback"] == 1 and info.state.messages == 1 and info.state.last_seq == 1, info
            wire = await asyncio.wait_for(anext(deliveries), 2)
            assert isinstance(wire, RenewingMessage)
            drops["ack_remaining"] = 1
            await receiver.callback(wire)
            assert drops["ack"] == 1 and not worker._deliveries
            assert (await first.get_result()).return_value == {"名称": "lost-puback"}
            assert executions == ["lost-puback"]

            final_ack = await task.kiq("lost-both-acks")
            wire = await asyncio.wait_for(anext(deliveries), 2)
            assert isinstance(wire, RenewingMessage)
            drops["ack_remaining"] = 2
            try:
                await receiver.callback(wire)
            except NatsTimeoutError:
                pass
            else:
                raise AssertionError("Two lost completion replies must propagate the native timeout")
            assert not worker._deliveries and drops["ack"] == 3
            assert (await final_ack.get_result()).return_value == {"名称": "lost-both-acks"}
            # Server accepted the ACK even though neither reply reached its waiter.
            await asyncio.sleep(settings.taskiq.ack_wait * 2)
            assert (await broker.js.stream_info(broker.stream_name)).state.messages == 0
            assert executions == ["lost-puback", "lost-both-acks"]

            try:
                await task.kiq(cast(Any, object()))  # Deliberately violate the wire contract.
            except SendTaskError as error:
                assert isinstance(error.__cause__, PydanticSerializationError), error.__cause__
            else:
                raise AssertionError("The native formatter must reject an unsupported argument before publication")
            assert (await broker.js.stream_info(broker.stream_name)).state.messages == 0

            unsupported = await task.kiq("unsupported")
            await receiver.callback(await asyncio.wait_for(anext(deliveries), 2))
            assert not await unsupported.is_ready() and not worker._deliveries
            assert (await broker.js.stream_info(broker.stream_name)).state.messages == 0

            ignored = await task.kicker().with_labels(ignore_result=True).kiq("ignored")
            await receiver.callback(await asyncio.wait_for(anext(deliveries), 2))
            assert not await ignored.is_ready() and not worker._deliveries

            unavailable_result = await task.kiq("redis-denied")
            await redis.execute_command("ACL", "SETUSER", "taskiq_faults", "-set")
            try:
                await receiver.callback(await asyncio.wait_for(anext(deliveries), 2))
            finally:
                await redis.execute_command("ACL", "SETUSER", "taskiq_faults", "+set")
            assert not await unavailable_result.is_ready() and not worker._deliveries
            remaining = (await broker.js.stream_info(broker.stream_name)).state.messages
            # Native WHEN_SAVED still ACKs after logging a result-write failure.
            # This is a documented upstream boundary, not a claim that results exist.
            assert remaining == 0 and executions[-3:] == ["unsupported", "ignored", "redis-denied"]
            return {"dropped_pubacks": drops["puback"], "dropped_acks": drops["ack"],
                    "executions": len(executions), "remaining_messages": remaining}
        finally:
            if deliveries is not None:
                await deliveries.aclose()
            await worker.shutdown()
            await broker.shutdown()
            await redis.aclose()
            await asyncio.sleep(0)
            assert not (asyncio.all_tasks() - {asyncio.current_task()})

    print(json.dumps(asyncio.run(run())))


def exercise_shared_redis(redis_port: int) -> None:
    """Reuse real acceptance checks; replace only their default config factory."""
    import unittest
    from unittest.mock import patch

    from oldman.conf.schemas import DefaultSettings
    from tests import test_oldman_redis_cache_integration, test_oldman_redis_settings_integration

    settings = DefaultSettings.model_validate({
        "redis": {alias: {"redis_url": f"redis://127.0.0.1:{redis_port}/{number}"}
                  for number, alias in enumerate(("DEFAULT", "CACHE"))},
    })
    checks = 0
    for module in (test_oldman_redis_settings_integration, test_oldman_redis_cache_integration):
        with patch.object(module, "DefaultSettings", return_value=settings):
            result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromModule(module))
            assert result.wasSuccessful() and not result.skipped
            checks += result.testsRun
    print(json.dumps({"checks": checks}))


def exercise_prefetch(nats_port: int, redis_port: int) -> None:
    """Hold real executions while measuring native admission plus merger buffers."""
    from oldman import conf
    from oldman.conf.schemas import DefaultSettings

    settings = DefaultSettings.model_validate({
        "nats": {"DEFAULT": {"nats_url": f"nats://127.0.0.1:{nats_port}"}},
        "redis": {"DEFAULT": {"redis_url": f"redis://127.0.0.1:{redis_port}/0"}},
        "taskiq": {"enabled": True, "namespace": "Prefetch_Test", "consume_queues": ["empty", "a", "b"],
                   "ack_wait": 0.3, "max_async_tasks": 2},
    })
    conf._publish_settings(settings)
    from oldman.tasks.distributed import broker
    from oldman.tasks.distributed.receiver import RenewingReceiver

    broker.is_worker_process = True

    async def run() -> dict[str, list[int]]:
        """One actual Receiver shares two busy queues; the third stays empty."""
        maxima, completed = [], []
        for prefetch in (0, 3):
            gate, finish = asyncio.Event(), asyncio.Event()
            active, maximum, count = 0, 0, 0

            @broker.task(task_name="prefetch.job", ignore_result=True)
            async def job() -> None:
                """Count real function entries, not result records or queue length."""
                nonlocal active, maximum, count
                active += 1
                maximum = max(active, maximum)
                await gate.wait()  # noqa: B023 -- this iteration's Receiver is drained before the next gate exists.
                await asyncio.sleep(0.01)
                active -= 1
                count += 1

            async with broker:
                for index in range(20):
                    await job.kicker().with_labels(queue_name="a" if index % 2 else "b").kiq()
                receiver = RenewingReceiver(broker, max_async_tasks=2, max_prefetch=prefetch, run_startup=False)
                listener = asyncio.create_task(receiver.listen(finish))
                try:
                    async with asyncio.timeout(3):
                        while active != 2:
                            await asyncio.sleep(0.01)
                    await asyncio.sleep(0.8)  # Several AckWait periods, still held.
                    # Native capacity is 2+prefetch; each durable source adds at
                    # most one merger slot. The empty queue contributes no work.
                    assert 2 + prefetch <= len(broker._deliveries) <= 2 + prefetch + 3
                    assert active == maximum == 2
                    for queue in ("a", "b"):
                        assert (await broker.js.consumer_info(broker.stream_name, f"workers_{queue}")).num_redelivered == 0
                    gate.set()
                    async with asyncio.timeout(4):
                        while count < 20 or broker._deliveries:
                            await asyncio.sleep(0.02)
                    assert (await broker.js.stream_info(broker.stream_name)).state.messages == 0
                    maxima.append(maximum)
                    completed.append(count)
                finally:
                    gate.set()
                    finish.set()
                    await asyncio.wait_for(listener, 4)
        return {"maximum_executions": maxima, "completed": completed}

    print(json.dumps(asyncio.run(run())))


def exercise_tls(nats_port: int, redis_port: int, root: Path) -> None:
    """Reuse owned certificate fixtures, but connect through the full Taskiq broker."""
    del nats_port
    import ssl

    from oldman import conf
    from oldman.conf.schemas import DefaultSettings
    from tests.test_oldman_nats_config import NATSTLSIntegrationTest

    NATSTLSIntegrationTest.setUpClass()
    case = NATSTLSIntegrationTest()

    async def run() -> dict[str, float | int]:
        """Positive publication and both certificate errors use production cleanup."""
        with socket.socket() as endpoint:
            endpoint.bind(("127.0.0.1", 0))
            case.port = endpoint.getsockname()[1]
        case.server = None
        case.log = (root / "tls-server.log").open("wb")
        try:
            await case.start_server(authentication=f'jetstream {{ store_dir: "{root / "tls-js"}", max_file_store: 134217728 }}\n')
            settings = DefaultSettings.model_validate({
                "nats": {"DEFAULT": case.config().model_dump()},
                "redis": {"DEFAULT": {"redis_url": f"redis://127.0.0.1:{redis_port}/0"}},
                "taskiq": {"enabled": True, "namespace": "TLS_Test", "startup_timeout": 0.8, "shutdown_timeout": 5},
            })
            conf._publish_settings(settings)
            from oldman.tasks.distributed import broker
            from oldman.tasks.distributed.broker import TaskiqBroker

            @broker.task()
            async def job() -> str:
                """A positive TLS publication proves the real Stream API works."""
                return "加密任务"

            async with broker:
                await job.kiq()
                assert (await broker.js.stream_info(broker.stream_name)).state.messages == 1
            durations: list[float] = []
            for change in ({"tls_ca_file": None}, {"nats_url": f"tls://127.0.0.1:{case.port}"}):
                raw = settings.model_dump()
                raw["nats"]["DEFAULT"].update(change)
                failed = TaskiqBroker(DefaultSettings.model_validate(raw))
                started = time.monotonic()
                try:
                    await failed.startup()
                except ssl.SSLCertVerificationError:
                    pass
                else:
                    raise AssertionError("A certificate error must remain the public startup failure")
                durations.append(time.monotonic() - started)
                assert not failed._started and (failed._closed or failed._broken)
                assert failed.results.close_attempted and failed.schedule_source._closed
            return {"certificate_failures": len(durations), "maximum_seconds": max(durations)}
        finally:
            await case.stop_server()
            case.log.close()

    try:
        print(json.dumps(asyncio.run(run())))
    finally:
        NATSTLSIntegrationTest.doClassCleanups()


def resource_settings(nats_port: int, redis_port: int):
    """Publish one isolated settings identity in each real test process."""
    from oldman import conf
    from oldman.conf.schemas import DefaultSettings

    settings = DefaultSettings.model_validate({
        "nats": {"DEFAULT": {"nats_url": f"nats://127.0.0.1:{nats_port}"}},
        "redis": {"DEFAULT": {"redis_url": f"redis://127.0.0.1:{redis_port}/0"}},
        "taskiq": {"enabled": True, "namespace": "Resource_Test", "consume_queues": ["jobs"],
                   "stream_max_bytes": 4096, "ack_wait": 0.3},
    })
    conf._publish_settings(settings)
    return settings


def resource_child(nats_port: int, redis_port: int, directory: str) -> None:
    """Wait at a test-only barrier, then use the real Worker resource startup."""
    root = Path(directory)
    resource_settings(nats_port, redis_port)
    from oldman.tasks.distributed import broker

    broker.is_worker_process = True
    (root / f"ready-{os.getpid()}").touch()
    deadline = time.monotonic() + 10
    while not (root / "create-now").exists():
        if time.monotonic() > deadline:
            raise TimeoutError("Resource test barrier was not released")
        time.sleep(0.01)

    async def run() -> None:
        """Close all native resources before exiting the owned child process."""
        async with broker:
            info = await broker.js.stream_info(broker.stream_name)
            assert info.state.consumer_count == 1

    asyncio.run(run())


def exercise_resources(nats_port: int, redis_port: int, root: Path) -> None:
    """Keep existing data/configuration and reject new messages at real capacity."""
    settings = resource_settings(nats_port, redis_port)
    from nats.js.errors import APIError
    from taskiq.exceptions import SendTaskError

    from oldman.tasks.distributed import broker
    from oldman.tasks.distributed.broker import TaskiqBroker

    children: list[subprocess.Popen[str]] = []
    try:
        command = [sys.executable, "-c", "from tests.taskiq_fault_checks import resource_child; import sys; resource_child(int(sys.argv[1]),int(sys.argv[2]),sys.argv[3])",
                   str(nats_port), str(redis_port), str(root)]
        for _ in range(2):
            children.append(subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        deadline = time.monotonic() + 10
        while not all((root / f"ready-{child.pid}").exists() for child in children):
            if time.monotonic() > deadline or any(child.poll() is not None for child in children):
                raise AssertionError("Resource initialization children did not reach their barrier")
            time.sleep(0.01)
        (root / "create-now").touch()
        for child in children:
            stdout, stderr = child.communicate(timeout=10)
            assert child.returncode == 0, stdout + stderr
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)

    @broker.task(task_name="resource.job", queue_name="jobs")
    async def job(value: str) -> str:
        """Only enqueue in this check; preserve every accepted message as backlog."""
        return value

    async def run() -> dict[str, int]:
        """Check actual Stream and consumer values after each attempted operation."""
        await broker.startup()
        try:
            await job.kiq("oldest")
            first = await broker.js.stream_info(broker.stream_name)
            assert first.state.messages == 1
            previous = await broker.js.get_msg(broker.stream_name, seq=first.state.first_seq)
            assert previous.data is not None and json.loads(previous.data)["args"] == ["oldest"]

            compatible = TaskiqBroker(settings)
            compatible.is_worker_process = True
            async with compatible:
                assert (await compatible.js.stream_info(broker.stream_name)).state.messages == 1
            for field, value in (("stream_max_bytes", 8192), ("ack_wait", 1.2)):
                different = settings.model_dump()
                different["taskiq"][field] = value
                conflict = TaskiqBroker(type(settings).model_validate(different))
                conflict.is_worker_process = True
                try:
                    await conflict.startup()
                except RuntimeError as error:
                    assert "conflicts:" in str(error), error
                else:
                    raise AssertionError(f"Conflicting {field} must not update a shared resource")
                assert conflict.client.is_closed and conflict.schedule_source._closed
                info = await broker.js.stream_info(broker.stream_name)
                consumer = await broker.js.consumer_info(broker.stream_name, "workers_jobs")
                assert info.config.max_bytes == 4096 and consumer.config.ack_wait == 0.3
                assert info.state.messages == 1

            accepted = 1
            for _ in range(20):
                try:
                    await job.kiq("新任务" * 180)
                    accepted += 1
                except SendTaskError as error:
                    assert isinstance(error.__cause__, APIError), error.__cause__
                    assert "maximum bytes" in str(error.__cause__).lower(), error.__cause__
                    break
            else:
                raise AssertionError("The 4 KiB real Stream must reject new work at capacity")
            info = await broker.js.stream_info(broker.stream_name)
            assert info.state.messages == accepted and info.state.first_seq == first.state.first_seq
            assert (await broker.js.get_msg(broker.stream_name, seq=first.state.first_seq)).data == previous.data

            core = await broker.client.subscribe("example.rpc.echo")
            await broker.client.publish("example.rpc.echo", b"not-a-task")
            assert (await core.next_msg(timeout=1)).data == b"not-a-task"
            await core.unsubscribe()
            assert (await broker.js.stream_info(broker.stream_name)).state.messages == accepted
            return {"creators": len(children), "rejected_conflicts": 2, "retained_messages": accepted}
        finally:
            await broker.shutdown()
            await asyncio.sleep(0)
            assert not (asyncio.all_tasks() - {asyncio.current_task()})

    print(json.dumps(asyncio.run(run())))
