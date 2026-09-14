"""Oldman Admin integration with the shared Table component."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from oldman.apps.admin.model_admin import ModelAdmin
from oldman.apps.admin.table import AdminModelTable
from oldman.db.models import DatabaseModel
from oldman.web.components.tables import TableRequest, TableResult


class AdminTableRecord(DatabaseModel):
    """Small mapped record used by the Admin table adapter tests."""

    __tablename__ = "test_oldman_admin_table_record"  # pyright: ignore[reportAssignmentType] -- SQLAlchemy declared_attr override

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class OldmanAdminTableTest(unittest.TestCase):
    """Verify Admin consumes the framework table renderer and protocol."""

    def make_table(self, *, db_manager: object | None = None) -> AdminModelTable:
        request = SimpleNamespace(args={}, app=None)
        return AdminModelTable(
            request,
            model_admin=ModelAdmin(AdminTableRecord),
            db_manager=db_manager if db_manager is not None else object(),  # type: ignore[arg-type]
            admin_prefix="/admin",
        )

    def test_admin_table_injects_the_shared_database_manager(self) -> None:
        """Admin Table 必须使用 shared adapter 的 manager 注入点。"""
        manager = object()

        table = self.make_table(db_manager=manager)

        self.assertIs(manager, table.database_manager)
        self.assertNotIn("get", AdminModelTable.__dict__)

    def test_admin_table_shell_uses_shared_component_protocol(self) -> None:
        table = self.make_table()

        html = str(asyncio.run(table.render_shell(html_id="admin-records-table")))

        self.assertIn('data-om-component="table"', html)
        self.assertIn('data-om-table-src="/admin/test_oldman_admin_table_record/table"', html)
        self.assertIn('class="om-table', html)

    def test_admin_table_fragment_uses_shared_summary_and_pagination(self) -> None:
        table = self.make_table()
        request = TableRequest(request=SimpleNamespace(), q="", page=1, page_size=20, sort="id", filters={}, route_kwargs={})
        result = TableResult(rows=[], row_contexts=[], total=25, filtered_total=25, page=1, page_size=20)

        html = str(asyncio.run(table.get_renderer().render_html_fragment(request, result)))

        self.assertIn("Showing 1", html)
        self.assertIn("of 25 entries", html)
        self.assertIn('data-om-table-page="2"', html)
        self.assertIn("Rows per page", html)

    def test_admin_action_column_uses_model_admin_primary_key(self) -> None:
        table = self.make_table()

        html = str(table.get_column_action_data(AdminTableRecord(id=7, name="Demo")))

        self.assertIn('href="/admin/test_oldman_admin_table_record/7/edit"', html)
        self.assertIn("om-button", html)


if __name__ == "__main__":
    unittest.main()
