"""Verify the public boundary between process execution and task management."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from oldman.processes import (
    AsyncProcessManager,
    ManagedSubprocess,
    ProcessTimeoutError,
    create_subprocess_exec,
)
from oldman.processes.executor import (
    AsyncProcessManager as ExecutorAsyncProcessManager,
)
from oldman.processes.executor import (
    ProcessTimeoutError as ExecutorProcessTimeoutError,
)
from oldman.processes.subprocess import ManagedSubprocess as ModuleManagedSubprocess
from oldman.processes.subprocess import (
    create_subprocess_exec as module_create_subprocess_exec,
)
from oldman.tasks import BaseManager

ROOT = Path(__file__).resolve().parents[1]


class OldmanProcessBoundaryTest(unittest.TestCase):
    """Keep process primitives separate from application and task domains."""

    def test_public_process_exports_are_canonical_objects(self) -> None:
        """The aggregate must not wrap or duplicate either implementation."""
        self.assertIs(AsyncProcessManager, ExecutorAsyncProcessManager)
        self.assertIs(ProcessTimeoutError, ExecutorProcessTimeoutError)
        self.assertIs(ManagedSubprocess, ModuleManagedSubprocess)
        self.assertIs(create_subprocess_exec, module_create_subprocess_exec)

    def test_removed_process_modules_have_no_compatibility_shims(self) -> None:
        """Old utility and runtime placements must disappear completely."""
        self.assertIsNone(importlib.util.find_spec("oldman.utils.process"))
        self.assertIsNone(importlib.util.find_spec("oldman.runtime.subprocess"))

    def test_task_manager_remains_in_the_task_domain(self) -> None:
        """A persistent task worker manager is not a low-level process primitive."""
        self.assertEqual(BaseManager.__module__, "oldman.tasks.manager")

    def test_production_code_does_not_reference_removed_paths(self) -> None:
        """Moved process capabilities cannot survive through deferred imports."""
        forbidden = ("oldman.runtime.subprocess", "oldman.utils.process")
        offenders: list[str] = []
        for path in (ROOT / "oldman").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if any(value in source for value in forbidden):
                offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
