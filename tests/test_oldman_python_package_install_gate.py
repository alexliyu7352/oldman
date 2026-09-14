"""The Python package gate must consume installed artifacts, not repository source."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-python-package-install.py"


def load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_python_package_install", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PythonPackageInstallGateTest(unittest.TestCase):
    def test_gate_installs_wheel_and_rebuilds_sdist_in_isolation(self) -> None:
        self.assertTrue(SCRIPT.is_file())
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('"uv", "venv"', source)
        self.assertIn('"uv", "pip", "install"', source)
        self.assertIn('"uv", "build"', source)
        self.assertIn('"--wheel"', source)
        self.assertIn('environment_executable(environment_root, "oldman")', source)
        self.assertIn("Installed markerless project root escaped the working directory", source)
        self.assertIn('"--help"', source)
        self.assertIn('"startproject"', source)
        self.assertIn('input_text="web\\nsqlite\\n"', source)
        self.assertIn('"startapp", "installed_probe_app"', source)
        self.assertIn('"startservice", "installed_probe_worker"', source)
        self.assertIn('"web", "settings", "sync"', source)
        self.assertIn('"web", "settings", "check"', source)
        self.assertIn('"db", "history"', source)
        self.assertNotIn('"--type", "web"', source)
        self.assertNotIn('"main.py", "settings", "init"', source)
        self.assertIn('environment.pop("PYTHONPATH", None)', source)
        self.assertIn("wheel_oldman_inventory", source)
        self.assertIn("compare_package_inventories", source)
        self.assertIn("modules=json.loads", source)
        self.assertNotIn("sys.path.insert", source)

    def test_clean_environment_blocks_repository_and_user_site_leaks(self) -> None:
        module = load_gate()

        environment = module.clean_environment({"PYTHONPATH": "/repo", "PYTHONHOME": "/python", "PATH": "/bin"})

        self.assertNotIn("PYTHONPATH", environment)
        self.assertNotIn("PYTHONHOME", environment)
        self.assertEqual("1", environment["PYTHONNOUSERSITE"])
        self.assertEqual("/bin", environment["PATH"])

    def test_every_importable_packaged_python_module_is_selected(self) -> None:
        module = load_gate()

        modules = module.package_module_names(
            {
                "oldman/__init__.py": "hash",
                "oldman/admin/__init__.py": "hash",
                "oldman/admin/site.py": "hash",
                "oldman/admin/templates/index.html": "hash",
                "oldman/db/__init__.py": "hash",
                "oldman/db/migrations/__init__.py": "hash",
                "oldman/db/migrations/templates/env.py": "hash",
            }
        )

        self.assertEqual(
            (
                "oldman",
                "oldman.admin",
                "oldman.admin.site",
                "oldman.db",
                "oldman.db.migrations",
            ),
            modules,
        )

    def test_artifact_inputs_require_exact_regular_files_with_expected_suffixes(self) -> None:
        module = load_gate()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wheel = root / "oldman-1.2.3-py3-none-any.whl"
            sdist = root / "oldman-1.2.3.tar.gz"
            wheel.touch()
            sdist.touch()
            symlink = root / "linked.whl"
            symlink.symlink_to(wheel)

            self.assertEqual(wheel.resolve(), module.resolve_single_artifact(str(wheel), "Wheel", ".whl"))
            self.assertEqual(
                sdist.resolve(),
                module.resolve_single_artifact(str(sdist), "Source distribution", ".tar.gz"),
            )
            for value in (root / "*.whl", root / "oldman-?.whl", root / "oldman-[123].whl"):
                with self.subTest(value=value), self.assertRaises(RuntimeError):
                    module.resolve_single_artifact(str(value), "Wheel", ".whl")
            for value in (root / "missing.whl", sdist, root, symlink):
                with self.subTest(value=value), self.assertRaises(RuntimeError):
                    module.resolve_single_artifact(str(value), "Wheel", ".whl")

    def test_sdist_rebuild_requires_the_exact_wheel_for_its_validated_version(self) -> None:
        module = load_gate()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sdist = root / "oldman-1.0.0a1.tar.gz"
            output = root / "output"
            output.mkdir()
            sdist.touch()
            expected = output / "oldman-1.0.0a1-py3-none-any.whl"

            def write_expected(*_args, **_kwargs) -> str:
                expected.touch()
                return ""

            with patch.object(module, "run", side_effect=write_expected):
                self.assertEqual(expected.resolve(), module.rebuild_sdist(sdist, output))

            expected.unlink()

            def write_wrong_version(*_args, **_kwargs) -> str:
                (output / "oldman-9.9.9-py3-none-any.whl").touch()
                return ""

            with patch.object(module, "run", side_effect=write_wrong_version):
                with self.assertRaisesRegex(RuntimeError, "exact expected wheel"):
                    module.rebuild_sdist(sdist, output)

            invalid_sdist = root / "oldman-not!a!version.tar.gz"
            invalid_sdist.touch()
            with self.assertRaisesRegex(RuntimeError, "invalid release version"):
                module.rebuild_sdist(invalid_sdist, output)

            wrong_name = root / "different-1.0.0.tar.gz"
            wrong_name.touch()
            with self.assertRaisesRegex(RuntimeError, "unexpected release name"):
                module.rebuild_sdist(wrong_name, output)

    def test_repeated_python_arguments_define_the_explicit_runtime_matrix(self) -> None:
        module = load_gate()

        args = module.parse_args(
            [
                "--wheel",
                "/tmp/oldman.whl",
                "--sdist",
                "/tmp/oldman.tar.gz",
                "--python",
                "/opt/python3.12",
                "--python",
                "/opt/python3.13",
            ]
        )

        self.assertEqual(["/opt/python3.12", "/opt/python3.13"], args.pythons)

    def test_default_verify_chain_executes_install_gate(self) -> None:
        scripts = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
        wrapper = ROOT / "scripts" / "verify-current-release-python-package.py"

        self.assertIn("verify-current-release-python-package.py", scripts["verify:python-package"])
        self.assertIn("verify-python-package-install.py", wrapper.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
