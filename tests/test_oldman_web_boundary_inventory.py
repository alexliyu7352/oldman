"""Oldman repository and Web package boundary tests."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify-oldman-web-boundary-inventory.py"


def load_verifier() -> ModuleType:
    """Load the verifier script as a module."""
    spec = importlib.util.spec_from_file_location("verify_oldman_web_boundary_inventory", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load oldman-web boundary verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class OldmanWebBoundaryInventoryTest(unittest.TestCase):
    """Verify repository ownership stays concrete and enforceable."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.verifier = load_verifier()

    def test_inventory_verifier_accepts_current_repository(self) -> None:
        self.assertEqual([], self.verifier.verify_repository_boundaries())

    def test_stable_ownership_boundaries_are_declared(self) -> None:
        expected = {
            "oldman/": "Python 框架",
            "frontend/packages/oldman-web/": "浏览器框架",
            "frontend/apps/admin/": "内置 Admin 前端",
            "tests/": "框架测试",
            "scripts/": "框架开发与发布门禁",
        }

        actual = {entry.path: entry.owner for entry in self.verifier.BOUNDARIES}
        self.assertEqual(expected, actual)

    def test_legacy_mixed_roots_are_absent(self) -> None:
        for path in self.verifier.FORBIDDEN_ROOT_PATHS:
            self.assertFalse((ROOT / path).exists(), path)

    def test_consumer_boundary_scans_production_sources_but_not_test_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            production = root / "runtime.ts"
            unit_test = root / "runtime.test.ts"
            test_fixture = root / "__tests__" / "package-metadata.ts"
            test_fixture.parent.mkdir()
            production.write_text("export const value = 1;\n", encoding="utf-8")
            unit_test.write_text("export const fixture = 1;\n", encoding="utf-8")
            test_fixture.write_text("export const fixture = 2;\n", encoding="utf-8")

            self.assertEqual([production], self.verifier.source_files(root))

if __name__ == "__main__":
    unittest.main()
