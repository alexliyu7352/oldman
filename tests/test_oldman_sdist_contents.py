"""Tests for the Oldman source distribution boundary."""

from __future__ import annotations

import copy
import gzip
import hashlib
import importlib.util
import io
import json
import re
import subprocess
import tarfile
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from scripts.release_artifacts import python_distribution_version

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify-sdist-contents.py"


def load_verifier() -> ModuleType:
    """Load the sdist verifier as a module."""
    spec = importlib.util.spec_from_file_location("verify_sdist_contents", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load source distribution verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def archive_root(source_files: dict[str, bytes] | None = None) -> str:
    """Return the sdist root directory Hatchling produces for the frozen (or given) project version."""
    pyproject = source_files["pyproject.toml"].decode() if source_files else (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project = tomllib.loads(pyproject)["project"]
    return f"{project['name']}-{python_distribution_version(project['version'])}"


def core_metadata_fixture(source_files: dict[str, bytes]) -> bytes:
    """Render semantically complete PKG-INFO for a synthetic sdist."""
    project = tomllib.loads(source_files["pyproject.toml"].decode())["project"]
    license_lines = source_files["LICENSE"].decode().splitlines()
    headers = [
        "Metadata-Version: 2.4",
        f"Name: {project['name']}",
        f"Version: {python_distribution_version(project['version'])}",
        f"Summary: {project['description']}",
    ]
    headers.extend(f"Project-URL: {name}, {url}" for name, url in project["urls"].items())
    headers.append(f"License: {license_lines[0]}")
    headers.extend(f"        {line}" for line in license_lines[1:])
    headers.extend(("License-File: LICENSE", f"Requires-Python: {project['requires-python']}"))
    headers.extend(f"Requires-Dist: {dependency}" for dependency in project["dependencies"])
    headers.append("Description-Content-Type: text/markdown")
    return ("\n".join(headers) + "\n\n").encode() + source_files["README.md"]


def write_archive(
    path: Path,
    members: list[str],
    *,
    unsafe_link: str | None = None,
    payloads: dict[str, bytes] | None = None,
    root: str | None = None,
) -> None:
    """Create a small source distribution fixture."""
    root = root or archive_root()
    archive_buffer = io.BytesIO()
    with tarfile.open(fileobj=archive_buffer, mode="w") as archive:
        for name in members:
            payload = (payloads or {}).get(name, b"fixture\n")
            info = tarfile.TarInfo(f"{root}/{name}")
            info.mtime = 1_580_601_600
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        if unsafe_link is not None:
            info = tarfile.TarInfo(f"{root}/{unsafe_link}")
            info.mtime = 1_580_601_600
            info.type = tarfile.SYMTYPE
            info.linkname = "../../outside"
            archive.addfile(info)
    path.write_bytes(gzip.compress(archive_buffer.getvalue(), compresslevel=9, mtime=1_580_601_600))


def rewrite_real_sdist_metadata(source: Path, target: Path) -> None:
    """Tamper root metadata while preserving a structurally valid tar archive."""
    with tarfile.open(source, "r:gz") as input_archive, tarfile.open(target, "w:gz") as output_archive:
        for original in input_archive.getmembers():
            member = copy.copy(original)
            extracted = input_archive.extractfile(original) if original.isfile() else None
            payload = extracted.read() if extracted is not None else None
            if member.name.endswith("/README.md") and payload is not None:
                payload += b"\nforged readme\n"
                member.size = len(payload)
            elif member.name.endswith("/PKG-INFO") and payload is not None:
                payload = payload.replace(b"Name: oldman\n", b"Name: forged-oldman\n", 1)
                member.size = len(payload)
            output_archive.addfile(member, io.BytesIO(payload) if payload is not None else None)


class OldmanSdistContentsTest(unittest.TestCase):
    """Verify source archives exclude workspace consumers and tooling."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.verifier = load_verifier()

    def test_hollow_source_distribution_is_rejected_by_committed_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / f"{archive_root()}.tar.gz"
            write_archive(path, sorted(self.verifier.REQUIRED_PATHS))

            expected = {
                "oldman/__init__.py": hashlib.sha256(b"fixture\n").hexdigest(),
                "oldman/py.typed": hashlib.sha256(b"fixture\n").hexdigest(),
                "oldman/tasks/base.py": hashlib.sha256(b"fixture\n").hexdigest(),
            }
            errors = self.verifier.verify_sdist(path, expected_inventory=expected)

        self.assertIn("source distribution is missing committed source package file: oldman/tasks/base.py", errors)

    def test_complete_source_distribution_inventory_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / f"{archive_root()}.tar.gz"
            members = sorted(self.verifier.REQUIRED_PATHS | {"oldman/tasks/base.py"})
            source_files = self.verifier.release_source_files(ROOT)
            write_archive(
                path,
                members,
                payloads={**source_files, "PKG-INFO": core_metadata_fixture(source_files)},
            )
            expected = {
                name: hashlib.sha256(b"fixture\n").hexdigest()
                for name in members
                if name.startswith("oldman/")
            }

            self.assertEqual(
                [],
                self.verifier.verify_sdist(
                    path,
                    expected_inventory=expected,
                    expected_source_files=source_files,
                ),
            )

    def test_prerelease_root_and_long_member_path_pass(self) -> None:
        """A longer (pre-release) root pushes one migration path past the 100-byte ustar name field;
        the resulting PAX path header is deterministic and must be accepted, and the root uses the PEP 440 form."""
        long_member = "oldman/web/messages/notifications/migrations/4858aab957ee_create_oldman_notification.py"
        source_files = dict(self.verifier.release_source_files(ROOT))
        source_files["pyproject.toml"] = re.sub(
            rb'^version = ".*"$', b'version = "9.9.9-rc.1"', source_files["pyproject.toml"], count=1, flags=re.MULTILINE
        )
        root = archive_root(source_files)
        self.assertEqual("oldman-9.9.9rc1", root)
        members = sorted(self.verifier.REQUIRED_PATHS | {"oldman/tasks/base.py", long_member})
        with patch.object(self.verifier, "release_source_files", return_value=source_files), tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / f"{root}.tar.gz"
            write_archive(path, members, payloads={**source_files, "PKG-INFO": core_metadata_fixture(source_files)}, root=root)
            with tarfile.open(path, "r:gz") as archive:
                self.assertTrue(any(member.pax_headers for member in archive.getmembers()))
            expected = {name: hashlib.sha256(b"fixture\n").hexdigest() for name in members if name.startswith("oldman/")}

            self.assertEqual([], self.verifier.verify_sdist(path, expected_inventory=expected, expected_source_files=source_files))

    def test_unexpected_consumer_and_frontend_sources_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / f"{archive_root()}.tar.gz"
            write_archive(
                path,
                sorted(self.verifier.REQUIRED_PATHS)
                + ["consumer/main.py", "frontend/packages/oldman-web/package.json"],
            )

            errors = self.verifier.verify_sdist(path)

        self.assertIn("Source distribution contains unexpected member: consumer/main.py", errors)
        self.assertTrue(any("frontend/" in error for error in errors))

    def test_sdist_rejects_arbitrary_root_files_and_gitignore(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / f"{archive_root()}.tar.gz"
            write_archive(path, sorted(self.verifier.REQUIRED_PATHS) + [".gitignore", "notes.txt"])

            errors = self.verifier.verify_sdist(path)

        self.assertIn("Source distribution contains unexpected member: .gitignore", errors)
        self.assertIn("Source distribution contains unexpected member: notes.txt", errors)

    def test_sdist_rejects_links_and_traversal_members(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / f"{archive_root()}.tar.gz"
            write_archive(
                path,
                sorted(self.verifier.REQUIRED_PATHS) + ["../escaped.txt"],
                unsafe_link="oldman/link",
            )

            errors = self.verifier.verify_sdist(path)

        self.assertTrue(any("unsafe member path" in error for error in errors))
        self.assertTrue(any("unsafe member type" in error for error in errors))

    def test_sdist_arguments_require_exact_files_and_preserve_explicit_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "oldman-1.0.0.tar.gz"
            second = root / "oldman-2.0.0.tar.gz"
            first.touch()
            second.touch()

            self.assertEqual(
                [second.resolve(), first.resolve()],
                self.verifier.resolve_sdist_args([str(second), str(first)]),
            )
            for value in (
                root / "*.tar.gz",
                root / "oldman-1.0.0*.tar.gz",
                root / "oldman-?.tar.gz",
                root / "oldman-[12].tar.gz",
            ):
                with self.subTest(value=value), self.assertRaises(RuntimeError):
                    self.verifier.resolve_sdist_args([str(value)])

            wrong_suffix = root / "oldman.zip"
            wrong_suffix.touch()
            directory = root / "directory.tar.gz"
            directory.mkdir()
            symlink = root / "linked.tar.gz"
            symlink.symlink_to(first)
            for value in (root / "missing.tar.gz", wrong_suffix, directory, symlink):
                with self.subTest(value=value), self.assertRaises(RuntimeError):
                    self.verifier.resolve_sdist_args([str(value)])

    def test_real_hatch_sdist_excludes_gitignore_and_binds_root_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            subprocess.run(
                ["uv", "build", "--sdist", "--out-dir", str(output)],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            archive = next(output.glob("*.tar.gz"))
            source_files = self.verifier.release_source_files(ROOT)
            with tarfile.open(archive, "r:gz") as built:
                names = {member.name for member in built.getmembers()}
                self.assertFalse(any(name.endswith("/.gitignore") for name in names))
                prefix = next(name.split("/", 1)[0] for name in names)
                self.assertIn(f"{prefix}/LICENSES/aiocache-BSD-3-Clause.txt", names)
                self.assertIn(f"{prefix}/LICENSES/flag-icons-LICENSE.txt", names)
                self.assertIn(f"{prefix}/oldman/db/migrations/templates/env.py", names)
                self.assertIn(f"{prefix}/oldman/db/migrations/templates/script.py.mako", names)
                self.assertIn(f"{prefix}/oldman/auth/migrations/__init__.py", names)
                self.assertIn(
                    f"{prefix}/oldman/web/messages/notifications/migrations/4858aab957ee_create_oldman_notification.py",
                    names,
                )
                self.assertIn(
                    f"{prefix}/oldman/web/templates/oldman/messages/notifications/center_content.html",
                    names,
                )
                self.assertIn(
                    f"{prefix}/oldman/web/templates/oldman/messages/notifications/topbar_fragment.html",
                    names,
                )
                for locale in ("zh_Hans", "zh_Hant"):
                    self.assertIn(
                        f"{prefix}/oldman/web/messages/notifications/locales/{locale}/LC_MESSAGES/messages.mo",
                        names,
                    )
                    self.assertIn(
                        f"{prefix}/oldman/web/messages/notifications/locales/{locale}/LC_MESSAGES/messages.po",
                        names,
                    )
                self.assertIn(
                    f"{prefix}/oldman/web/messages/notifications/locales/messages.pot",
                    names,
                )
                auth_revisions = {
                    name
                    for name in names
                    if name.startswith(f"{prefix}/oldman/auth/migrations/")
                    and name.endswith(".py")
                    and not name.endswith("/__init__.py")
                }
                self.assertEqual(len(auth_revisions), 1)
            self.assertEqual([], self.verifier.verify_sdist(archive, expected_source_files=source_files))

            extracted = output / "extracted"
            with tarfile.open(archive, "r:gz") as built:
                built.extractall(extracted, filter="data")
            rebuilt_output = output / "rebuilt"
            rebuilt_output.mkdir()
            subprocess.run(
                ["uv", "build", "--sdist", "--out-dir", str(rebuilt_output)],
                cwd=extracted / archive_root(),
                check=True,
                capture_output=True,
                text=True,
            )
            rebuilt = rebuilt_output / archive.name
            self.assertEqual([], self.verifier.verify_sdist(rebuilt, expected_source_files=source_files))

            tampered_dir = output / "tampered"
            tampered_dir.mkdir()
            tampered = tampered_dir / archive.name
            rewrite_real_sdist_metadata(archive, tampered)
            errors = self.verifier.verify_sdist(tampered, expected_source_files=source_files)

        self.assertIn("Source distribution README.md does not match frozen source", errors)
        self.assertIn("Source distribution PKG-INFO Name does not match frozen pyproject.toml", errors)

    def test_root_package_script_builds_and_checks_both_python_artifacts(self) -> None:
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        scripts = package["scripts"]
        wrapper = ROOT / "scripts" / "verify-current-release-python-package.py"
        wrapper_source = wrapper.read_text(encoding="utf-8")

        self.assertIn("uv build --package oldman", scripts["build:python"])
        self.assertIn("verify-current-release-python-package.py", scripts["verify:python-package"])
        self.assertIn("verify-wheel-contents.py", wrapper_source)
        self.assertIn("verify-sdist-contents.py", wrapper_source)
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(
            "scripts/hatch_sdist_hook.py",
            pyproject["tool"]["hatch"]["build"]["targets"]["sdist"]["hooks"]["custom"]["path"],
        )


if __name__ == "__main__":
    unittest.main()
