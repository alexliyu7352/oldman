"""Chart 组件配置对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChartField:
    """图表可聚合字段声明。"""

    key: str
    label: str
    expression: Any | None = None


@dataclass(frozen=True)
class ChartConfig:
    """Chart 类属性和字段配置的标准对象。"""

    chart_type: str = "line"
    default_range: str = "30d"
    default_group_by: str = ""
    default_metric: str = ""
    fields: tuple[ChartField, ...] = field(default_factory=tuple)
