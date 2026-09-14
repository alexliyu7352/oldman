"""Contracts for the deterministic current-release scaffold matrix wrapper."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-current-release-scaffold-matrix.py"


def load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_current_release_scaffold_matrix", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CurrentReleaseScaffoldMatrixGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gate = load_gate()

    def test_version_comes_only_from_root_pyproject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[project]\nname = "oldman"\nversion = "1.2.3"\n', encoding="utf-8")

            self.assertEqual("1.2.3", self.gate.authoritative_version(root))

            (root / "pyproject.toml").write_text('[project]\nname = "oldman"\nversion = "latest"\n', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "SemVer"):
                self.gate.authoritative_version(root)

    def test_artifact_paths_are_exact_and_versioned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            wheel, npm_tarball = self.gate.release_artifact_paths(root, "2.4.6")

            self.assertEqual((root / "dist" / "oldman-2.4.6-py3-none-any.whl").resolve(), wheel)
            self.assertEqual(
                (root / "frontend" / "packages" / "oldman-web" / "oldman-web-2.4.6.tgz").resolve(),
                npm_tarball,
            )
            self.assertNotIn("*", str(wheel))
            self.assertNotIn("*", str(npm_tarball))

    def test_prerelease_uses_normalized_wheel_and_original_npm_semver(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            wheel, npm_tarball = self.gate.release_artifact_paths(root, "1.0.0-alpha.1")

            self.assertEqual((root / "dist" / "oldman-1.0.0a1-py3-none-any.whl").resolve(), wheel)
            self.assertEqual(
                (root / "frontend" / "packages" / "oldman-web" / "oldman-web-1.0.0-alpha.1.tgz").resolve(),
                npm_tarball,
            )

    def test_each_run_gets_a_distinct_persistent_evidence_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "evidence"

            first = self.gate.create_evidence_directory(parent, "1.2.3")
            second = self.gate.create_evidence_directory(parent, "1.2.3")

            self.assertNotEqual(first, second)
            self.assertEqual(parent.resolve(), first.parent)
            self.assertEqual(parent.resolve(), second.parent)
            self.assertEqual([], list(first.iterdir()))
            self.assertEqual([], list(second.iterdir()))

    def test_wrapper_uses_the_existing_release_build_entrypoints(self) -> None:
        self.assertEqual(
            (("pnpm", "build:python"), ("pnpm", "pack:web")),
            self.gate.build_commands(),
        )

    def test_missing_exact_artifact_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "oldman-1.2.3-py3-none-any.whl"
            with self.assertRaisesRegex(RuntimeError, "exact path"):
                self.gate.require_built_artifact(missing, label="wheel")

    def test_wrapper_invokes_matrix_with_only_absolute_explicit_artifacts(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('"--wheel",\n                str(wheel)', source)
        self.assertIn('"--npm-tarball",\n                str(npm_tarball)', source)
        self.assertIn('"--evidence-dir",\n                str(matrix_evidence)', source)
        self.assertNotIn("glob(", source)
        self.assertNotIn("latest", source)

if __name__ == "__main__":
    unittest.main()
