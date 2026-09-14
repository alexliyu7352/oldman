"""Request-scoped SQL query tracking and diagnostics."""

import contextvars
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

logger = logging.getLogger("sqlalchemy.engine")

# 使用 contextvars 实现上下文隔离
_current_tracker_data: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("sql_tracker_data", default=None)


class SQLQueryTracker:
    """Collect SQL timings inside one async request context."""

    def __init__(self) -> None:
        """Initialize source-compatible diagnostic thresholds."""
        self.slow_query_threshold = 100  # ms
        self.query_limit_per_request = 30
        self._engine_registered = False

    def setup_logging(self, engine: Engine) -> None:
        """设置 SQL 日志监听（只注册一次）"""
        if self._engine_registered:
            return
        self._engine_registered = True
        logger.info("Setting up SQL query tracking")

        @event.listens_for(engine, "before_cursor_execute")
        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            """Push the start time for one cursor execution."""
            conn.info.setdefault("query_start_time", []).append(datetime.now())

        @event.listens_for(engine, "after_cursor_execute")
        def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            """Record a completed cursor execution in the active request context."""
            total = datetime.now() - conn.info["query_start_time"].pop()
            duration = total.total_seconds() * 1000

            # 获取当前上下文的 tracker 数据
            tracker_data = _current_tracker_data.get()
            if tracker_data is None:
                return  # 不在跟踪上下文中，忽略

            sql = statement.strip()
            query_info: dict[str, Any] = {"sql": sql, "parameters": parameters, "duration": duration}
            tracker_data["queries"].append(query_info)

            # 记录慢查询
            if duration > self.slow_query_threshold:
                logger.warning("Slow SQL Query (%.2fms):\nSQL: %s\nParameters: %s", duration, sql, parameters)

            # Database output must pass through the configured logging handlers so
            # file records remain ANSI-free and process-safe.
            logger.info("SQL Query:\nDuration: %.2fms\nSQL: %s\nParameters: %s", duration, sql, parameters)

    @asynccontextmanager
    async def track(self) -> AsyncIterator[dict[str, Any]]:
        """异步上下文管理器用于跟踪查询"""
        tracker_data: dict[str, Any] = {"queries": [], "start_time": datetime.now()}
        token = _current_tracker_data.set(tracker_data)
        try:
            yield tracker_data
        finally:
            _current_tracker_data.reset(token)

    def check_performance(self, queries: list[dict[str, Any]], request_info: str) -> None:
        """检查性能问题"""
        if len(queries) > self.query_limit_per_request:
            logger.warning("Too many queries (%d) for request: %s", len(queries), request_info)

        total_time = sum(q["duration"] for q in queries)
        if total_time > 1000:
            logger.warning("Request took too long (%.2fms): %s", total_time, request_info)

        similar_queries = self._detect_n_plus_1(queries)
        if similar_queries:
            logger.warning("Potential N+1 query detected in %s:\n%s", request_info, similar_queries)

    def _detect_n_plus_1(self, queries: list[dict[str, Any]]) -> str | None:
        """检测可能的 N+1 查询问题"""
        from collections import defaultdict

        query_patterns: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)

        # 修复：使用传入的 queries 参数，而不是 self.queries
        for query in queries:
            simplified = self._simplify_sql(query["sql"])
            query_patterns[simplified].append(query)

        repeated = {pattern: q for pattern, q in query_patterns.items() if len(q) > 3}

        if repeated:
            return "\n".join(f"Pattern executed {len(q)} times: {pattern}" for pattern, q in repeated.items())
        return None

    def _simplify_sql(self, sql: str) -> str:
        """简化SQL以检测相似模式"""
        # 移除具体的值，保留查询结构
        simplified = re.sub(r"\'.*?\'", "?", sql)
        simplified = re.sub(r"\d+", "?", simplified)
        return simplified

    def log_summary(self, queries: list[dict[str, Any]], request_info: str = "") -> None:
        """记录查询摘要"""
        if not queries:
            return

        total_time = sum(q["duration"] for q in queries)
        avg_time = total_time / len(queries)
        max_time = max(q["duration"] for q in queries)

        logger.info(
            "SQL Query Summary: %s\nTotal Queries: %d | Total Time: %.2fms | Avg Time: %.2fms | Max Time: %.2fms\nSlow Queries (>100ms): %d",
            request_info,
            len(queries),
            total_time,
            avg_time,
            max_time,
            sum(1 for q in queries if q["duration"] > self.slow_query_threshold),
        )

        slow_queries = [q for q in queries if q["duration"] > self.slow_query_threshold]
        if slow_queries:
            logger.warning("Slow Queries Details:")
            for i, query in enumerate(slow_queries, 1):
                logger.warning("Slow Query #%d (%.2fms):\nSQL: %s\nParameters: %s", i, query["duration"], query["sql"], query["parameters"])
