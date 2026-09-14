"""Tests for the single Oldman release-version authority."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync-release-version.py"


class ReleaseVersionSyncTest(unittest.TestCase):
    """Verify generated release copies cannot become independent authorities."""

    def make_fixture(self, root: Path, *, generated_version: str = "2.3.4", lock_version: str = "2.3.4") -> None:
        """Create the minimal release metadata tree consumed by the synchronizer."""
        (root / "pyproject.toml").write_text('[project]\nname = "oldman"\nversion = "2.3.4"\n', encoding="utf-8")
        (root / "uv.lock").write_text(
            f'version = 1\n\n[[package]]\nname = "oldman"\nversion = "{lock_version}"\nsource = {{ editable = "." }}\n',
            encoding="utf-8",
        )
        for relative, name in (
            (Path("package.json"), "oldman"),
            (Path("frontend/apps/admin/package.json"), "oldman-admin"),
            (Path("frontend/packages/oldman-web/package.json"), "oldman-web"),
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"name": name, "version": generated_version}, indent=2) + "\n", encoding="utf-8")

        python_version = root / "oldman" / "version.py"
        python_version.parent.mkdir(parents=True)
        python_version.write_text(f'__VERSION__ = "{generated_version}"\n', encoding="utf-8")
        web_core = root / "frontend" / "packages" / "oldman-web" / "src" / "core" / "index.ts"
        web_core.parent.mkdir(parents=True)
        web_core.write_text(f'export const OLDMAN_WEB_VERSION = "{generated_version}";\n', encoding="utf-8")

        scaffold = root / "oldman" / "scaffolds" / "project" / "cli_app" / "pyproject.toml.tpl"
        scaffold.parent.mkdir(parents=True)
        scaffold.write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")

    def run_sync(self, root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        """Run the synchronizer against an isolated fixture."""
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(root), *arguments],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_check_accepts_generated_copies_from_root_pyproject(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_fixture(root)

            completed = self.run_sync(root)

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("2.3.4 verified", completed.stdout)

    def test_repository_generated_copies_and_uv_lock_are_current(self) -> None:
        completed = self.run_sync(ROOT)

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("verified from pyproject.toml", completed.stdout)

    def test_check_rejects_coordinated_generated_and_lock_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_fixture(root, generated_version="9.9.9", lock_version="9.9.9")

            completed = self.run_sync(root)

        self.assertEqual(1, completed.returncode)
        self.assertIn("expected version 2.3.4, found 9.9.9", completed.stderr)
        self.assertIn("expected editable oldman version 2.3.4, found 9.9.9", completed.stderr)

    def test_write_repairs_generated_copies_but_not_consumer_project_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_fixture(root, generated_version="1.0.0")
            scaffold = root / "oldman" / "scaffolds" / "project" / "cli_app" / "pyproject.toml.tpl"

            written = self.run_sync(root, "--write")
            checked = self.run_sync(root)

            self.assertEqual("0.1.0", scaffold.read_text(encoding="utf-8").split('"')[1])
            for relative in (
                Path("package.json"),
                Path("frontend/apps/admin/package.json"),
                Path("frontend/packages/oldman-web/package.json"),
            ):
                with self.subTest(relative=relative):
                    self.assertEqual("2.3.4", json.loads((root / relative).read_text(encoding="utf-8"))["version"])
            self.assertIn('__VERSION__ = "2.3.4"', (root / "oldman" / "version.py").read_text(encoding="utf-8"))
            self.assertIn(
                'OLDMAN_WEB_VERSION = "2.3.4"',
                (root / "frontend" / "packages" / "oldman-web" / "src" / "core" / "index.ts").read_text(encoding="utf-8"),
            )

        self.assertEqual(0, written.returncode, written.stderr)
        self.assertEqual(0, checked.returncode, checked.stderr)

    def test_check_rejects_stale_uv_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_fixture(root, lock_version="2.3.3")

            completed = self.run_sync(root)

        self.assertEqual(1, completed.returncode)
        self.assertIn("expected editable oldman version 2.3.4, found 2.3.3", completed.stderr)

    def test_version_authority_rejects_semver_that_changes_python_release_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_fixture(root)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "oldman"\nversion = "2.3.4-1"\n',
                encoding="utf-8",
            )

            completed = self.run_sync(root)

        self.assertEqual(1, completed.returncode)
        self.assertIn("prerelease semantics must agree", completed.stderr)

    def test_version_authority_accepts_shared_prerelease(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_fixture(root, generated_version="2.3.4-alpha.1", lock_version="2.3.4a1")
            (root / "pyproject.toml").write_text(
                '[project]\nname = "oldman"\nversion = "2.3.4-alpha.1"\n',
                encoding="utf-8",
            )

            completed = self.run_sync(root)

        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_version_authority_rejects_build_metadata_used_by_generated_minimum_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_fixture(root)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "oldman"\nversion = "2.3.4+build.7"\n',
                encoding="utf-8",
            )

            completed = self.run_sync(root)

        self.assertEqual(1, completed.returncode)
        self.assertIn("build metadata is unsupported", completed.stderr)

    def test_package_workflows_enforce_version_gate(self) -> None:
        root_package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        web_package = json.loads((ROOT / "frontend" / "packages" / "oldman-web" / "package.json").read_text(encoding="utf-8"))
        scripts = root_package["scripts"]

        self.assertEqual("uv run python3 scripts/sync-release-version.py --write", scripts["version:sync"])
        self.assertEqual("uv run python3 scripts/sync-release-version.py", scripts["verify:version"])
        for script_name in ("build", "build:python", "pack:web"):
            with self.subTest(script_name=script_name):
                self.assertTrue(scripts[script_name].startswith("pnpm verify:version && "))
        self.assertIn("pnpm -C ../../.. verify:version", web_package["scripts"]["prepack"])


if __name__ == "__main__":
    unittest.main()
