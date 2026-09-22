"""Chart 视图基类。"""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from oldman.web.api import ApiErrorCode, DefaultApiResponse
from oldman.web.components.data_endpoint import DataEndpointMixin
from oldman.web.http import OldmanHTTPMethodView
from oldman.web.request import get_arg, iter_args
from oldman.web.response import json_response

from .exceptions import ChartInvalidRequest
from .renderers import ChartRenderer
from .request import ChartRequest
from .results import ChartResult


class BaseChartView(DataEndpointMixin, OldmanHTTPMethodView):
    """支持独立 endpoint 的无主题 Chart 基类。"""

    require_authenticated = True
    require_staff = True
    response_mode = "json"
    route_name: str = ""
    route_path: str = ""
    chart_type: str = "line"
    default_range: str = "30d"
    default_group_by: str = ""
    default_metric: str = ""
    allowed_ranges: tuple[str, ...] = ()
    allowed_group_by: tuple[str, ...] = ()
    allowed_metrics: tuple[str, ...] = ()
    allowed_chart_types: tuple[str, ...] = ()
    renderer_class = ChartRenderer

    def __init__(self, request: Any | None = None) -> None:
        """初始化图表 shell 或请求实例。"""
        self.request = request

    def build_chart_request(self, request: Any, *, route_kwargs: dict[str, object]) -> ChartRequest:
        """从 HTTP 请求构建标准 ChartRequest。"""
        args = getattr(request, "args", {}) or {}
        filters = {key.removeprefix("filter."): value for key, value in iter_args(args) if key.startswith("filter.") and value not in {"", None}}
        return ChartRequest(
            request=request,
            range_key=str(get_arg(args, "range", self.default_range) or self.default_range),
            group_by=str(get_arg(args, "group_by", self.default_group_by) or self.default_group_by),
            chart_type=str(get_arg(args, "chart_type", self.chart_type) or self.chart_type),
            metric=str(get_arg(args, "metric", self.default_metric) or self.default_metric),
            filters=filters,
            route_kwargs=dict(route_kwargs),
        )

    async def get(self, request: Any, **route_kwargs: object):
        """处理图表 data endpoint 请求。"""
        self.request = request
        chart_request = self.build_chart_request(request, route_kwargs=route_kwargs)
        if not await self.check_auth(chart_request.request):
            return self.render_error_response("Permission denied", status=403, error_code=ApiErrorCode.PERMISSION_DENIED)
        try:
            await self.validate_filters(chart_request)
            result = await self.get_result(chart_request)
        except ChartInvalidRequest as exc:
            return self.render_error_response(str(exc), status=400)
        return self.render_json_result(result)

    async def check_auth(self, request: Any) -> bool:
        """检查当前请求是否允许访问图表数据。"""
        return True

    async def validate_filters(self, chart_request: ChartRequest) -> None:
        """验证请求中的 filter 参数都由业务图表显式支持。"""
        self.validate_allowed_parameter("range", chart_request.range_key, self.allowed_ranges, default=self.default_range)
        self.validate_allowed_parameter("group_by", chart_request.group_by, self.allowed_group_by, default=self.default_group_by)
        self.validate_allowed_parameter("metric", chart_request.metric, self.allowed_metrics, default=self.default_metric)
        self.validate_allowed_parameter("chart_type", chart_request.chart_type, self.allowed_chart_types, default=self.chart_type)
        for name in chart_request.filters:
            if getattr(self, f"filter_{safe_method_name(name)}", None) is None:
                raise ChartInvalidRequest(f"Unknown chart filter: {name}")

    def validate_allowed_parameter(self, name: str, value: str, allowed: tuple[str, ...], *, default: str) -> None:
        """按业务图表声明的白名单校验单个请求参数。"""
        effective_allowed = allowed or (default,)
        if value in effective_allowed:
            return
        raise ChartInvalidRequest(f"Invalid chart parameter: {name}")

    def render_error_response(self, message: str, *, status: int, error_code: ApiErrorCode = ApiErrorCode.INVALID_REQUEST):
        """把图表请求错误转换为统一 JSON 响应。"""
        response = DefaultApiResponse(
            error_code=error_code,
            message=message,
        )
        return json_response(response.to_dict(), status=status)

    def on_permission_denied(self, request: Any, response_mode: str, *, message: str, method_name: str):
        """endpoint 级权限失败复用 Chart JSON 错误协议。"""
        del request, response_mode, method_name
        return self.render_error_response(message, status=403, error_code=ApiErrorCode.PERMISSION_DENIED)

    def render_json_result(self, result: ChartResult):
        """渲染 ChartResult JSON 响应。"""
        return json_response(result.to_apex_options())

    def get_renderer(self) -> ChartRenderer:
        """返回当前图表 renderer 实例。"""
        return self.renderer_class(self)

    async def render_shell(self, *, html_id: str | None = None, **route_kwargs: object) -> Markup:
        """异步渲染图表外壳和前端挂载属性。"""
        return await self.get_renderer().render_shell(route_kwargs=route_kwargs, html_id=html_id)

    async def get_result(self, chart_request: ChartRequest) -> ChartResult:
        """返回当前图表结果，业务子类应重写。"""
        return ChartResult(series=[], meta={"range": chart_request.range_key})


def safe_method_name(value: str) -> str:
    """把筛选字段名转换为 Python 方法名片段。"""
    return value.replace(".", "_").replace("-", "_")
