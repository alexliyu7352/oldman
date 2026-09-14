"""Contracts for the exact current-release Python package wrapper."""

from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-current-release-python-package.py"


def load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_current_release_python_package", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CurrentReleasePythonPackageGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gate = load_gate()

    def test_artifact_paths_are_exact_and_follow_the_pyproject_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            wheel, sdist = self.gate.python_release_artifact_paths(root, "2.4.6")

            self.assertEqual((root / "dist" / "oldman-2.4.6-py3-none-any.whl").resolve(), wheel)
            self.assertEqual((root / "dist" / "oldman-2.4.6.tar.gz").resolve(), sdist)
            self.assertNotIn("*", str(wheel))
            self.assertNotIn("*", str(sdist))

    def test_prerelease_uses_python_distribution_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            wheel, sdist = self.gate.python_release_artifact_paths(root, "1.0.0-alpha.1")

            self.assertEqual((root / "dist" / "oldman-1.0.0a1-py3-none-any.whl").resolve(), wheel)
            self.assertEqual((root / "dist" / "oldman-1.0.0a1.tar.gz").resolve(), sdist)

    def test_stale_dist_files_cannot_change_selected_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dist = root / "dist"
            dist.mkdir()
            (dist / "oldman-1.9.9-py3-none-any.whl").touch()
            (dist / "oldman-1.9.9.tar.gz").touch()

            wheel, sdist = self.gate.python_release_artifact_paths(root, "2.0.0")

            self.assertEqual("oldman-2.0.0-py3-none-any.whl", wheel.name)
            self.assertEqual("oldman-2.0.0.tar.gz", sdist.name)

    def test_every_verifier_receives_only_explicit_absolute_paths(self) -> None:
        wheel = Path("/tmp/release/oldman-3.1.4-py3-none-any.whl")
        sdist = Path("/tmp/release/oldman-3.1.4.tar.gz")
        source_root = Path("/tmp/repository")
        source_revision = "a" * 40
        interpreters = {
            "3.12": Path("/opt/python/3.12/bin/python"),
            "3.13": Path("/opt/python/3.13/bin/python"),
        }

        commands = self.gate.verification_commands(
            wheel,
            sdist,
            source_root=source_root,
            source_revision=source_revision,
            interpreters=interpreters,
        )
        rendered = [command for command, _log_name, _timeout in commands]

        self.assertEqual(4, len(rendered))
        self.assertIn(str(wheel), rendered[0])
        self.assertIn(str(sdist), rendered[1])
        self.assertIn(str(wheel), rendered[2])
        self.assertIn(str(sdist), rendered[2])
        self.assertIn(str(wheel), rendered[3])
        self.assertTrue(all("*" not in argument for command in rendered for argument in command))
        for command in rendered[:2]:
            self.assertIn(str(source_root), command)
            self.assertIn(source_revision, command)
        self.assertIn("verify-python-package-install.py", " ".join(rendered[2]))
        self.assertEqual(2, rendered[2].count("--python"))
        self.assertTrue(all(str(path) in rendered[2] for path in interpreters.values()))
        self.assertIn("verify-installed-wheel-admin-browser.py", " ".join(rendered[3]))
        self.assertNotIn("--python", rendered[3])

    def test_runtime_matrix_matches_the_declared_python_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "oldman"\nversion = "1.0.0"\nrequires-python = ">=3.12, <3.15"\n',
                encoding="utf-8",
            )

            self.assertEqual(("3.12", "3.13", "3.14"), self.gate.declared_supported_python_minors(root))

    def test_runtime_matrix_rejects_an_unverified_declared_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "oldman"\nversion = "1.0.0"\nrequires-python = ">=3.12, <3.16"\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "matrix must be updated"):
                self.gate.declared_supported_python_minors(root)

    def test_parent_gate_can_bind_an_exact_release_interpreter(self) -> None:
        minor = f"{self.gate.sys.version_info.major}.{self.gate.sys.version_info.minor}"
        executable = Path(self.gate.sys.executable).resolve()
        environment = {f"OLDMAN_RELEASE_PYTHON_{minor.replace('.', '_')}": str(executable)}
        with (
            mock.patch.object(self.gate, "interpreter_minor", return_value=minor),
            mock.patch.object(self.gate.subprocess, "run") as run,
        ):
            resolved = self.gate.resolve_python_interpreters((minor,), cwd=ROOT, environment=environment)

        self.assertEqual({minor: executable.resolve()}, resolved)
        run.assert_not_called()

    def test_missing_exact_artifact_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "oldman-2.0.0.tar.gz"
            with self.assertRaisesRegex(RuntimeError, "exact path"):
                self.gate.require_built_artifact(missing, label="source distribution")

    def test_existing_artifact_requires_the_parent_gate_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "oldman.whl"
            artifact.write_bytes(b"reviewed artifact")
            expected = hashlib.sha256(artifact.read_bytes()).hexdigest()

            self.assertEqual(
                expected,
                self.gate.require_expected_artifact_sha256(artifact, expected, label="wheel"),
            )
            with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                self.gate.require_expected_artifact_sha256(artifact, "0" * 64, label="wheel")
            with self.assertRaisesRegex(RuntimeError, "requires one lowercase SHA-256"):
                self.gate.require_expected_artifact_sha256(artifact, None, label="wheel")

if __name__ == "__main__":
    unittest.main()
