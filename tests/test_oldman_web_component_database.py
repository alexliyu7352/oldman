"""Web Components 数据库管理器消费合同。"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any, cast

from oldman.db import DatabaseManager
from oldman.db import db_manager as default_db_manager
from oldman.web.components.charts import SQLAlchemyChartView
from oldman.web.components.selects import ModelSelectProvider
from oldman.web.components.tables import SQLAlchemyTableView


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

            async def check_auth(self, request: Any) -> bool:
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

            async def check_auth(self, request: Any) -> bool:
                raise RuntimeError("component hook failed")

        table = FailingDatabaseTable()
        with self.assertRaisesRegex(RuntimeError, "component hook failed"):
            asyncio.run(table.get(make_request()))

        self.assertEqual(manager.read_session_calls, 1)
        self.assertEqual(manager.context.enter_count, 1)
        self.assertEqual(manager.context.exit_count, 1)
        self.assertIsNone(table.db_session)


if __name__ == "__main__":
    unittest.main()
