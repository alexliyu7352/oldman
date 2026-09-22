"""BackgroundTaskManager: done-callback supervision, restart policy and fire-and-forget spawns."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any, cast
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from oldman.tasks import BackgroundTaskManager, TaskStatus, TaskType
from oldman.tasks.simple import TaskInfo

LOGGER = "default"


def fresh_manager() -> BackgroundTaskManager:
    """A private instance: the decorated class is a process singleton shared with the runtimes."""
    return cast(Any, BackgroundTaskManager).__wrapped__()


async def wait_until(condition: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.005)


async def settle() -> None:
    """Let done callbacks scheduled with call_soon run."""
    for _ in range(3):
        await asyncio.sleep(0)


class Runs:
    """Count invocations of a coroutine function and script each run's outcome."""

    def __init__(self, outcomes: list[str] | None = None) -> None:
        self.count = 0
        self.outcomes = list(outcomes or [])
        self.release = asyncio.Event()

    async def __call__(self, *args: Any, **kwargs: Any) -> str:
        self.count += 1
        outcome = self.outcomes.pop(0) if self.outcomes else "wait"
        if outcome == "wait":
            await self.release.wait()
            return "released"
        if outcome == "fail":
            raise RuntimeError(f"run {self.count} failed")
        return outcome


class SpawnTest(IsolatedAsyncioTestCase):
    async def test_spawn_runs_now_and_forgets_the_task_when_it_completes(self) -> None:
        manager = fresh_manager()
        seen: list[tuple[int, str]] = []

        async def job(value: int, *, label: str) -> None:
            seen.append((value, label))

        task = manager.spawn(job, 7, label="mail")

        self.assertIsInstance(task, asyncio.Task)
        self.assertEqual(manager.get_task_status(task.get_name())["status"], "running")
        await task
        await settle()
        self.assertEqual(seen, [(7, "mail")])
        self.assertEqual(manager.get_all_status(), {})

    async def test_spawn_failure_is_logged_removed_and_never_retried(self) -> None:
        manager = fresh_manager()
        runs = Runs(["fail"])

        with self.assertLogs(LOGGER, level="ERROR") as logs:
            task = manager.spawn(runs, name="reset-mail")
            with self.assertRaises(RuntimeError):
                await task
            await settle()

        self.assertTrue(any("reset-mail failed" in line for line in logs.output))
        self.assertEqual(manager.get_all_status(), {})
        await asyncio.sleep(0.02)
        self.assertEqual(runs.count, 1)

    async def test_spawn_names_are_unique_and_taken_names_are_rejected(self) -> None:
        manager = fresh_manager()
        runs = Runs()

        first = manager.spawn(runs)
        second = manager.spawn(runs)
        self.assertNotEqual(first.get_name(), second.get_name())
        self.assertTrue(first.get_name().startswith("Runs-") or first.get_name().startswith("task-"))
        manager.add_task("held", runs)
        with self.assertRaises(ValueError):
            manager.spawn(runs, name="held")
        with self.assertRaises(ValueError):
            manager.add_task("held", runs)

        runs.release.set()
        await asyncio.gather(first, second)

    async def test_spawn_is_refused_while_stopping(self) -> None:
        manager = fresh_manager()
        await manager.stop_all()

        with self.assertRaises(RuntimeError):
            manager.spawn(Runs())

        await manager.start_all()
        task = manager.spawn(Runs(["done"]))
        self.assertEqual(await task, "done")

    async def test_spawn_argument_errors_surface_to_the_caller_and_leave_no_registration(self) -> None:
        manager = fresh_manager()

        async def job(required: int) -> None:
            return None

        with self.assertRaises(TypeError):
            manager.spawn(cast(Any, job))
        self.assertEqual(manager.get_all_status(), {})


