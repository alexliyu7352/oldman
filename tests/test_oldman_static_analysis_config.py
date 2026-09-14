"""Static-analysis configuration boundary tests."""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class OldmanStaticAnalysisConfigTest(unittest.TestCase):
    """Keep migration suppressions away from new framework code."""

    def test_completed_migration_has_no_per_file_style_exemptions(self) -> None:
        """Current framework code must pass the common rules without migration exemptions."""
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        global_ignores = set(pyproject["tool"]["ruff"]["lint"]["ignore"])
        migration_rules = {"E402", "I001", "UP041", "UP046", "UP047"}

        self.assertNotIn("per-file-ignores", pyproject["tool"]["ruff"]["lint"])
        self.assertTrue(migration_rules.isdisjoint(global_ignores))

    def test_upgrade_rules_are_not_disabled_for_new_code(self) -> None:
        """UP041/UP046/UP047 may not remain global exemptions."""
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        ignored = set(pyproject["tool"]["ruff"]["lint"]["ignore"])
        self.assertTrue({"UP041", "UP046", "UP047"}.isdisjoint(ignored))


if __name__ == "__main__":
    unittest.main()
