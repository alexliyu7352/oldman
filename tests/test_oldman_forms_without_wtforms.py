"""Oldman's forms run on the framework's own form core; WTForms is neither imported nor required."""

from __future__ import annotations

import ast
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _imports_wtforms(node: ast.Import | ast.ImportFrom) -> bool:
    if isinstance(node, ast.Import):
        return any(alias.name == "wtforms" or alias.name.startswith("wtforms.") for alias in node.names)
    return node.level == 0 and node.module is not None and (node.module == "wtforms" or node.module.startswith("wtforms."))


class FormsWithoutWtformsTest(unittest.TestCase):
    def test_no_framework_module_imports_wtforms(self) -> None:
        offenders = []
        for path in sorted((ROOT / "oldman").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            offenders.extend(
                f"{path.relative_to(ROOT)}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Import | ast.ImportFrom) and _imports_wtforms(node)
            )
        self.assertEqual([], offenders)

    def test_wtforms_is_not_a_dependency(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        requirements = list(project["dependencies"])
        for extra in project.get("optional-dependencies", {}).values():
            requirements.extend(extra)
        self.assertEqual([], [requirement for requirement in requirements if requirement.lower().startswith("wtforms")])
