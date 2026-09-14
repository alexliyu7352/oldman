"""Request-scoped component failure contracts."""

from __future__ import annotations

import unittest

from oldman.web.components.selects import (
    ModelSelectProvider,
)
from oldman.web.components.tables import (
    SQLAlchemyTableView,
)


class DatabaseSessionFailFastTest(unittest.TestCase):
    """The approved request-scoped session diagnostic remains explicit."""

    def test_table_requires_an_active_database_session(self) -> None:
        table = SQLAlchemyTableView()

        with self.assertRaisesRegex(RuntimeError, "active database session"):
            table.require_db_session()

    def test_select_requires_an_active_database_session(self) -> None:
        provider = ModelSelectProvider()

        with self.assertRaisesRegex(RuntimeError, "active database session"):
            provider.require_db_session()


if __name__ == "__main__":
    unittest.main()
