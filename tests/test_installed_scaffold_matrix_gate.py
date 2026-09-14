"""Contracts for the installed-wheel scaffold matrix gate."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from types import ModuleType
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-installed-scaffold-matrix.py"


def load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_installed_scaffold_matrix", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InstalledScaffoldMatrixGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gate = load_gate()

    def test_cli_requires_all_three_explicit_paths(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.gate.parse_args([])

        args = self.gate.parse_args(
            ["--wheel", "/tmp/oldman.whl", "--npm-tarball", "/tmp/oldman-web.tgz", "--evidence-dir", "/tmp/evidence"]
        )

        self.assertEqual("/tmp/oldman.whl", args.wheel)
        self.assertEqual("/tmp/oldman-web.tgz", args.npm_tarball)
        self.assertEqual(Path("/tmp/evidence"), args.evidence_dir)

    def test_matrix_contains_five_representative_cases(self) -> None:
        cases = self.gate.matrix_cases()

        self.assertEqual(
            (
                ("cli", "none"),
                ("service", "none"),
                ("api", "postgres"),
                ("web", "mysql"),
                ("dashboard", "sqlite"),
            ),
            cases,
        )

    def test_artifact_resolution_rejects_globs_missing_files_and_wrong_suffixes(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "explicit path"):
            self.gate.resolve_artifact("dist/*.whl", label="wheel", suffix=".whl")
        with self.assertRaisesRegex(RuntimeError, "not a readable"):
            self.gate.resolve_artifact("/definitely/missing.whl", label="wheel", suffix=".whl")

        with tempfile.TemporaryDirectory() as tmp:
            wrong = Path(tmp) / "oldman.zip"
            wrong.write_bytes(b"not a wheel")
            with self.assertRaisesRegex(RuntimeError, "not a readable"):
                self.gate.resolve_artifact(str(wrong), label="wheel", suffix=".whl")
            wheel = Path(tmp) / "oldman.whl"
            wheel.write_bytes(b"wheel")
            symlink = Path(tmp) / "linked.whl"
            symlink.symlink_to(wheel)
            with self.assertRaisesRegex(RuntimeError, "regular"):
                self.gate.resolve_artifact(str(symlink), label="wheel", suffix=".whl")

    def test_evidence_directory_must_be_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "evidence"
            self.assertEqual(evidence.resolve(), self.gate.prepare_evidence_directory(evidence))
            (evidence / "existing.log").write_text("occupied", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "not empty"):
                self.gate.prepare_evidence_directory(evidence)

    def test_clean_environment_blocks_python_and_uv_source_leaks(self) -> None:
        environment = self.gate.clean_environment(
            {
                "PATH": "/bin",
                "PYTHONHOME": "/python",
                "PYTHONPATH": "/repo",
                "UV_PROJECT_ENVIRONMENT": "/repo/.venv",
                "VIRTUAL_ENV": "/repo/.venv",
            }
        )

        for name in ("PYTHONHOME", "PYTHONPATH", "UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV"):
            self.assertNotIn(name, environment)
        self.assertEqual("1", environment["PYTHONNOUSERSITE"])
        self.assertEqual("1", environment["CI"])
        self.assertEqual("/bin", environment["PATH"])

    def test_mismatched_release_artifacts_fail_before_environment_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wheel = root / "oldman-1.2.3-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("oldman-1.2.3.dist-info/METADATA", "Name: oldman\nVersion: 1.2.3\n")
            tarball = root / "oldman-web-9.9.9.tgz"
            package = json.dumps({"name": "oldman-web", "version": "9.9.9"}).encode()
            with tarfile.open(tarball, "w:gz") as archive:
                info = tarfile.TarInfo("package/package.json")
                info.size = len(package)
                archive.addfile(info, io.BytesIO(package))
            evidence = root / "evidence"

            with contextlib.redirect_stderr(io.StringIO()):
                result = self.gate.main(
                    ["--wheel", str(wheel), "--npm-tarball", str(tarball), "--evidence-dir", str(evidence)]
                )

            self.assertEqual(1, result)
            payload = json.loads((evidence / "result.json").read_text(encoding="utf-8"))
            self.assertFalse(payload["ok"])
            self.assertIn("Artifact version mismatch", payload["errors"][0])
            self.assertFalse((evidence / "environment").exists())

    def test_python_normalized_prerelease_matches_original_npm_semver(self) -> None:
        self.gate.require_matching_artifact_versions("1.0.0a1", "1.0.0-alpha.1")

        with self.assertRaisesRegex(RuntimeError, "Artifact version mismatch"):
            self.gate.require_matching_artifact_versions("1.0.0b1", "1.0.0-alpha.1")

    def test_dashboard_consumer_uses_only_the_explicit_tarball(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('package["dependencies"]["oldman-web"] = f"file:{npm_tarball}"', source)
        self.assertIn('frontend / "node_modules" / "oldman-web" / "package.json"', source)
        self.assertIn('resolved_package_json.parent / "dist" / "index.js"', source)
        self.assertIn("resolved_package_json.is_relative_to(node_modules)", source)
        self.assertNotIn('"--ignore-scripts"', source)
        self.assertNotIn("glob.glob", source)
        self.assertNotIn("find_pack_artifact", source)
        self.assertNotIn("sys.path.insert", source)

    def test_installed_npm_tree_excludes_only_package_manager_node_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_root = root / "installed"
            package_root.mkdir()
            payloads = {
                "package/package.json": b'{"name":"oldman-web","version":"0.1.0"}',
                "package/dist/index.js": b"export {};\n",
            }
            tarball = root / "oldman-web-0.1.0.tgz"
            with tarfile.open(tarball, "w:gz") as archive:
                for name, payload in payloads.items():
                    info = tarfile.TarInfo(name)
                    info.mode = 0o644
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))
                    target = package_root / name.removeprefix("package/")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(payload)
            injected = package_root / "node_modules" / ".bin" / "sass"
            injected.parent.mkdir(parents=True)
            injected.write_text("package-manager shim\n", encoding="utf-8")

            evidence = self.gate.installed_npm_tree_evidence(package_root, tarball)

            self.assertEqual(2, evidence["fileCount"])
            self.assertEqual(["node_modules"], evidence["excludedPackageManagerRoots"])
            (package_root / "injected.js").write_text("not from tarball\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "unexpected=.*injected.js"):
                self.gate.installed_npm_tree_evidence(package_root, tarball)

    @unittest.skipUnless(os.name == "posix", "npm installed-mode policy is POSIX-only")
    def test_installed_npm_tree_rejects_world_writable_or_over_executable_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_root = root / "installed"
            package_root.mkdir()
            tarball = root / "oldman-web-0.1.0.tgz"
            payloads = {
                "package/package.json": (b"{}", 0o644),
                "package/bin/tool.mjs": (b"#!/usr/bin/env node\n", 0o755),
            }
            with tarfile.open(tarball, "w:gz") as archive:
                for name, (payload, mode) in payloads.items():
                    info = tarfile.TarInfo(name)
                    info.mode = mode
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))
                    target = package_root / name.removeprefix("package/")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(payload)
                    target.chmod(mode)
            self.gate.installed_npm_tree_evidence(package_root, tarball)

            (package_root / "package.json").chmod(0o666)
            (package_root / "bin" / "tool.mjs").chmod(0o777)
            with self.assertRaisesRegex(RuntimeError, "mode=.*bin/tool.mjs.*package.json"):
                self.gate.installed_npm_tree_evidence(package_root, tarball)

    def test_pnpm_lock_binds_one_resolution_and_snapshot_to_the_same_tarball(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frontend = root / "consumer" / "frontend"
            frontend.mkdir(parents=True)
            tarball = root / "artifacts" / "oldman-web-0.1.0.tgz"
            tarball.parent.mkdir()
            tarball.write_bytes(b"reviewed npm artifact")
            relative = Path(os.path.relpath(tarball, frontend)).as_posix()
            locked = f"file:{relative}"
            integrity = "sha512-" + self.gate.base64.b64encode(
                self.gate.hashlib.sha512(tarball.read_bytes()).digest()
            ).decode("ascii")
            lock_path = frontend / "pnpm-lock.yaml"
            lock_path.write_text(
                f"""lockfileVersion: '9.0'
