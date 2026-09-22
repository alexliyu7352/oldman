"""后端 Chart 组件合同。"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import unittest
from typing import cast

from oldman.db import DatabaseManager
from oldman.db import db_manager as default_db_manager
from oldman.web.api.enums import ApiErrorCode
from oldman.web.components.charts import (
    BaseChartView,
    ChartConfig,
    ChartField,
    ChartInvalidRequest,
    ChartResult,
    ChartSeries,
    ChartSummary,
    SQLAlchemyChartView,
)


class DemoChartView(BaseChartView):
    route_name = "dashboard_programme_trend_chart"
    route_path = "/dashboard/charts/programme-trend"
    chart_type = "line"
    default_range = "7d"

    async def get_result(self, chart_request):
        return ChartResult(
            series=[ChartSeries(name="Programmes", data=[1, 2])],
            labels=["2026-06-09", "2026-06-10"],
            meta={"range": chart_request.range_key},
            chart={"type": chart_request.chart_type},
        )


class StrictChartView(DemoChartView):
    allowed_ranges = ("7d", "30d")
    allowed_group_by = ("day",)
    allowed_metrics = ("programmes",)
    allowed_chart_types = ("line",)


class DeniedChartView(DemoChartView):
    async def check_auth(self, request) -> bool:
        return False


class DeniedSQLAlchemyChartView(SQLAlchemyChartView):
    async def check_auth(self, request) -> bool:
        return False


class FakeReadSession:
    def __init__(self) -> None:
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self):
        self.enter_count += 1
        return object()

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self.exit_count += 1
        return None


class FakeDbManager:
    def __init__(self) -> None:
        self.context = FakeReadSession()
        self.read_session_calls = 0

    def get_read_session(self) -> FakeReadSession:
        self.read_session_calls += 1
        return self.context


class ChartRequestResultTest(unittest.TestCase):
    def test_chart_request_normalizes_sanic_multivalue_args(self) -> None:
        request = make_chart_request(
            args={
                "range": ["30d"],
                "group_by": ["day"],
                "chart_type": ["line"],
                "metric": ["programmes"],
            }
        )

        chart_request = DemoChartView().build_chart_request(request, route_kwargs={})

        self.assertEqual(chart_request.range_key, "30d")
        self.assertEqual(chart_request.group_by, "day")
        self.assertEqual(chart_request.chart_type, "line")
        self.assertEqual(chart_request.metric, "programmes")

    def test_chart_config_is_exported_as_component_contract(self) -> None:
        config = ChartConfig(
            chart_type="bar",
            default_range="30d",
            default_group_by="status",
            default_metric="feeds",
            fields=(ChartField(key="status", label="Status"),),
        )

        self.assertEqual(config.chart_type, "bar")
        self.assertEqual(config.fields[0].key, "status")

    def test_chart_result_converts_to_apex_payload(self) -> None:
        result = ChartResult(
            series=[ChartSeries(name="Programmes", data=[1, 2, 3])],
            labels=["2026-06-08", "2026-06-09", "2026-06-10"],
            summary=[ChartSummary(label="Total", value=6)],
            meta={"range": "3d"},
            chart={"type": "line", "height": 320},
            options={"chart": {"type": "bar"}, "xaxis": {"tickAmount": 3}, "series": []},
        )

        payload = result.to_apex_options()

        self.assertEqual(payload["series"], [{"name": "Programmes", "data": [1, 2, 3]}])
        self.assertEqual(payload["labels"], ["2026-06-08", "2026-06-09", "2026-06-10"])
        self.assertEqual(payload["chart"], {"type": "line", "height": 320})
        self.assertEqual(payload["meta"], {"range": "3d"})
        self.assertEqual(payload["summary"], [{"label": "Total", "value": 6, "tone": "secondary"}])
        self.assertEqual(payload["xaxis"], {"tickAmount": 3})

    def test_chart_result_preserves_scalar_series_for_non_axis_charts(self) -> None:
        result = ChartResult(
            series=[24, 18, 12],
            labels=["Active", "Paused", "Completed"],
            chart={"type": "donut"},
        )

        self.assertEqual(result.to_apex_options()["series"], [24, 18, 12])


class ChartRendererTest(unittest.TestCase):
    def test_chart_renderer_outputs_oldman_apex_shell(self) -> None:
        chart = DemoChartView(request=make_chart_request())

        html = str(asyncio.run(chart.render_shell(html_id="programme-trend-chart")))

        self.assertIn('id="programme-trend-chart"', html)
        self.assertIn('data-om-component="apex-chart"', html)
        self.assertIn('data-om-chart-src="/dashboard/charts/programme-trend"', html)
        self.assertIn("data-om-chart-target", html)
        self.assertIn("data-om-chart-loading", html)
        self.assertNotIn("data-om-scoped-preloader", html)
        self.assertIn("data-om-chart-empty", html)
        self.assertIn("data-om-chart-error", html)
        self.assertIn("data-om-chart-summary", html)
        self.assertIn("data-om-chart-meta", html)


class ChartViewLifecycleTest(unittest.TestCase):
    def test_sqlalchemy_chart_defaults_to_framework_database_manager(self) -> None:
        self.assertIs(SQLAlchemyChartView.database_manager, default_db_manager)

    def test_chart_view_returns_json_payload(self) -> None:
        response = asyncio.run(DemoChartView().get(make_chart_request(headers={"accept": "application/json"})))
        body = response.body
        assert body is not None

        self.assertEqual(response.status, 200)
        self.assertIn(b'"series"', body)
        self.assertIn(b'"Programmes"', body)

    def test_chart_view_rejects_unknown_filter(self) -> None:
        response = asyncio.run(DemoChartView().get(make_chart_request(args={"filter.unknown": ["1"]})))
        body = response.body
        assert body is not None

        self.assertEqual(response.status, 400)
        self.assertIn(b"Unknown chart filter", body)

    def test_chart_view_rejects_values_outside_declared_whitelists(self) -> None:
        for args in (
            {"range": ["365d"]},
            {"group_by": ["month"]},
            {"metric": ["users"]},
            {"chart_type": ["pie"]},
        ):
            with self.subTest(args=args):
                response = asyncio.run(StrictChartView().get(make_chart_request(args=args)))
                body = response.body
                assert body is not None
                self.assertEqual(response.status, 400)
                self.assertIn(b"Invalid chart parameter", body)

    def test_range_key_translates_to_days_and_an_inclusive_window_start(self) -> None:
        """range_days/range_start 是图表共用的时间窗口计算，业务不再各写一份。"""
        end = dt.datetime(2026, 9, 17, 12, 30)

        weekly = make_chart_request(args={"range": ["7d"]})
        chart_request = DemoChartView().build_chart_request(weekly, route_kwargs={})

        self.assertEqual(7, chart_request.range_days())
        # 含今天的 7 天窗口从 6 天前的零点开始：按天分桶时最早一天必须是完整的一天，
        # 否则第一个点只统计"此刻之后"的记录，还会随刷新时间漂移。
        self.assertEqual(dt.datetime(2026, 9, 11, 0, 0), chart_request.range_start(end=end))
        self.assertIsNone(chart_request.range_start().tzinfo)
        self.assertEqual(dt.datetime(2026, 9, 17, 0, 0), chart_request.range_start(end=end.replace(hour=23, minute=59)) + dt.timedelta(days=6))

        broken = DemoChartView().build_chart_request(make_chart_request(args={"range": ["week"]}), route_kwargs={})
        with self.assertRaisesRegex(ChartInvalidRequest, "Unknown chart range"):
            broken.range_days()

    def test_chart_view_permission_denied_returns_403(self) -> None:
        response = asyncio.run(DeniedChartView().get(make_chart_request()))
        body = response.body
        assert body is not None

        self.assertEqual(response.status, 403)
        self.assertIn(b"Permission denied", body)

    def test_sqlalchemy_chart_view_permission_denied_uses_permission_code(self) -> None:
        manager = FakeDbManager()

        class CustomDatabaseChart(DeniedSQLAlchemyChartView):
            database_manager = cast(DatabaseManager, manager)

        response = asyncio.run(CustomDatabaseChart().get(make_chart_request()))
        body = response.body
        assert body is not None

        self.assertEqual(response.status, 403)
        self.assertEqual(json.loads(body)["error_code"], ApiErrorCode.PERMISSION_DENIED)
        self.assertEqual(manager.read_session_calls, 1)
        self.assertEqual(manager.context.enter_count, 1)
        self.assertEqual(manager.context.exit_count, 1)


def make_chart_request(*, args: dict[str, list[str]] | None = None, headers: dict[str, str] | None = None):
    class Args(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    class Headers(dict):
        def get(self, key, default=None):
            return super().get(key.lower(), default)

    return type(
        "ChartRequestStub",
        (),
        {
            "args": Args(args or {}),
            "headers": Headers({(key or "").lower(): value for key, value in (headers or {}).items()}),
            "app": None,
        },
    )()


if __name__ == "__main__":
    unittest.main()
