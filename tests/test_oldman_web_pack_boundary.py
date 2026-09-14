"""Negative tests for the exact oldman-web npm tarball boundary."""

from __future__ import annotations

import copy
import gzip
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-oldman-web-package.py"


def load_verifier() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_oldman_web_pack_boundary", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load oldman-web package verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_pack_fixture(
    path: Path,
    module: ModuleType,
    *,
    extra_member: str | None = None,
    tamper_member: str | None = None,
    link_member: str | None = None,
    noncanonical_member: str | None = None,
) -> dict[str, bytes]:
    expected = module.expected_pack_files(module.load_package_json())
    expected_payloads = {name: source.read_bytes() for name, source in expected.items()}
    expected_payloads["package/package.json"] = module.expected_pnpm_packed_package_json(
        module.load_package_json()
    )
    archive_buffer = io.BytesIO()
    with tarfile.open(fileobj=archive_buffer, mode="w") as archive:
        for name in expected:
            payload = expected_payloads[name]
            if name == tamper_member:
                payload += b"tampered\n"
            info = tarfile.TarInfo(name)
            info.mode = module.expected_pack_mode(name)
            info.mtime = 0 if name == noncanonical_member else module.NPM_PACK_MTIME
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        if extra_member is not None:
            payload = b"injected\n"
            info = tarfile.TarInfo(extra_member)
            info.mode = 0o644
            info.mtime = module.NPM_PACK_MTIME
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        if link_member is not None:
            info = tarfile.TarInfo(link_member)
            info.mtime = module.NPM_PACK_MTIME
            info.type = tarfile.SYMTYPE
            info.linkname = "../../outside"
            archive.addfile(info)
    payload = bytearray(gzip.compress(archive_buffer.getvalue(), compresslevel=6, mtime=0))
    payload[9] = 3
    path.write_bytes(payload)
    return expected_payloads


def inject_real_pack_member(source: Path, target: Path) -> None:
    """Add one regular member to a real npm pack output."""
    with tarfile.open(source, "r:gz") as input_archive, tarfile.open(target, "w:gz") as output_archive:
        for original in input_archive.getmembers():
            member = copy.copy(original)
            extracted = input_archive.extractfile(original) if original.isfile() else None
            payload = extracted.read() if extracted is not None else None
            output_archive.addfile(member, io.BytesIO(payload) if payload is not None else None)
        payload = b"collaboratively expanded\n"
        injected = tarfile.TarInfo("package/src/private.ts")
        injected.mode = 0o644
        injected.size = len(payload)
        output_archive.addfile(injected, io.BytesIO(payload))


class OldmanWebPackBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.verifier = load_verifier()

    def test_exact_source_allowlist_fixture_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact = Path(temp_dir) / "oldman-web.tgz"
            expected_payloads = write_pack_fixture(artifact, self.verifier)

            self.assertEqual([], self.verifier.verify_pack_artifact(artifact, expected_payloads=expected_payloads))

    def test_injected_and_rewritten_members_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact = Path(temp_dir) / "oldman-web.tgz"
            expected_payloads = write_pack_fixture(
                artifact,
                self.verifier,
                extra_member="package/injected.txt",
                tamper_member="package/LICENSE",
            )

            errors = self.verifier.verify_pack_artifact(artifact, expected_payloads=expected_payloads)

        self.assertIn("Packed artifact contains unexpected member: package/injected.txt", errors)
        self.assertIn("Packed artifact content differs from package source: package/LICENSE", errors)

    def test_links_and_traversal_members_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact = Path(temp_dir) / "oldman-web.tgz"
            expected_payloads = write_pack_fixture(
                artifact,
                self.verifier,
                extra_member="package/../escaped.txt",
                link_member="package/unsafe-link",
            )

            errors = self.verifier.verify_pack_artifact(artifact, expected_payloads=expected_payloads)

        self.assertTrue(any("unsafe member path" in error for error in errors))
        self.assertIn("Packed artifact contains unsafe member type: package/unsafe-link", errors)

    def test_tar_metadata_and_modes_are_verifier_owned(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact = Path(temp_dir) / "oldman-web.tgz"
            expected_payloads = write_pack_fixture(
                artifact,
                self.verifier,
                noncanonical_member="package/LICENSE",
            )

            errors = self.verifier.verify_pack_artifact(artifact, expected_payloads=expected_payloads)

        self.assertIn("Packed artifact member has non-canonical mtime: package/LICENSE", errors)
        self.assertEqual(0o755, self.verifier.expected_pack_mode("package/bin/oldman-web-icons.mjs"))
        self.assertEqual(0o755, self.verifier.expected_pack_mode("package/bin/oldman-web-i18n.mjs"))
        self.assertEqual(0o644, self.verifier.expected_pack_mode("package/dist/index.js"))

    def test_package_json_cannot_collaboratively_expand_verifier_owned_roots(self) -> None:
        package = json.loads(json.dumps(self.verifier.load_package_json()))
        package["files"].append("src")

        with self.assertRaisesRegex(RuntimeError, "verifier-owned publish roots"):
            self.verifier.expected_pack_files(package)

        self.assertEqual(
            ("bin", "dist", "LICENSE", "README.md", "package.json"),
            self.verifier.PACK_FILE_ENTRIES,
        )

    def test_real_pnpm_pack_passes_and_injected_member_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            completed = subprocess.run(
                ["pnpm", "--config.ignore-scripts=true", "pack", "--pack-destination", str(output), "--silent"],
                cwd=self.verifier.PACKAGE_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            artifact = output / completed.stdout.strip().splitlines()[-1]
            expected_payloads = self.verifier.snapshot_expected_pack_files(self.verifier.load_package_json())
            expected_payloads["package/package.json"] = self.verifier.expected_pnpm_packed_package_json(
                self.verifier.load_package_json()
            )
            self.assertEqual(
                [],
                self.verifier.verify_pack_artifact(artifact, expected_payloads=expected_payloads),
            )

            tampered = output / "tampered.tgz"
            inject_real_pack_member(artifact, tampered)
            errors = self.verifier.verify_pack_artifact(tampered, expected_payloads=expected_payloads)

        self.assertIn("Packed artifact contains unexpected member: package/src/private.ts", errors)

    def test_checkout_validation_reads_bytes_without_trusting_git_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checkout = Path(temp_dir)
            source = checkout / "tracked.ts"
            source.write_text("export const value = 1;\n", encoding="utf-8")
            payload = source.read_bytes()
            object_id = hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()
            with (
                mock.patch.object(self.verifier, "committed_tree_entries", return_value={"tracked.ts": ("100644", object_id)}),
                mock.patch.object(self.verifier, "git_output", return_value="sha1\n"),
            ):
                self.verifier.verify_checkout_matches_revision(checkout, "HEAD")
                source.write_text("export const value = 2;\n", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "bytes or mode differ"):
                    self.verifier.verify_checkout_matches_revision(checkout, "HEAD")

    def test_isolated_node_environment_removes_injection_channels_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {
                "PATH": os.environ.get("PATH", ""),
                "NODE_OPTIONS": "--require=/tmp/inject.js",
                "NODE_PATH": "/tmp/modules",
                "npm_config_userconfig": "/tmp/evil-npmrc",
                "NPM_CONFIG_REGISTRY": "https://evil.invalid",
                "PnPm_HoMe": "/tmp/evil-pnpm",
                "GIT_CONFIG_COUNT": "1",
            },
            clear=True,
        ):
            environment = self.verifier.isolated_node_environment(Path(temp_dir))

        for name in ("NODE_OPTIONS", "NODE_PATH", "NPM_CONFIG_REGISTRY", "PnPm_HoMe", "GIT_CONFIG_COUNT"):
            self.assertNotIn(name, environment)
        self.assertEqual("/dev/null", environment["npm_config_userconfig"])
        self.assertEqual("1", environment["GIT_CONFIG_NOSYSTEM"])

    def test_real_frozen_clone_rebuild_matches_pnpm_pack(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as temp_dir:
            root = Path(temp_dir)
            artifact_dir = root / "artifacts"
            evidence = root / "evidence"
            artifact_dir.mkdir()
            evidence.mkdir()
            subprocess.run(
                ["pnpm", "--dir", str(self.verifier.PACKAGE_ROOT), "pack", "--pack-destination", str(artifact_dir)],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            payloads, inventory, package, static_errors, tailwind = self.verifier.rebuild_pack_snapshot(evidence)
            artifact = artifact_dir / f"oldman-web-{package['version']}.tgz"
            errors = static_errors + self.verifier.verify_pack_artifact(
                artifact,
                expected_payloads=payloads,
                package_json=package,
                expected_tailwind_utilities=tailwind,
            )

        self.assertEqual([], errors)
        self.assertEqual(
            subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
            ).stdout.strip(),
            inventory["revision"],
        )


if __name__ == "__main__":
    unittest.main()