class RestartPolicyTest(IsolatedAsyncioTestCase):
    async def test_persistent_task_restarts_after_an_exception(self) -> None:
        manager = fresh_manager()
        runs = Runs(["fail", "wait"])
        manager.add_task("worker", runs, restart_delay=0)

        with self.assertLogs(LOGGER, level="ERROR") as logs:
            await manager.start_task("worker")
            await wait_until(lambda: runs.count == 2)

        self.assertTrue(any("worker failed" in line for line in logs.output))
        status = manager.get_task_status("worker")
        self.assertEqual(status["status"], "running")
        self.assertEqual(status["restart_count"], 1)
        self.assertTrue(status["is_alive"])
        await manager.stop_all()

    async def test_persistent_task_restarts_after_a_normal_return(self) -> None:
        manager = fresh_manager()
        runs = Runs(["done", "wait"])
        manager.add_task("worker", runs, restart_delay=0)

        await manager.start_task("worker")
        await wait_until(lambda: runs.count == 2)

        self.assertEqual(manager.get_task_status("worker")["status"], "running")
        await manager.stop_all()

    async def test_restart_waits_for_the_delay_measured_from_the_last_start(self) -> None:
        manager = fresh_manager()
        runs = Runs(["fail", "wait"])
        manager.add_task("worker", runs, restart_delay=60)

        with self.assertLogs(LOGGER, level="ERROR"):
            await manager.start_task("worker")
            await settle()

        info = manager.tasks["worker"]
        self.assertEqual(info.status, TaskStatus.RESTARTING)
        self.assertIsNotNone(info.restart_handle)
        await asyncio.sleep(0.02)
        self.assertEqual(runs.count, 1)
        await manager.stop_task("worker")
        self.assertIsNone(info.restart_handle)
        self.assertEqual(info.status, TaskStatus.STOPPED)
        await asyncio.sleep(0.02)
        self.assertEqual(runs.count, 1)

    async def test_max_restarts_bounds_automatic_restarts(self) -> None:
        manager = fresh_manager()
        runs = Runs(["fail", "fail", "fail", "fail"])
        manager.add_task("worker", runs, restart_delay=0, max_restarts=2)

        with self.assertLogs(LOGGER, level="WARNING") as logs:
            await manager.start_task("worker")
            await wait_until(lambda: manager.get_task_status("worker")["status"] == "error")

        self.assertEqual(runs.count, 3)
        self.assertEqual(manager.get_task_status("worker")["restart_count"], 2)
        self.assertTrue(any("exceeded max restarts (2)" in line for line in logs.output))

    async def test_max_restarts_zero_disables_restarts(self) -> None:
        manager = fresh_manager()
        runs = Runs(["done"])
        manager.add_task("worker", runs, restart_delay=0, max_restarts=0)

        await manager.start_task("worker")
        await wait_until(lambda: manager.get_task_status("worker")["status"] == "completed")

        self.assertEqual(runs.count, 1)

    async def test_one_time_task_is_removed_after_success_or_kept_as_completed(self) -> None:
        manager = fresh_manager()
        manager.add_task("removed", Runs(["done"]), task_type=TaskType.ONE_TIME)
        manager.add_task("kept", Runs(["done"]), task_type=TaskType.ONE_TIME, auto_remove_on_complete=False)

        await manager.start_all()
        await wait_until(lambda: "removed" not in manager.tasks)
        await wait_until(lambda: manager.get_task_status("kept")["status"] == "completed")

        self.assertFalse(manager.get_task_status("kept")["is_alive"])

    async def test_one_time_failure_is_an_error_without_restart_unless_a_budget_is_given(self) -> None:
        manager = fresh_manager()
        never = Runs(["fail", "done"])
        once = Runs(["fail", "done"])
        manager.add_task("never", never, task_type=TaskType.ONE_TIME, restart_delay=0)
        manager.add_task("once", once, task_type=TaskType.ONE_TIME, restart_delay=0, max_restarts=1)

        with self.assertLogs(LOGGER, level="ERROR"):
            await manager.start_all()
            await wait_until(lambda: manager.get_task_status("never")["status"] == "error")
            await wait_until(lambda: "once" not in manager.tasks)

        await asyncio.sleep(0.02)
        self.assertEqual(never.count, 1)
        self.assertEqual(once.count, 2)

    async def test_cancellation_from_outside_restarts_persistent_and_stops_one_time_tasks(self) -> None:
        manager = fresh_manager()
        persistent = Runs()
        one_time = Runs()
        manager.add_task("persistent", persistent, restart_delay=0)
        manager.add_task("one_time", one_time, task_type=TaskType.ONE_TIME)
        await manager.start_all()
        await settle()

        with self.assertLogs(LOGGER, level="WARNING"):
            for name in ("persistent", "one_time"):
                task = manager.tasks[name].task
                assert task is not None
                task.cancel()
            await wait_until(lambda: persistent.count == 2)
            await wait_until(lambda: manager.get_task_status("one_time")["status"] == "stopped")

        self.assertEqual(one_time.count, 1)
        await manager.stop_all()

    async def test_manager_initiated_stop_never_restarts(self) -> None:
        manager = fresh_manager()
        runs = Runs()
        manager.add_task("worker", runs, restart_delay=0)
        await manager.start_task("worker")
        await settle()

        self.assertTrue(await manager.stop_task("worker"))
        await asyncio.sleep(0.02)

        status = manager.get_task_status("worker")
        self.assertEqual(status["status"], "stopped")
        self.assertFalse(status["is_alive"])
        self.assertEqual(runs.count, 1)

    async def test_start_task_resets_the_restart_budget_and_replaces_a_running_task(self) -> None:
        manager = fresh_manager()
        runs = Runs(["fail", "wait", "wait"])
        manager.add_task("worker", runs, restart_delay=0)
        with self.assertLogs(LOGGER, level="ERROR"):
            await manager.start_task("worker")
            await wait_until(lambda: manager.get_task_status("worker")["restart_count"] == 1)

        self.assertTrue(await manager.start_task("worker"))
        await settle()

        status = manager.get_task_status("worker")
        self.assertEqual(status["restart_count"], 0)
        self.assertEqual(runs.count, 3)
        await manager.stop_all()

    async def test_manual_restart_counts_against_the_budget(self) -> None:
        manager = fresh_manager()
        runs = Runs()
        manager.add_task("worker", runs, max_restarts=1)
        await manager.start_task("worker")
        await settle()

        self.assertTrue(await manager.restart_task("worker"))
        await settle()
        self.assertEqual(runs.count, 2)
        with self.assertLogs(LOGGER, level="WARNING"):
            self.assertFalse(await manager.restart_task("worker"))
        self.assertEqual(manager.get_task_status("worker")["status"], "error")
        await manager.stop_all()

    async def test_a_start_that_raises_synchronously_is_retried_after_a_full_delay(self) -> None:
        manager = fresh_manager()
        calls = 0

        def factory() -> Any:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise TypeError("bad arguments")

            async def run() -> None:
                raise RuntimeError("boom")

            return run()

        manager.add_task("worker", cast(Any, factory), restart_delay=0, max_restarts=3)
        with self.assertLogs(LOGGER, level="ERROR") as logs:
            await manager.start_task("worker")
            await wait_until(lambda: manager.get_task_status("worker")["status"] == "error" and calls == 4)

        self.assertTrue(any("Restarting task worker failed" in line for line in logs.output))
        self.assertEqual(manager.get_task_status("worker")["restart_count"], 3)

    async def test_callback_errors_are_logged_and_do_not_break_the_manager(self) -> None:
        manager = fresh_manager()
        runs = Runs(["done"])
        manager.add_task("worker", runs, max_restarts=0)

        with (
            patch.object(manager, "_settle", side_effect=KeyError("broken")),
            self.assertLogs(LOGGER, level="ERROR") as logs,
        ):
            await manager.start_task("worker")
            await wait_until(lambda: any("Handling the end of task worker failed" in line for line in logs.output))

        self.assertTrue(await manager.stop_task("worker"))


