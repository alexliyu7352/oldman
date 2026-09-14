"""SQLAlchemy Chart adapter。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from oldman.db import DatabaseManager
from oldman.db import db_manager as default_db_manager

from .views import BaseChartView


class SQLAlchemyChartView(BaseChartView):
    """在同一个只读数据库 session 内完成图表查询的 adapter。"""

    # 多数据库业务通过子类覆盖该属性；默认对象仍由 DB 模块惰性初始化。
    database_manager: DatabaseManager = default_db_manager
    db_session: AsyncSession | None = None

    async def get(self, request: Any, **route_kwargs: object):
        """在只读 session 生命周期内处理图表 data endpoint 请求。"""
        async with self.database_manager.get_read_session() as session:
            self.db_session = session
            try:
                return await super().get(request, **route_kwargs)
            finally:
                self.db_session = None

    def require_db_session(self) -> AsyncSession:
        """Return the request-scoped SQLAlchemy session."""
        if self.db_session is None:
            raise RuntimeError("SQLAlchemyChartView requires an active database session")
        return self.db_session
