"""Public compatibility modules must re-export canonical migrated objects."""

from __future__ import annotations

import importlib
import unittest


class OldmanAliasBoundariesTest(unittest.TestCase):
    def assert_exports_are_identical(
        self,
        alias_module: str,
        expected: dict[str, str],
    ) -> None:
        alias = importlib.import_module(alias_module)
        self.assertEqual(set(alias.__all__), set(expected))
        for name, canonical_module in expected.items():
            canonical = importlib.import_module(canonical_module)
            self.assertIs(getattr(alias, name), getattr(canonical, name))

    def test_db_services_exports_canonical_implementation(self) -> None:
        self.assert_exports_are_identical(
            "oldman.db.services",
            {"BaseModelService": "oldman.db.sqlalchemy.services"},
        )

if __name__ == "__main__":
    unittest.main()
