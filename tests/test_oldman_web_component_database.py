"""Web Components 数据库管理器消费合同。"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from sqlalchemy import ForeignKey, Integer, String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload

from oldman.conf.schemas import DatabaseConfig
from oldman.db import DatabaseManager
from oldman.db import db_manager as default_db_manager
from oldman.web.components.charts import SQLAlchemyChartView
from oldman.web.components.selects import ModelSelectProvider
from oldman.web.components.tables import Column, SQLAlchemyTableView


class FakeReadSessionContext:
    """记录一次只读 session 上下文的进入和退出。"""

    def __init__(self) -> None:
        self.session = object()
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self) -> object:
        self.enter_count += 1
        return self.session

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.exit_count += 1


class FakeDatabaseManager:
    """提供可观察只读 session 的测试 manager。"""

    def __init__(self) -> None:
        self.context = FakeReadSessionContext()
        self.read_session_calls = 0

    def get_read_session(self) -> FakeReadSessionContext:
        self.read_session_calls += 1
        return self.context


def make_request() -> Any:
    """构造 Table 直接调用所需的最小请求对象。"""
    return type(
        "RequestStub",
        (),
        {
            "args": {},
            "headers": {"accept": "application/json"},
        },
    )()


class ComponentDatabaseManagerContractTest(unittest.TestCase):
    """验证默认单例和业务子类显式绑定边界。"""

    def test_all_database_adapters_share_framework_default_manager(self) -> None:
        """三个数据库 adapter 不得创建自己的默认连接池。"""
        self.assertIs(ModelSelectProvider.database_manager, default_db_manager)
        self.assertIs(SQLAlchemyTableView.database_manager, default_db_manager)
        self.assertIs(SQLAlchemyChartView.database_manager, default_db_manager)

    def test_table_subclass_uses_explicit_database_manager(self) -> None:
        """业务 Table 子类绑定的 manager 应覆盖框架默认对象。"""
        manager = FakeDatabaseManager()

        class CustomDatabaseTable(SQLAlchemyTableView):
            database_manager = cast(DatabaseManager, manager)

            async def check_auth(self, table_request: Any) -> bool:
                return False

        table = CustomDatabaseTable()
        response = asyncio.run(table.get(make_request()))

        self.assertEqual(response.status, 403)
        self.assertEqual(manager.read_session_calls, 1)
        self.assertEqual(manager.context.enter_count, 1)
        self.assertEqual(manager.context.exit_count, 1)
        self.assertIsNone(table.db_session)

    def test_table_clears_request_session_when_component_hook_fails(self) -> None:
        """组件钩子抛错时仍应退出只读上下文并清空实例状态。"""
        manager = FakeDatabaseManager()

        class FailingDatabaseTable(SQLAlchemyTableView):
            database_manager = cast(DatabaseManager, manager)

            async def check_auth(self, table_request: Any) -> bool:
                raise RuntimeError("component hook failed")

        table = FailingDatabaseTable()
        with self.assertRaisesRegex(RuntimeError, "component hook failed"):
            asyncio.run(table.get(make_request()))

        self.assertEqual(manager.read_session_calls, 1)
        self.assertEqual(manager.context.enter_count, 1)
        self.assertEqual(manager.context.exit_count, 1)
        self.assertIsNone(table.db_session)


class TableSessionLifecycleTest(unittest.TestCase):
    def test_one_read_session_spans_every_hook_of_a_request_in_order(self) -> None:
        manager = FakeDatabaseManager()
        seen: list[tuple[str, object | None]] = []

        class RecordingTable(SQLAlchemyTableView):
            database_manager = cast(DatabaseManager, manager)

            def record(self, hook: str) -> None:
                seen.append((hook, self.db_session))

            async def check_auth(self, table_request: Any) -> bool:
                self.record("check_auth")
                return True

            async def get_queryset(self) -> Any:
                self.record("get_queryset")
                return "query"

            async def apply_base_filters(self, query: Any, table_request: Any) -> Any:
                self.record("apply_base_filters")
                return query

            async def get_total_count(self, query: Any) -> int:
                self.record("get_total_count")
                return 1

            async def apply_filters(self, query: Any, table_request: Any) -> Any:
                self.record("apply_filters")
                return query

            async def apply_search(self, query: Any, table_request: Any) -> Any:
                self.record("apply_search")
                return query

            async def apply_ordering(self, query: Any, table_request: Any) -> Any:
                self.record("apply_ordering")
                return query

            async def paginate(self, query: Any, table_request: Any) -> list[object]:
                self.record("paginate")
                return [{"id": 1}]

            async def preload_record_data(self, row: object) -> dict[str, object]:
                self.record("preload_record_data")
                return {}

            def render_json_payload(self, table_request: Any, result: Any) -> Any:
                self.record("render_json_payload")
                return {"rows": []}

        table = RecordingTable()
        response = asyncio.run(table.get(make_request()))

        self.assertEqual(200, response.status)
        self.assertEqual((1, 1, 1), (manager.read_session_calls, manager.context.enter_count, manager.context.exit_count))
        self.assertIsNone(table.db_session)
        self.assertEqual(
            [
                "check_auth",
                "get_queryset",
                "apply_base_filters",
                "get_total_count",
                "apply_filters",
                "apply_search",
                "get_total_count",
                "apply_ordering",
                "paginate",
                "preload_record_data",
                "render_json_payload",
            ],
            [hook for hook, _ in seen],
        )
        self.assertTrue(all(session is manager.context.session for _, session in seen))

    def test_loader_options_are_applied_by_the_lifecycle_not_by_get_queryset(self) -> None:
        """On an async session a relation must be loaded with the page: lazy loading it while rendering fails."""

        class LocalBase(DeclarativeBase):
            pass

        class Channel(LocalBase):
            __tablename__ = "table_loader_channel"

            id: Mapped[int] = mapped_column(Integer, primary_key=True)
            name: Mapped[str] = mapped_column(String)

        class Programme(LocalBase):
            __tablename__ = "table_loader_programme"

            id: Mapped[int] = mapped_column(Integer, primary_key=True)
            channel_id: Mapped[int] = mapped_column(ForeignKey("table_loader_channel.id"))
            channel: Mapped[Channel] = relationship()

        async def scenario(database_path: Path) -> Any:
            manager = DatabaseManager(DatabaseConfig(url=f"sqlite+aiosqlite:///{database_path.as_posix()}", echo=False))

            class ProgrammeTable(SQLAlchemyTableView):
                database_manager = manager
                model = Programme
                loader_options = (selectinload(Programme.channel),)
                columns = (Column("channel", "Channel", field_path="channel.name"),)

                async def get_queryset(self) -> Any:
                    return select(Programme)

            try:
                await manager.initialize()
                async with manager.engine.begin() as connection:
                    await connection.run_sync(LocalBase.metadata.create_all)
                async with manager.get_session() as session:
                    session.add_all([Channel(id=1, name="BBC One"), Channel(id=2, name="CNN")])
                    session.add_all([Programme(id=1, channel_id=1), Programme(id=2, channel_id=2)])
                return await ProgrammeTable().get(make_request())
            finally:
                await manager.close()

        with tempfile.TemporaryDirectory() as temp_dir:
            response = asyncio.run(scenario(Path(temp_dir) / "table.sqlite3"))

        self.assertEqual(200, response.status)
        self.assertIn(b"BBC One", response.body)
        self.assertIn(b"CNN", response.body)


if __name__ == "__main__":
    unittest.main()
