"""Project-root discovery must remain safe in installed and markerless applications."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from oldman.conf.constants import _find_project_root


class ProjectRootDiscoveryTest(unittest.TestCase):
    def test_explicit_environment_root_has_priority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with patch.dict("os.environ", {"PROJECT_ROOT": str(root)}):
                self.assertEqual(root.resolve(), _find_project_root())

    def test_markerless_installed_package_falls_back_to_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            installed_main = root / ".venv" / "lib" / "python3.13" / "site-packages" / "runner.py"
            installed_path = installed_main.parent
            main_module = sys.modules["__main__"]
            with (
                patch.dict("os.environ", {}, clear=True),
                patch("oldman.conf.constants.Path.cwd", return_value=root),
                patch.object(main_module, "__file__", str(installed_main), create=True),
                patch("oldman.conf.constants.sys.path", [str(installed_path)]),
            ):
                discovered = _find_project_root(start=installed_path / "oldman" / "conf")

        self.assertEqual(root.resolve(), discovered)
        self.assertNotIn("site-packages", discovered.as_posix())

    def test_nearest_marker_is_used_from_the_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            nested = root / "src" / "service"
            nested.mkdir(parents=True)
            (root / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0'\n", encoding="utf-8")
            with patch.dict("os.environ", {}, clear=True), patch("oldman.conf.constants.Path.cwd", return_value=nested):
                discovered = _find_project_root()

        self.assertEqual(root.resolve(), discovered)


if __name__ == "__main__":
    unittest.main()
