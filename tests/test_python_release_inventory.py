"""Tests for committed and archived Python package inventories."""

from __future__ import annotations

import io
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.python_release_inventory import (
    committed_oldman_inventory,
    compare_package_inventories,
    inventory_digest,
    require_clean_oldman_tree,
    sdist_oldman_inventory,
    sha256_bytes,
    wheel_oldman_inventory,
)


def git(root: Path, *args: str) -> None:
    completed = subprocess.run(
        ("git", "-C", str(root), *args),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr)


def write_sdist(path: Path, files: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, payload in files.items():
            info = tarfile.TarInfo(f"oldman-1.2.3/{name}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


class PythonReleaseInventoryTest(unittest.TestCase):
    def create_repository(self, root: Path) -> dict[str, bytes]:
        files = {
            "oldman/__init__.py": b'__version__ = "1.2.3"\n',
            "oldman/tasks/base.py": b"class BaseTask:\n    pass\n",
        }
        for name, payload in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        git(root, "init", "-q")
        git(root, "add", "oldman")
        git(root, "-c", "user.name=Oldman Gate", "-c", "user.email=gate@example.invalid", "commit", "-qm", "fixture")
        return files

    def test_committed_inventory_hashes_every_oldman_blob(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = self.create_repository(root)

            inventory = committed_oldman_inventory(root)

        expected = {name: sha256_bytes(payload) for name, payload in files.items()}
        self.assertEqual(expected, inventory.files)
        self.assertEqual(inventory_digest(expected), inventory.digest)
        self.assertEqual(40, len(inventory.revision))

    def test_clean_tree_guard_rejects_tracked_and_untracked_package_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_repository(root)
            require_clean_oldman_tree(root)

            (root / "oldman" / "tasks" / "base.py").write_text("changed = True\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "clean commit"):
                require_clean_oldman_tree(root)

            (root / "oldman" / "tasks" / "base.py").write_bytes(b"class BaseTask:\n    pass\n")
            (root / "oldman" / "new_module.py").write_text("value = 1\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "new_module.py"):
                require_clean_oldman_tree(root)

    def test_wheel_and_sdist_readers_preserve_exact_file_sets_and_content(self) -> None:
        files = {
            "oldman/__init__.py": b"value = 1\n",
            "oldman/tasks/base.py": b"class BaseTask: ...\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wheel = root / "oldman.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                for name, payload in files.items():
                    archive.writestr(name, payload)
            sdist = root / "oldman.tar.gz"
            write_sdist(sdist, files)

            wheel_inventory = wheel_oldman_inventory(wheel)
            sdist_inventory = sdist_oldman_inventory(sdist)

        expected = {name: sha256_bytes(payload) for name, payload in files.items()}
        self.assertEqual(expected, wheel_inventory)
        self.assertEqual(expected, sdist_inventory)
        self.assertEqual(
            [],
            compare_package_inventories(
                wheel_inventory,
                sdist_inventory,
                expected_label="wheel",
                actual_label="sdist",
            ),
        )

    def test_inventory_comparison_rejects_missing_extra_and_rewritten_files(self) -> None:
        errors = compare_package_inventories(
            {
                "oldman/__init__.py": sha256_bytes(b"source\n"),
                "oldman/tasks/base.py": sha256_bytes(b"task\n"),
            },
            {
                "oldman/__init__.py": sha256_bytes(b"rewritten\n"),
                "oldman/fake.py": sha256_bytes(b"fake\n"),
            },
            expected_label="committed source",
            actual_label="wheel",
        )

        self.assertTrue(any("missing" in error and "tasks/base.py" in error for error in errors))
        self.assertTrue(any("unexpected" in error and "fake.py" in error for error in errors))
        self.assertTrue(any("content differs" in error and "__init__.py" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
