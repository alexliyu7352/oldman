"""Chart 模板 renderer。"""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from oldman.web.template import render_component_template


class ChartRenderer:
    """无主题 Chart renderer，负责把图表状态转换为模板上下文。"""

    template_namespace = "oldman/charts/default"

    def __init__(self, chart: Any) -> None:
        """保存当前图表实例。"""
        self.chart = chart

    def template_name(self, name: str) -> str:
        """返回当前 renderer 使用的模板路径。"""
        return f"{self.template_namespace}/{name}"

    async def render_shell(self, *, route_kwargs: dict[str, object], html_id: str | None = None) -> Markup:
        """渲染图表外壳和前端挂载属性。"""
        return await render_component_template(
            self.chart,
            self.template_name("shell.html"),
            {
                "attrs": self.shell_attrs(route_kwargs, html_id=html_id),
            },
        )

    def shell_attrs(self, route_kwargs: dict[str, object], *, html_id: str | None) -> dict[str, object]:
        """生成图表外层容器属性。"""
        return {
            "id": html_id,
            "data-om-component": "apex-chart",
            "data-om-chart-src": self.chart.build_data_url(route_kwargs),
        }


class TailwindChartRenderer(ChartRenderer):
    """Tailwind/Oldman 图表 renderer。"""

    template_namespace = "oldman/charts/default"


__all__ = ["ChartRenderer", "TailwindChartRenderer"]
