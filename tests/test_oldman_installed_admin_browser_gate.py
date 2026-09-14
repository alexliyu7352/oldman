"""The release gate must run Admin from the installed wheel in real Chrome."""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-installed-wheel-admin-browser.py"


def load_gate():
    spec = importlib.util.spec_from_file_location("verify_installed_wheel_admin_browser", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class InstalledAdminBrowserGateTest(unittest.TestCase):
    def test_gate_installs_exact_wheel_and_uses_real_chrome(self) -> None:
        self.assertTrue(SCRIPT.is_file())
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('("uv", "venv"', source)
        self.assertIn('("uv", "pip", "install"', source)
        self.assertIn("ChromePage(browser_result)", source)
        self.assertIn('navigate(client, f"{base_url}/admin/login")', source)
        self.assertIn('navigate(client, f"{base_url}/admin/oldman_user")', source)
        self.assertIn("document.fonts.load", source)
        self.assertIn("start_new_session=True", source)
        self.assertIn("Installed-wheel Admin server returncode=", source)
        self.assertNotIn("sys.path.insert", source)

    def test_shutdown_rejects_early_clean_exit_and_nonzero_return_code(self) -> None:
        module = load_gate()
        early = MagicMock(pid=43121, returncode=0)
        early.poll.return_value = 0
        early.communicate.return_value = ("early output", "")
        early_tree = MagicMock()
        with patch.object(module, "wait_until", return_value=True):
            stdout, stderr, errors = module.stop_server(early, early_tree, port=24121)

        self.assertEqual("early output", stdout)
        self.assertEqual("", stderr)
        self.assertTrue(any("before gate-initiated shutdown" in error for error in errors))

        failed = MagicMock(pid=43122, returncode=7)
        failed.poll.return_value = None
        failed.communicate.return_value = ("", "server failed")
        failed_tree = MagicMock()
        with (
            patch.object(module, "wait_until", return_value=True),
        ):
            _stdout, captured_stderr, errors = module.stop_server(failed, failed_tree, port=24122)

        self.assertEqual("server failed", captured_stderr)
        self.assertIn("installed Admin server returned 7", errors)

    def test_clean_environment_blocks_repository_import_leaks(self) -> None:
        module = load_gate()

        environment = module.clean_environment(
            {
                "PATH": "/bin",
                "PYTHONHOME": "/python",
                "PYTHONPATH": "/repo",
                "UV_PROJECT_ENVIRONMENT": "/repo/.venv",
            }
        )

        self.assertEqual("/bin", environment["PATH"])
        self.assertEqual("1", environment["PYTHONNOUSERSITE"])
        self.assertNotIn("PYTHONHOME", environment)
        self.assertNotIn("PYTHONPATH", environment)
        self.assertNotIn("UV_PROJECT_ENVIRONMENT", environment)

    def test_wheel_input_requires_one_exact_regular_whl_file(self) -> None:
        module = load_gate()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wheel = root / "oldman-1.2.3-py3-none-any.whl"
            wheel.touch()
            wrong_suffix = root / "oldman-1.2.3.zip"
            wrong_suffix.touch()
            directory = root / "directory.whl"
            directory.mkdir()
            symlink = root / "linked.whl"
            symlink.symlink_to(wheel)

            self.assertEqual(wheel.resolve(), module.resolve_single_wheel(str(wheel)))
            rejected = (
                str(root / "*.whl"),
                str(root / "oldman-1.2.3-*.whl"),
                str(root / "oldman-?.whl"),
                str(root / "oldman-[123].whl"),
                str(root / "missing.whl"),
                str(wrong_suffix),
                str(directory),
                str(symlink),
            )
            for value in rejected:
                with self.subTest(value=value), self.assertRaises(RuntimeError):
                    module.resolve_single_wheel(value)

    def test_probe_server_uses_public_settings_sqlite_and_redis_session(self) -> None:
        module = load_gate()
        source = module.SERVER_SOURCE
        runtime_settings = inspect.getsource(module.prepare_runtime_settings)

        compile(source, "installed_admin_server.py", "exec")
        self.assertIn('bootstrap_context = bootstrap_service("web")', source)
        self.assertIn("sqlite+aiosqlite", runtime_settings)
        self.assertIn('"redis": {"SESSION": {"redis_url": redis_url}}', runtime_settings)
        self.assertIn("Session(app)", source)
        self.assertIn("await redis_client.close()", source)
        self.assertIn("install_admin(\n    app,", source)
        self.assertIn("ensure_superuser", source)
        self.assertIn("auth_settings=auth_app.settings", source)
        self.assertIn("admin_settings=admin_app.settings", source)
        self.assertNotIn("conf.setup", source)
        self.assertNotIn("configure_admin_database", source)
        self.assertIn("admin_template_dir().resolve()", source)
        self.assertIn("from oldman.apps.admin import", source)
        self.assertIn('STATIC_ROOT / ADMIN_STATIC_PATH / ".vite" / "manifest.json"', source)
        self.assertIn('app.static(STATIC_URL, str(STATIC_ROOT), name="static")', source)
        self.assertNotIn("redis_url=None", source)
        self.assertNotIn("DatabaseManager(", source)
        self.assertNotIn("from oldman.admin", source)
        self.assertNotIn(str(ROOT), source)
        self.assertNotIn("PYTHONPATH", source)

    def test_gate_migrates_the_empty_database_before_starting_admin(self) -> None:
        """The installed server must consume reviewed Auth migrations, never create tables at startup."""
        module = load_gate()

        self.assertIn("load_migration_project(Path.cwd())", module.MIGRATE_SOURCE)
        self.assertIn("migrate(project, FirstUseInteraction())", module.MIGRATE_SOURCE)
        self.assertIn('return "first use"', module.MIGRATE_SOURCE)
        script_source = SCRIPT.read_text(encoding="utf-8")
        self.assertLess(
            script_source.index('(str(python), "-I", "-c", MIGRATE_SOURCE)'),
            script_source.index("with tracked_popen("),
        )

    def test_gate_owns_redis_and_writes_its_url_to_the_service_settings(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("with owned_redis_server(", source)
        self.assertIn("prepare_runtime_settings(", source)
        self.assertIn("redis_url=redis_url", source)
        self.assertNotIn("OLDMAN_INSTALLED_ADMIN_REDIS_URL", source)
        self.assertIn('shutil.which("redis-server"', source)
        self.assertIn("process.wait(timeout=5)", source)
        self.assertIn("Redis port 127.0.0.1", source)

    def test_gate_collects_installed_assets_before_starting_the_server(self) -> None:
        """The wheel gate must exercise collectstatic instead of package source mounts."""
        module = load_gate()
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("collect_project_static(", module.COLLECT_SOURCE)
        self.assertIn("clear=True", module.COLLECT_SOURCE)
        self.assertIn('"OLDMAN_INSTALLED_ADMIN_STATIC_SOURCE"', source)
        self.assertIn('"OLDMAN_INSTALLED_ADMIN_STATIC_ROOT"', source)
        self.assertLess(
            source.index('(str(python), "-I", "-c", COLLECT_SOURCE)'),
            source.index("with tracked_popen("),
        )

    def test_runtime_proof_accepts_owned_short_tmp_alias(self) -> None:
        module = load_gate()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            environment_root = root / "home-storage" / ".venv"
            package_root = environment_root / "lib" / "python3.13" / "site-packages" / "oldman"
            static_root = root / "project" / "public-static"
            template_root = package_root / "apps" / "admin" / "templates"
            manifest = static_root / "oldman" / "admin" / ".vite" / "manifest.json"
            manifest.parent.mkdir(parents=True)
            template_root.mkdir(parents=True)
            (environment_root / "bin").mkdir()
            alias = root / "short-tmp"
            alias.symlink_to(root / "home-storage", target_is_directory=True)
            module.assert_installed_runtime(
                {
                    "oldman_file": str(package_root / "__init__.py"),
                    "python_executable": str(alias / ".venv" / "bin" / "python"),
                    "python_prefix": str(environment_root),
                    "template_dir": str(template_root),
                    "static_dir": str(static_root),
                    "manifest_path": str(manifest),
                },
                alias / ".venv",
                static_root,
            )
            contract_script = module.admin_contract_script(
                module.ManifestContract(
                    main_script="assets/main.js",
                    main_styles=("assets/main.css",),
                    dynamic_files={},
                    font_files=(),
                    all_files=(),
                ),
                alias / ".venv",
                static_root,
            )
            self.assertIn(str(alias / ".venv"), contract_script)
            self.assertIn(str(environment_root.resolve()), contract_script)
            self.assertIn(str(static_root.resolve()), contract_script)

    def test_manifest_contract_requires_entry_chunks_styles_and_fonts(self) -> None:
        module = load_gate()
        manifest = {
            "src/main.ts": {
                "file": "assets/main.js",
                "css": ["assets/main.css"],
                "assets": ["assets/dm-sans-400.woff2"],
            },
            "date": {"name": "date-time-picker", "file": "assets/date.js", "isDynamicEntry": True},
            "dropdown": {"name": "dropdown", "file": "assets/dropdown.js", "isDynamicEntry": True},
            "filter": {"name": "table-filter-form", "file": "assets/filter.js", "isDynamicEntry": True},
            "modal": {"name": "modal", "file": "assets/modal.js", "isDynamicEntry": True},
        }

        contract = module.manifest_contract(manifest)

        self.assertEqual("assets/main.js", contract.main_script)
        self.assertEqual(("assets/main.css",), contract.main_styles)
        self.assertEqual("assets/date.js", contract.dynamic_files["date-time-picker"])
        self.assertEqual(("assets/dm-sans-400.woff2",), contract.font_files)
        self.assertEqual(
            {
                "assets/date.js",
                "assets/dm-sans-400.woff2",
                "assets/dropdown.js",
                "assets/filter.js",
                "assets/main.css",
                "assets/main.js",
                "assets/modal.js",
            },
            set(contract.all_files),
        )

    def test_default_package_gate_runs_installed_admin_browser_after_install_probe(self) -> None:
        scripts = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
        wrapper = ROOT / "scripts" / "verify-current-release-python-package.py"
        command = wrapper.read_text(encoding="utf-8")

        self.assertIn("verify-current-release-python-package.py", scripts["verify:python-package"])
        install_index = command.index("verify-python-package-install.py")
        browser_index = command.index("verify-installed-wheel-admin-browser.py")
        self.assertGreater(browser_index, install_index)


if __name__ == "__main__":
    unittest.main()