class LifecycleTest(IsolatedAsyncioTestCase):
    async def test_start_all_skips_running_and_pending_tasks(self) -> None:
        manager = fresh_manager()
        spawned = Runs()
        waiting = Runs(["fail", "wait"])
        idle = Runs()
        manager.spawn(spawned, name="spawned")
        manager.add_task("waiting", waiting, restart_delay=60)
        manager.add_task("idle", idle)
        with self.assertLogs(LOGGER, level="ERROR"):
            await manager.start_task("waiting")
            await settle()
        self.assertEqual(manager.tasks["waiting"].status, TaskStatus.RESTARTING)

        await manager.start_all()
        await settle()

        self.assertTrue(manager.running)
        self.assertEqual((spawned.count, waiting.count, idle.count), (1, 1, 1))
        await manager.stop_all()

    async def test_stop_all_cancels_tasks_and_pending_restarts_and_can_be_started_again(self) -> None:
        manager = fresh_manager()
        runs = Runs(["wait", "fail", "wait"])
        manager.add_task("worker", runs, restart_delay=60)
        spawned = manager.spawn(Runs(), name="spawned")
        await manager.start_all()
        await settle()

        await manager.stop_all()

        self.assertFalse(manager.running)
        self.assertTrue(spawned.cancelled())
        self.assertEqual(manager.get_task_status("worker")["status"], "stopped")
        self.assertEqual(manager.get_task_status("spawned")["status"], "stopped")
        self.assertTrue(await manager.remove_task("spawned"))
        with self.assertLogs(LOGGER, level="ERROR"):
            await manager.start_all()
            await settle()
        self.assertEqual(runs.count, 2)
        self.assertEqual(manager.tasks["worker"].status, TaskStatus.RESTARTING)
        await manager.stop_all()
        self.assertIsNone(manager.tasks["worker"].restart_handle)

    async def test_stop_all_sync_requests_cancellation_without_waiting(self) -> None:
        manager = fresh_manager()
        runs = Runs()
        manager.add_task("worker", runs)
        await manager.start_task("worker")
        task = manager.tasks["worker"].task
        assert task is not None

        manager.stop_all_sync()

        self.assertFalse(manager.running)
        self.assertFalse(task.done())
        await settle()
        self.assertTrue(task.cancelled())
        self.assertEqual(manager.get_task_status("worker")["status"], "stopped")

    async def test_status_reports_live_task_state(self) -> None:
        manager = fresh_manager()
        self.assertEqual(manager.get_task_status("missing"), {})
        manager.add_task("worker", Runs())

        registered = manager.get_task_status("worker")
        self.assertEqual(registered, {"name": "worker", "status": "stopped", "restart_count": 0, "last_restart": 0, "is_alive": False})
        await manager.start_task("worker")
        self.assertTrue(manager.get_task_status("worker")["is_alive"])
        self.assertEqual(set(manager.get_all_status()), {"worker"})
        await manager.remove_task("worker")
        self.assertEqual(manager.get_all_status(), {})


