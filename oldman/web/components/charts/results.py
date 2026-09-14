"""Chart 查询结果对象。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class ChartSeries:
    """ApexCharts series 数据。"""

    name: str
    data: Sequence[object]


@dataclass(frozen=True)
class ChartSummary:
    """图表旁边的摘要项。"""

    label: str
    value: object
    tone: str = "secondary"


@dataclass(frozen=True)
class ChartResult:
    """图表查询结果，不是 HTTP 响应对象。"""

    series: Sequence[ChartSeries] | Sequence[int | float]
    labels: Sequence[object] = field(default_factory=list)
    summary: Sequence[ChartSummary] = field(default_factory=list)
    meta: dict[str, object] = field(default_factory=dict)
    chart: dict[str, object] = field(default_factory=dict)
    options: dict[str, object] = field(default_factory=dict)

    def to_apex_options(self) -> dict[str, object]:
        """转换为前端 ApexChart 组件可消费的 JSON 配置。"""
        payload = dict(self.options)
        payload.update(
            {
                "chart": dict(self.chart),
                "series": [asdict(item) if isinstance(item, ChartSeries) else item for item in self.series],
                "labels": list(self.labels),
                "summary": [asdict(item) for item in self.summary],
                "meta": dict(self.meta),
            }
        )
        return payload