importers:
  .:
    dependencies:
      oldman-web:
        specifier: file:{tarball}
        version: {locked}(tailwindcss@4.3.2)
packages:
  oldman-web@{locked}:
    resolution:
      integrity: {integrity}
      tarball: {locked}
snapshots:
  oldman-web@{locked}(tailwindcss@4.3.2): {{}}
""",
                encoding="utf-8",
            )

            evidence = self.gate.pnpm_tarball_lock_evidence(lock_path, tarball)

            self.assertEqual(integrity, evidence["integrity"])
            self.assertEqual(f"oldman-web@{locked}", evidence["packageKey"])
            lock_path.write_text(
                lock_path.read_text(encoding="utf-8").replace(
                    f"integrity: {integrity}",
                    f"integrity: sha512-wrong\n  # unrelated entry still mentions {integrity}",
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "bind tarball and integrity together"):
                self.gate.pnpm_tarball_lock_evidence(lock_path, tarball)

    def test_database_probe_connects_only_to_sqlite(self) -> None:
        probe = self.gate.DATABASE_PROBE

        self.assertIn("from oldman import bootstrap_service", probe)
        self.assertIn("context = bootstrap_service(service_name)", probe)
        self.assertIn("engine = create_async_engine(url)", probe)
        self.assertIn('if database == "sqlite":\n            async with engine.connect()', probe)
        self.assertIn("import aiomysql", probe)
        self.assertIn("import asyncpg", probe)
        self.assertEqual(1, probe.count("engine.connect()"))
        self.assertEqual(1, probe.count('text("SELECT 1")'))

    def test_each_matrix_case_uses_a_project_local_uv_environment(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('environment_root = project / ".venv"', source)
        self.assertIn('run(\n        ("uv", "sync")', source)
        self.assertNotIn('"--active"', source)
        self.assertNotIn('"--inexact"', source)
        self.assertNotIn('"--no-install-package"', source)
        self.assertNotIn('"lowest-direct"', source)
        self.assertIn('locked_oldman[0].get("version") != expected_version', source)
        self.assertIn("environment_package_state", source)
        self.assertIn("installed_import_provenance", source)
        self.assertIn("shutil.rmtree(case_project)", source)
        self.assertIn('("uv", "run", "python", "-c", INSTALLED_IMPORT_PROBE)', source)
        self.assertNotIn("environments = {", source)

    def test_project_sync_uses_plain_uv_and_creates_the_ide_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "api-sqlite"
            project.mkdir()
            wheel_index = root / "wheel-index"
            package_index = wheel_index / "oldman"
            package_index.mkdir(parents=True)
            indexed_wheel = package_index / "oldman-1.2.3-py3-none-any.whl"
            indexed_wheel.write_bytes(b"selected wheel")
            wheel_hash = self.gate.sha256_file(indexed_wheel)
            calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

            def fake_run(command, *, cwd, environment, log_path, timeout=300):
                del cwd, log_path, timeout
                calls.append((tuple(command), dict(environment)))
                environment_root = project / ".venv"
                python = self.gate.environment_executable(environment_root, "python")
                python.parent.mkdir(parents=True)
                python.touch()
                (environment_root / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
                (project / "uv.lock").write_text(
                    "version = 1\n\n[[package]]\n"
                    'name = "oldman"\n'
                    'version = "1.2.3"\n'
                    'source = { registry = "../wheel-index" }\n'
                    "wheels = [\n"
                    f'    {{ path = "oldman/{indexed_wheel.name}", hash = "sha256:{wheel_hash}" }},\n'
                    "]\n",
                    encoding="utf-8",
                )
                return ""

            with mock.patch.object(self.gate, "run", side_effect=fake_run):
                evidence = self.gate.sync_generated_project(
                    project,
                    wheel_index=wheel_index,
                    expected_version="1.2.3",
                    environment={"PATH": "/bin"},
                    log_path=root / "evidence" / "uv-sync.log",
                )

            self.assertEqual(("uv", "sync"), calls[0][0])
            self.assertNotIn("VIRTUAL_ENV", calls[0][1])
            self.assertEqual(str((project / ".venv").resolve()), evidence["environment"])
            self.assertEqual(
                str(self.gate.environment_executable((project / ".venv").resolve(), "python")),
                evidence["interpreter"],
            )

    def test_uv_run_uses_the_project_local_environment_without_active_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            environment_root = project / ".venv"
            calls: list[tuple[tuple[str, ...], dict[str, str]]] = []
            provenance = json.dumps(
                {
                    "module": str(environment_root / "lib" / "python3.12" / "site-packages" / "oldman" / "__init__.py"),
                    "prefix": str(environment_root),
                    "version": "1.2.3",
                }
            )

            def fake_run(command, *, cwd, environment, log_path, timeout=300):
                del cwd, log_path, timeout
                calls.append((tuple(command), dict(environment)))
                return provenance

            with mock.patch.object(self.gate, "run", side_effect=fake_run):
                result = self.gate.uv_run_import_provenance(
                    project,
                    environment_root,
                    wheel_index=project / "wheel-index",
                    expected_version="1.2.3",
                    environment={"PATH": "/bin"},
                    log_path=project / "uv-run.log",
                )

            self.assertEqual(("uv", "run", "python", "-c", self.gate.INSTALLED_IMPORT_PROBE), calls[0][0])
            self.assertNotIn("VIRTUAL_ENV", calls[0][1])
            self.assertEqual("1.2.3", result["version"])

    def test_web_matrix_uses_dynamic_port_real_http(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("reserve_tcp_port()", source)
        self.assertIn("subprocess.Popen", source)
        self.assertIn('url = f"http://127.0.0.1:{port}/matrix_probe"', source)
        self.assertIn('(str(launcher), service_name, "start")', source)
        self.assertNotIn("WEB_SERVER_LAUNCHER", source)
        self.assertIn("if status != 200", source)
        self.assertNotIn("WEB_RUNTIME_PROBE", source)

    def test_dashboard_browser_checks_the_real_shared_sidebar(self) -> None:
        self.assertIn(
            'document.querySelector(".oldman-sidebar")',
            self.gate.DASHBOARD_BROWSER_CONTRACT,
        )
        self.assertNotIn(
            'document.querySelector("#matrix-sidebar")',
            self.gate.DASHBOARD_BROWSER_CONTRACT,
        )
        self.assertIn(
            'sidebar?.querySelector(\'#navbar-nav a[href="/matrix_probe"]\')',
            self.gate.DASHBOARD_BROWSER_CONTRACT,
        )
        self.assertNotIn('id="matrix-sidebar"', self.gate.DASHBOARD_COMPONENT_FIXTURE)

    def test_generation_uses_current_interactive_scaffold_and_service_commands(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('"startproject", case_name)', source)
        self.assertIn('"startapp", "matrix_probe"', source)
        self.assertIn('"startservice", "matrix_worker"', source)
        self.assertIn('service_name, "settings", "sync"', source)
        self.assertIn('"db", "history"', source)
        self.assertIn('"db", "migrate"', source)
        self.assertIn('"db", "status"', source)
        self.assertNotIn('"--type", project_type', source)
        self.assertNotIn('"--project-root"', source)
        self.assertNotIn('"main.py", "settings", "init"', source)

    def test_http_200_cannot_hide_a_post_readiness_crash_or_error_output(self) -> None:
        errors = self.gate.http_probe_outcome_errors(
            status=200,
            returncode=7,
            stdout="[ERROR] Error while running server",
            stderr="Traceback (most recent call last):\nRuntimeError: boom",
            response_errors=(),
            shutdown_initiated=False,
            cleanup_errors=(),
        )

        self.assertTrue(any("after HTTP 200" in error for error in errors))
        self.assertTrue(any("non-zero return code 7" in error for error in errors))
        self.assertTrue(any("output contains" in error for error in errors))

    def test_http_probe_rejects_process_group_and_port_residue(self) -> None:
        errors = self.gate.http_probe_outcome_errors(
            status=200,
            returncode=0,
            stdout="server stopped cleanly",
            stderr="DeprecationWarning: harmless warning",
            response_errors=(),
            shutdown_initiated=True,
            cleanup_errors=(
                "owned server process group 123 remains after shutdown",
                "owned server port 127.0.0.1:456 remains open after shutdown",
            ),
        )

        self.assertEqual(2, len(errors))
        self.assertTrue(any("process group" in error for error in errors))
        self.assertTrue(any("port" in error for error in errors))

    def test_http_probe_accepts_clean_graceful_shutdown_with_warning_only_stderr(self) -> None:
        self.assertEqual(
            [],
            self.gate.http_probe_outcome_errors(
                status=200,
                returncode=0,
                stdout="server stopped",
                stderr="DeprecationWarning: migrate this API",
                response_errors=(),
                shutdown_initiated=True,
                cleanup_errors=(),
            ),
        )

    def test_http_response_contract_requires_complete_expected_content(self) -> None:
        self.assertEqual(
            [],
            self.gate.http_response_contract_errors(
                "api",
                status=200,
                body=b'{"name":"matrix_probe","status":"ok"}',
                content_type="application/json; charset=utf-8",
            ),
        )
        self.assertEqual(
            [],
            self.gate.http_response_contract_errors(
                "web",
                status=200,
                body=b"<html><h1>MatrixProbe</h1></html>",
                content_type="text/html; charset=utf-8",
            ),
        )
        for project_type, body, content_type in (
            ("api", b"", "application/json"),
            ("api", b'{"status":"ok"}', "application/json"),
            ("web", b"<html><h1>Wrong app</h1></html>", "text/html"),
            ("dashboard", b"<html><h1>MatrixProbe</h1></html>", "text/html"),
        ):
            with self.subTest(project_type=project_type, body=body):
                self.assertTrue(
                    self.gate.http_response_contract_errors(
                        project_type,
                        status=200,
                        body=body,
                        content_type=content_type,
                    )
                )

    def test_http_200_headers_are_not_committed_when_body_read_fails(self) -> None:
        class BrokenResponse:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                raise TimeoutError("body stalled")

        class Opener:
            def open(self, _url, *, timeout):
                self.timeout = timeout
                return BrokenResponse()

        with self.assertRaisesRegex(TimeoutError, "body stalled"):
            self.gate.read_http_probe_response(Opener(), "http://127.0.0.1:1234/matrix_probe", "api")

    def test_http_probe_fails_closed_when_body_read_stalls_after_200_headers(self) -> None:
        class BrokenResponse:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                raise TimeoutError("body stalled")

        class Opener:
            def open(self, _url, *, timeout):
                del timeout
                return BrokenResponse()

        class RunningProcess:
            pid = 12345
            returncode = 0

            def poll(self):
                return None

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            with (
                mock.patch.object(self.gate, "reserve_tcp_port", return_value=43210),
                mock.patch.object(self.gate, "update_service_settings"),
                mock.patch.object(self.gate.subprocess, "Popen", return_value=RunningProcess()),
                mock.patch.object(self.gate.urllib.request, "build_opener", return_value=Opener()),
                mock.patch.object(self.gate.time, "monotonic", side_effect=(0.0, 0.0, 31.0)),
                mock.patch.object(self.gate.time, "sleep"),
                mock.patch.object(
                    self.gate,
                    "stop_http_probe_process",
                    return_value=("", "", [], True),
                ),
                self.assertRaisesRegex(RuntimeError, "HTTP response read failed"),
            ):
                self.gate.run_http_probe(
                    project,
                    project_type="api",
                    service_name="api",
                    launcher=project / "run.sh",
                    environment={"PATH": "/bin"},
                    log_path=project / "http.log",
                )

    def test_post_readiness_settle_rejects_an_early_clean_exit(self) -> None:
        process = mock.Mock()
        process.wait.return_value = 0

        error = self.gate.settle_http_probe_process(process, timeout=0.25)

        self.assertIn("post-readiness settle window", error)
        self.assertIn("code 0", error)
        process.wait.assert_called_once_with(timeout=0.25)

    def test_post_readiness_settle_accepts_a_process_that_remains_live(self) -> None:
        process = mock.Mock()
        process.wait.side_effect = subprocess.TimeoutExpired(("server",), 0.25)

        self.assertEqual("", self.gate.settle_http_probe_process(process, timeout=0.25))

    def test_post_readiness_stability_window_rejects_a_delayed_clean_exit(self) -> None:
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.35)"])

        error = self.gate.settle_http_probe_process(process, timeout=1.0)

        self.assertIn("post-readiness settle window", error)
        self.assertIn("code 0", error)

    def test_cleanup_detects_a_server_that_exited_before_shutdown_started(self) -> None:
        class ExitedProcess:
            pid = 999_999_999
            returncode = 0

            def poll(self):
                return 0

            def communicate(self, *, timeout):
                del timeout
                return "server stopped itself", ""

        with (
            mock.patch.object(self.gate, "process_group_exists", return_value=False),
            mock.patch.object(self.gate, "tcp_port_is_open", return_value=False),
        ):
            stdout, stderr, cleanup_errors, shutdown_initiated = self.gate.stop_http_probe_process(
                ExitedProcess(),
                host="127.0.0.1",
                port=12345,
            )

        self.assertFalse(shutdown_initiated)
        errors = self.gate.http_probe_outcome_errors(
            status=200,
            returncode=0,
            stdout=stdout,
            stderr=stderr,
            response_errors=(),
            shutdown_initiated=shutdown_initiated,
            cleanup_errors=cleanup_errors,
        )
        self.assertTrue(any("before the gate initiated shutdown" in error for error in errors), errors)

    @unittest.skipUnless(sys.platform == "linux", "detached descendant cleanup requires Linux")
    def test_early_server_exit_still_cleans_a_detached_descendant(self) -> None:
        child_source = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
        parent_source = (
            "import pathlib,subprocess,sys; "
            "child=subprocess.Popen([sys.executable,'-c',sys.argv[2]],start_new_session=True); "
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid))"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            marker = Path(temp_dir) / "child.pid"
            with self.gate.tracked_popen(
                [sys.executable, "-c", parent_source, str(marker), child_source],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            ) as (process, tracker):
                process.wait(timeout=5)
                child_pid = int(marker.read_text(encoding="utf-8"))

                _stdout, _stderr, errors, shutdown_initiated = self.gate.stop_http_probe_process(
                    process,
                    host="127.0.0.1",
                    port=self.gate.reserve_tcp_port(),
                    process_tree=tracker,
                )

                self.assertFalse(shutdown_initiated)
                self.assertTrue(any("before gate-initiated shutdown" in error for error in errors), errors)
                self.assertFalse(Path(f"/proc/{child_pid}").exists())

    @unittest.skipUnless(os.name == "posix", "owned process-group gate is Linux-only")
    def test_http_process_cleanup_accepts_a_real_graceful_listener(self) -> None:
        port = self.gate.reserve_tcp_port()
        source = f"""