class LockAcrossLoopsTest(TestCase):
    def test_the_singleton_can_serve_consecutive_event_loops(self) -> None:
        manager = fresh_manager()

        async def cycle() -> None:
            manager.add_task("worker", Runs(["done"]), max_restarts=0)
            await manager.start_task("worker")
            await wait_until(lambda: manager.get_task_status("worker")["status"] == "completed")
            await manager.remove_task("worker")

        asyncio.run(cycle())
        asyncio.run(cycle())

        self.assertEqual(manager.get_all_status(), {})

    def test_task_info_defaults_match_add_task(self) -> None:
        info = TaskInfo(name="x", coro_func=Runs())
        self.assertEqual((info.restart_delay, info.max_restarts, info.task_type), (30, -1, TaskType.PERSISTENT))
        self.assertFalse(info.remove_on_failure)


if __name__ == "__main__":
    import unittest

    unittest.main()


class RestartTaskSupervisionTest(TestCase):
    """The restart wrapper must be referenced and its failures reported.

    _launch_restart discarded the task it created. asyncio keeps only a weak reference,
    so CPython may collect it before it runs, and an exception raised before _restart
    reaches _create would appear only as a "never retrieved" warning at shutdown. _create,
    two methods above in the same class, already binds its task and attaches a done
    callback - and db/sqlalchemy/cache.py spells out this exact rule as the reason not to
    use a bare create_task.
    """

    def test_the_restart_task_is_held_and_supervised(self) -> None:
        import inspect

        source = inspect.getsource(BackgroundTaskManager._launch_restart)
        self.assertIn("restart_task_ref", source, "the restart task is created and dropped")
        self.assertIn("add_done_callback", source, "a failure before _create would be silent")
        self.assertIn("restart_task_ref", TaskInfo.__dataclass_fields__)

    def test_a_restart_that_fails_on_its_way_in_is_logged(self) -> None:
        manager = BackgroundTaskManager()
        info = TaskInfo(name="probe", coro_func=lambda: None)

        async def boom() -> None:
            raise RuntimeError("could not even start")

        async def drive() -> None:
            loop = asyncio.get_running_loop()
            task = loop.create_task(boom(), name="probe:restart")
            info.restart_task_ref = task
            try:
                await task
            except RuntimeError:
                pass
            with patch("oldman.tasks.simple.logger") as log:
                manager._on_restart_done(info, task)
            log.error.assert_called_once()
            self.assertIn("probe", str(log.error.call_args))

        asyncio.run(drive())
        self.assertIsNone(info.restart_task_ref, "the reference must be dropped once it is done")
