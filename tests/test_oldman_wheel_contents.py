"""Preflight tests for Oldman wheel contents."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import io
import json
import re
import stat
import subprocess
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.release_artifacts import python_distribution_version

ROOT = Path(__file__).resolve().parents[1]
VERIFY_WHEEL_SCRIPT = ROOT / "scripts" / "verify-wheel-contents.py"


def load_verify_wheel_module():
    """Load the wheel verifier script as a module."""
    spec = importlib.util.spec_from_file_location("verify_wheel_contents", VERIFY_WHEEL_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load verify-wheel-contents.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def core_metadata_fixture(source_files: dict[str, bytes]) -> bytes:
    """Render semantically complete core metadata for a synthetic wheel."""
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
    headers.extend(
        (
            "License-File: LICENSE",
            f"Requires-Python: {project['requires-python']}",
        )
    )
    headers.extend(f"Requires-Dist: {dependency}" for dependency in project["dependencies"])
    headers.append("Description-Content-Type: text/markdown")
    return ("\n".join(headers) + "\n\n").encode() + source_files["README.md"]


def write_closed_wheel(
    path: Path,
    module,
    *,
    extra_files: dict[str, bytes] | None = None,
    bad_record_member: str | None = None,
    symlink: str | None = None,
    writable_member: str | None = None,
) -> dict[str, str]:
    """Build a small, internally closed wheel fixture."""
    manifest: dict[str, object] = {"src/main.ts": {"file": "assets/main.js"}}
    for index, name in enumerate(module.REQUIRED_ADMIN_DYNAMIC_ENTRIES):
        manifest[f"src/dynamic-{index}.ts"] = {
            "file": "assets/main.js",
            "isDynamicEntry": True,
            "name": name,
        }
    files: dict[str, bytes] = {
        "oldman/__init__.py": b"fixture\n",
        "oldman/py.typed": b"",
        f"{module.ADMIN_STATIC_PREFIX}.vite/manifest.json": json.dumps(
            manifest
        ).encode(),
        f"{module.ADMIN_STATIC_PREFIX}assets/main.js": b"export {};\n",
    }
    for name in module.REQUIRED_FILES:
        files.setdefault(name, b"fixture\n")
    for prefix in (*module.REQUIRED_DIR_PREFIXES, *module.REQUIRED_SCAFFOLD_PREFIXES):
        files.setdefault(f"{prefix}fixture.txt", b"fixture\n")
    source_files = module.release_source_files(ROOT)
    project = module.project_table(source_files)
    dist_info = f"{project['name']}-{python_distribution_version(project['version'])}.dist-info"
    entry_points = "[console_scripts]\n" + "".join(
        f"{name} = {target}\n" for name, target in project["scripts"].items()
    )
    files.update(
        {
            f"{dist_info}/METADATA": core_metadata_fixture(source_files),
            f"{dist_info}/WHEEL": (
                b"Wheel-Version: 1.0\nGenerator: hatchling 1.31.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
            ),
            f"{dist_info}/entry_points.txt": entry_points.encode(),
            f"{dist_info}/licenses/LICENSE": source_files["LICENSE"],
        }
    )
    files.update(extra_files or {})
    record_name = f"{dist_info}/RECORD"
    rows: list[list[str]] = []
    for name, payload in sorted(files.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()
        if name == bad_record_member:
            digest = "invalid"
        rows.append([name, f"sha256={digest}", str(len(payload))])
    rows.append([record_name, "", ""])
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(rows)
    files[record_name] = output.getvalue().encode()

    def canonical_info(name: str) -> zipfile.ZipInfo:
        info = zipfile.ZipInfo(name, date_time=module.WHEEL_DATE_TIME)
        info.create_system = 3
        info.create_version = 20
        info.extract_version = 20
        info.compress_type = zipfile.ZIP_DEFLATED
        file_type = stat.S_IFREG if name.startswith("oldman/") else 0
        info.external_attr = (file_type | 0o644) << 16
        return info

    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in files.items():
            info = canonical_info(name)
            if name == writable_member:
                info.external_attr = (stat.S_IFREG | 0o666) << 16
            archive.writestr(info, payload)
        if symlink is not None:
            info = canonical_info(symlink)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, b"target")
    return {
        name: hashlib.sha256(payload).hexdigest()
        for name, payload in files.items()
        if name.startswith("oldman/")
    }


def rewrite_real_wheel_with_valid_record(source: Path, target: Path) -> None:
    """Tamper metadata and mode while keeping RECORD internally consistent."""
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        payloads = {info.filename: archive.read(info) for info in infos}
    metadata_name = next(name for name in payloads if name.endswith(".dist-info/METADATA"))
    record_name = next(name for name in payloads if name.endswith(".dist-info/RECORD"))
    payloads[metadata_name] = payloads[metadata_name].replace(b"Name: oldman\n", b"Name: forged-oldman\n", 1)
    rows: list[list[str]] = []
    for name, payload in sorted(payloads.items()):
        if name == record_name:
            continue
        digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()
        rows.append([name, f"sha256={digest}", str(len(payload))])
    rows.append([record_name, "", ""])
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(rows)
    payloads[record_name] = output.getvalue().encode()

    writable_name = "oldman/__init__.py"
    with zipfile.ZipFile(target, "w") as archive:
        for info in infos:
            if info.filename == writable_name:
                info.external_attr = (stat.S_IFREG | 0o666) << 16
            archive.writestr(info, payloads[info.filename])


class OldmanWheelContentsPreflightTest(unittest.TestCase):
    """Verify source package data that must later be present in the built wheel."""

    def test_package_data_sources_exist(self) -> None:
        """Templates, Admin static assets and scaffolds must exist before wheel build."""
        required_paths = [
            ROOT / "oldman" / "web" / "templates" / "oldman" / "forms" / "default",
            ROOT / "oldman" / "apps" / "admin" / "templates",
            ROOT
            / "oldman"
            / "apps"
            / "admin"
            / "static"
            / "oldman"
            / "admin"
            / ".vite"
            / "manifest.json",
            ROOT / "oldman" / "scaffolds" / "project" / "dashboard",
            ROOT / "oldman" / "scaffolds" / "app" / "dashboard_app",
            ROOT / "oldman" / "auth" / "migrations" / "__init__.py",
            ROOT
            / "oldman"
            / "web"
            / "messages"
            / "notifications"
            / "locales"
            / "messages.pot",
            ROOT
            / "oldman"
            / "web"
            / "messages"
            / "notifications"
            / "locales"
            / "zh_Hans"
            / "LC_MESSAGES"
            / "messages.mo",
            ROOT
            / "oldman"
            / "web"
            / "messages"
            / "notifications"
            / "locales"
            / "zh_Hant"
            / "LC_MESSAGES"
            / "messages.mo",
            ROOT
            / "oldman"
            / "web"
            / "templates"
            / "oldman"
            / "messages"
            / "notifications"
            / "center_content.html",
            ROOT
            / "oldman"
            / "web"
            / "templates"
            / "oldman"
            / "messages"
            / "notifications"
            / "topbar_fragment.html",
        ]

        for path in required_paths:
            self.assertTrue(path.exists(), path)
        self.assertTrue((ROOT / "oldman" / "db" / "migrations" / "templates" / "env.py").is_file())
        self.assertTrue((ROOT / "oldman" / "db" / "migrations" / "templates" / "script.py.mako").is_file())
        auth_revisions = tuple(
            path
            for path in (ROOT / "oldman" / "auth" / "migrations").glob("*.py")
            if path.name != "__init__.py"
        )
        self.assertEqual(len(auth_revisions), 1)
        self.assertFalse((ROOT / "oldman" / "dashboard").exists())
        self.assertFalse((ROOT / "frontend" / "scaffolds").exists())

    def test_admin_manifest_references_packaged_files(self) -> None:
        """Admin manifest references must point to existing static files."""
        static_dir = (
            ROOT
            / "oldman"
            / "apps"
            / "admin"
            / "static"
            / "oldman"
            / "admin"
        )
        manifest = json.loads((static_dir / ".vite" / "manifest.json").read_text(encoding="utf-8"))

        self.assertIn("src/main.ts", manifest)
        dynamic_entries = {
            entry.get("name")
            for entry in manifest.values()
            if isinstance(entry, dict) and entry.get("isDynamicEntry") is True
        }
        self.assertTrue({"date-time-picker", "dropdown", "table-filter-form"}.issubset(dynamic_entries))
        for entry in manifest.values():
            if not isinstance(entry, dict):
                continue
            file_name = entry.get("file")
            if file_name:
                self.assertTrue((static_dir / file_name).exists(), file_name)
            for css_file in entry.get("css", []) or []:
                self.assertTrue((static_dir / css_file).exists(), css_file)

    def test_admin_static_filenames_are_neutral(self) -> None:
        """Admin packaged asset filenames must not contain demo or business tokens."""
        forbidden = ("epg", "channels", "catalog", "logo", "match-decisions", "component-coverage")
        static_root = (
            ROOT
            / "oldman"
            / "apps"
            / "admin"
            / "static"
            / "oldman"
            / "admin"
        )
        for path in static_root.rglob("*"):
            if path.is_file():
                lower = path.relative_to(static_root).as_posix().lower()
                for token in forbidden:
                    self.assertNotIn(token, lower)

    def test_wheel_verifier_defines_required_checks(self) -> None:
        """The wheel verifier must check real wheel package data, not just source files."""
        module = load_verify_wheel_module()

        self.assertIn(
            "oldman/apps/admin/static/oldman/admin/",
            module.REQUIRED_DIR_PREFIXES,
        )
        self.assertIn("oldman/web/templates/oldman/forms/default/", module.REQUIRED_DIR_PREFIXES)
        self.assertIn("oldman/py.typed", module.REQUIRED_FILES)
        self.assertIn(
            "oldman/web/messages/notifications/migrations/4858aab957ee_create_oldman_notification.py",
            module.REQUIRED_FILES,
        )
        self.assertIn(
            "oldman/web/messages/notifications/locales/zh_Hans/LC_MESSAGES/messages.mo",
            module.REQUIRED_FILES,
        )
        self.assertIn(
            "oldman/web/templates/oldman/messages/notifications/center_content.html",
            module.REQUIRED_FILES,
        )
        self.assertIn("oldman/scaffolds/project/dashboard/", module.REQUIRED_SCAFFOLD_PREFIXES)
        self.assertIn("oldman/scaffolds/app/dashboard_app/", module.REQUIRED_SCAFFOLD_PREFIXES)
        self.assertIn("epg", module.FORBIDDEN_ADMIN_ASSET_TOKENS)
        self.assertNotIn("date-time-picker", module.FORBIDDEN_ADMIN_ASSET_TOKENS)
        self.assertEqual(("date-time-picker", "dropdown", "modal", "table-filter-form"), module.REQUIRED_ADMIN_DYNAMIC_ENTRIES)

    def test_wheel_arguments_require_exact_files_and_preserve_explicit_order(self) -> None:
        module = load_verify_wheel_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "oldman-1.0.0-py3-none-any.whl"
            second = root / "oldman-2.0.0-py3-none-any.whl"
            first.touch()
            second.touch()

            self.assertEqual([second.resolve(), first.resolve()], module.resolve_wheel_args([str(second), str(first)]))
            for value in (
                root / "*.whl",
                root / "oldman-1.0.0-*.whl",
                root / "oldman-?.whl",
                root / "oldman-[12].whl",
            ):
                with self.subTest(value=value), self.assertRaises(RuntimeError):
                    module.resolve_wheel_args([str(value)])

            wrong_suffix = root / "oldman.zip"
            wrong_suffix.touch()
            directory = root / "directory.whl"
            directory.mkdir()
            symlink = root / "linked.whl"
            symlink.symlink_to(first)
            for value in (root / "missing.whl", wrong_suffix, directory, symlink):
                with self.subTest(value=value), self.assertRaises(RuntimeError):
                    module.resolve_wheel_args([str(value)])

    def test_wheel_verifier_rejects_missing_admin_user_management_chunks(self) -> None:
        """The wheel manifest must retain components used by the restored user manager."""
        module = load_verify_wheel_module()
        errors: list[str] = []

        module.verify_manifest_references(set(), {"src/main.ts": {}}, errors)

        for name in module.REQUIRED_ADMIN_DYNAMIC_ENTRIES:
            self.assertIn(f"Admin manifest missing required dynamic entry: {name}", errors)

    def test_wheel_verifier_rejects_missing_and_rewritten_committed_modules(self) -> None:
        module = load_verify_wheel_module()
        with tempfile.TemporaryDirectory() as tmp:
            wheel = Path(tmp) / "oldman.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("oldman/__init__.py", b"rewritten\n")
            expected = {
                "oldman/__init__.py": hashlib.sha256(b"source\n").hexdigest(),
                "oldman/tasks/base.py": hashlib.sha256(b"task\n").hexdigest(),
            }

            errors = module.verify_wheel(wheel, expected_inventory=expected)

        self.assertTrue(any("missing" in error and "tasks/base.py" in error for error in errors))
        self.assertTrue(any("content differs" in error and "__init__.py" in error for error in errors))

    def test_closed_wheel_fixture_passes(self) -> None:
        module = load_verify_wheel_module()
        with tempfile.TemporaryDirectory() as tmp:
            wheel = Path(tmp) / "oldman.whl"
            expected = write_closed_wheel(wheel, module)

            self.assertEqual([], module.verify_wheel(wheel, expected_inventory=expected))

    def test_closed_wheel_fixture_passes_for_prerelease_versions(self) -> None:
        """Hatchling writes the PEP 440 form (9.9.9rc1) into dist-info names and METADATA; the verifier must expect it."""
        module = load_verify_wheel_module()
        source_files = dict(module.release_source_files(ROOT))
        source_files["pyproject.toml"] = re.sub(
            rb'^version = ".*"$', b'version = "9.9.9-rc.1"', source_files["pyproject.toml"], count=1, flags=re.MULTILINE
        )
        with patch.object(module, "release_source_files", return_value=source_files), tempfile.TemporaryDirectory() as tmp:
            wheel = Path(tmp) / "oldman.whl"
            expected = write_closed_wheel(wheel, module)
            with zipfile.ZipFile(wheel) as archive:
                self.assertIn("oldman-9.9.9rc1.dist-info/METADATA", archive.namelist())

            self.assertEqual([], module.verify_wheel(wheel, expected_inventory=expected))

    def test_wheel_rejects_injected_members_and_tampered_record(self) -> None:
        module = load_verify_wheel_module()
        with tempfile.TemporaryDirectory() as tmp:
            wheel = Path(tmp) / "oldman.whl"
            expected = write_closed_wheel(
                wheel,
                module,
                extra_files={"injected.txt": b"not published\n"},
                bad_record_member="oldman/__init__.py",
            )
            errors = module.verify_wheel(wheel, expected_inventory=expected)

        self.assertIn("Wheel contains unexpected member: injected.txt", errors)
        self.assertIn("Wheel RECORD hash does not match member: oldman/__init__.py", errors)

    def test_wheel_rejects_notification_translation_sources(self) -> None:
        """Wheels carry compiled catalogs but not editable PO/POT sources."""
        module = load_verify_wheel_module()
        source_name = (
            "oldman/web/messages/notifications/locales/"
            "zh_Hans/LC_MESSAGES/messages.po"
        )
        with tempfile.TemporaryDirectory() as tmp:
            wheel = Path(tmp) / "oldman.whl"
            expected = write_closed_wheel(
                wheel,
                module,
                extra_files={source_name: b'msgid ""\nmsgstr ""\n'},
            )
            errors = module.verify_wheel(wheel, expected_inventory=expected)

        self.assertIn(
            f"Wheel must not contain notification translation source: {source_name}",
            errors,
        )

    def test_wheel_rejects_multiple_dist_info_roots_and_symlinks(self) -> None:
        module = load_verify_wheel_module()
        with tempfile.TemporaryDirectory() as tmp:
            wheel = Path(tmp) / "oldman.whl"
            expected = write_closed_wheel(
                wheel,
                module,
                extra_files={"other-1.0.dist-info/METADATA": b"Name: other\n"},
                symlink="oldman/unsafe-link",
            )
            errors = module.verify_wheel(wheel, expected_inventory=expected)

        self.assertTrue(any("exactly one .dist-info" in error for error in errors))
        self.assertIn("Wheel contains an unsafe member type: oldman/unsafe-link", errors)

    def test_real_hatch_wheel_binds_metadata_and_rejects_writable_members(self) -> None:
        module = load_verify_wheel_module()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            subprocess.run(
                ["uv", "build", "--wheel", "--out-dir", str(output)],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            wheel = next(output.glob("*.whl"))
            source_files = module.release_source_files(ROOT)
            self.assertEqual([], module.verify_wheel(wheel, expected_source_files=source_files))
            with zipfile.ZipFile(wheel) as archive:
                names = set(archive.namelist())
            self.assertIn("oldman/db/migrations/templates/env.py", names)
            self.assertIn("oldman/db/migrations/templates/script.py.mako", names)
            self.assertIn("oldman/auth/migrations/__init__.py", names)
            self.assertIn(
                "oldman/web/messages/notifications/migrations/4858aab957ee_create_oldman_notification.py",
                names,
            )
            self.assertIn(
                "oldman/web/templates/oldman/messages/notifications/center_content.html",
                names,
            )
            self.assertIn(
                "oldman/web/templates/oldman/messages/notifications/topbar_fragment.html",
                names,
            )
            self.assertIn(
                "oldman/web/messages/notifications/locales/zh_Hans/LC_MESSAGES/messages.mo",
                names,
            )
            self.assertIn(
                "oldman/web/messages/notifications/locales/zh_Hant/LC_MESSAGES/messages.mo",
                names,
            )
            self.assertFalse(
                any(
                    name.startswith(
                        "oldman/web/messages/notifications/locales/"
                    )
                    and name.endswith((".po", ".pot"))
                    for name in names
                )
            )
            auth_revisions = {
                name
                for name in names
                if name.startswith("oldman/auth/migrations/")
                and name.endswith(".py")
                and name != "oldman/auth/migrations/__init__.py"
            }
            self.assertEqual(len(auth_revisions), 1)

            tampered = output / "tampered.whl"
            rewrite_real_wheel_with_valid_record(wheel, tampered)
            errors = module.verify_wheel(tampered, expected_source_files=source_files)

        self.assertIn("Wheel METADATA Name does not match frozen pyproject.toml", errors)
        self.assertIn("Wheel member mode is not the release-file mode 0644: oldman/__init__.py", errors)
        self.assertFalse(any("RECORD hash" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