import signal
import socket
import sys
import time

listener = socket.socket()
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("127.0.0.1", {port}))
listener.listen()

def stop(_signum, _frame):
    listener.close()
    raise SystemExit(0)

signal.signal(signal.SIGTERM, stop)
while True:
    time.sleep(1)
"""
        process = subprocess.Popen(
            [sys.executable, "-c", source],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not self.gate.tcp_port_is_open("127.0.0.1", port):
                time.sleep(0.05)
            self.assertTrue(self.gate.tcp_port_is_open("127.0.0.1", port))

            _stdout, _stderr, errors, shutdown_initiated = self.gate.stop_http_probe_process(
                process,
                host="127.0.0.1",
                port=port,
            )

            self.assertEqual([], errors)
            self.assertTrue(shutdown_initiated)
            self.assertEqual(0, process.returncode)
        finally:
            try:
                os.killpg(process.pid, 9)
            except ProcessLookupError:
                pass

    @unittest.skipUnless(os.name == "posix", "owned process-group gate is Linux-only")
    def test_http_process_cleanup_detects_and_kills_a_residual_child(self) -> None:
        port = self.gate.reserve_tcp_port()
        child = (
            "import signal,socket,time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            f"s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(('127.0.0.1',{port})); "
            "s.listen(); time.sleep(60)"
        )
        parent = (
            "import signal,subprocess,sys,time; "
            "subprocess.Popen([sys.executable,'-c',sys.argv[1]],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
            "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0)); time.sleep(60)"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", parent, child],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with socket.socket() as client:
                    if client.connect_ex(("127.0.0.1", port)) == 0:
                        break
                time.sleep(0.05)
            else:
                self.fail("residual-child fixture did not open its port")

            _stdout, _stderr, errors, shutdown_initiated = self.gate.stop_http_probe_process(
                process,
                host="127.0.0.1",
                port=port,
            )

            self.assertTrue(shutdown_initiated)
            self.assertTrue(any("process group" in error for error in errors), errors)
            self.assertFalse(self.gate.tcp_port_is_open("127.0.0.1", port))
        finally:
            try:
                os.killpg(process.pid, 9)
            except ProcessLookupError:
                pass

    def test_each_dashboard_case_requires_real_chrome_while_its_server_is_live(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("with ChromePage(browser_result) as client:", source)
        self.assertIn("navigate(client, url)", source)
        self.assertIn("save_screenshot(client", source)
        self.assertIn('document.documentElement.dataset.omReady !== "true"', self.gate.DASHBOARD_BROWSER_CONTRACT)
        self.assertIn('document.querySelector("#back-to-top")', self.gate.DASHBOARD_BROWSER_CONTRACT)
        self.assertIn('document.querySelector("h1")', self.gate.DASHBOARD_BROWSER_CONTRACT)
        self.assertIn("document.fonts.check", self.gate.DASHBOARD_BROWSER_CONTRACT)
        self.assertIn("document.fonts.load", self.gate.DASHBOARD_BROWSER_CONTRACT)
        self.assertIn("buttonVisible", self.gate.DASHBOARD_BROWSER_CONTRACT)
        self.assertIn("button.click()", self.gate.DASHBOARD_BROWSER_CONTRACT)
        self.assertIn("scrollAfterClick", self.gate.DASHBOARD_BROWSER_CONTRACT)
        self.assertIn('if response_ready and project_type == "dashboard":', source)
        self.assertIn('browser_evidence_dir=case_evidence / "browser" if project_type == "dashboard" else None', source)
        self.assertIn("browser_package_provenance=browser_package_provenance", source)
        self.assertIn("resolved_package_json.is_relative_to(node_modules)", source)
        self.assertIn('prefix = "/static/dist/"', source)
        self.assertIn('"consoleErrors": browser_result.console_errors', source)
        self.assertIn('"pageErrors": browser_result.page_errors', source)
        self.assertIn('"resourceErrors": browser_result.bad_responses', source)
        self.assertIn(
            'document.querySelector(".oldman-sidebar")',
            self.gate.DASHBOARD_BROWSER_CONTRACT,
        )
        for component in (
            'data-om-component="table"',
            'data-om-component="modal"',
            'data-om-component="select"',
        ):
            self.assertIn(component, self.gate.DASHBOARD_COMPONENT_FIXTURE)
        for interaction in ("tableSecondPage", "modalOpened", "modalClosed", "selectChanged", "themeToggled"):
            self.assertIn(interaction, self.gate.DASHBOARD_BROWSER_CONTRACT)
        self.assertIn('new MouseEvent("mousedown"', self.gate.DASHBOARD_BROWSER_CONTRACT)
        self.assertIn("cancelable: true", self.gate.DASHBOARD_BROWSER_CONTRACT)
        self.assertIn("nativeSelectChangeCount === 1", self.gate.DASHBOARD_BROWSER_CONTRACT)
        self.assertIn("oldmanSelectChangeCount === 1", self.gate.DASHBOARD_BROWSER_CONTRACT)
        self.assertIn('"om:select:change"', self.gate.DASHBOARD_BROWSER_CONTRACT)
        self.assertIn("install_dashboard_component_fixture(project)", source)
        self.assertIn('for weight in (300, 700):', source)

    def test_browser_assets_must_map_to_generated_static_dist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            asset = project / "static" / "dist" / "assets" / "main.js"
            asset.parent.mkdir(parents=True)
            asset.write_text("export {};", encoding="utf-8")

            evidence = self.gate.browser_asset_evidence(
                project,
                "http://127.0.0.1:43210/matrix_probe",
                ["http://127.0.0.1:43210/static/dist/assets/main.js"],
                label="JavaScript",
            )

            self.assertEqual(str(asset.resolve()), evidence[0]["path"])
            with self.assertRaisesRegex(RuntimeError, "generated server origin"):
                self.gate.browser_asset_evidence(
                    project,
                    "http://127.0.0.1:43210/matrix_probe",
                    ["http://localhost:5173/static/dist/assets/main.js"],
                    label="JavaScript",
                )
            with self.assertRaisesRegex(RuntimeError, "static/dist"):
                self.gate.browser_asset_evidence(
                    project,
                    "http://127.0.0.1:43210/matrix_probe",
                    ["http://127.0.0.1:43210/workspace/main.js"],
                    label="JavaScript",
                )


if __name__ == "__main__":
    unittest.main()
