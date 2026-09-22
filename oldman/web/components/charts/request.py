"""Chart 请求状态对象。"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

from oldman.utils.date import naive_utcnow

from .exceptions import ChartInvalidRequest

RANGE_KEY_PATTERN = re.compile(r"(\d+)d")


@dataclass(frozen=True)
class ChartRequest:
    """标准化后的图表请求状态。"""

    request: Any
    range_key: str
    group_by: str
    chart_type: str
    metric: str
    filters: dict[str, object]
    route_kwargs: dict[str, object]

    def range_days(self) -> int:
        """`7d`、`30d` 这类 range key 对应的天数。

        视图的 `allowed_ranges` 已经挡掉了它不支持的值，这里只负责翻译写法；不是 `<天数>d`
        就是接线错误，按非法请求处理。
        """
        match = RANGE_KEY_PATTERN.fullmatch(self.range_key)
        days = int(match.group(1)) if match else 0
        if days < 1:
            raise ChartInvalidRequest(f"Unknown chart range: {self.range_key}")
        return days

    def range_start(self, *, end: dt.datetime | None = None) -> dt.datetime:
        """当前窗口的起点，含今天：`end`（默认无时区 UTC 现在）往前 `range_days() - 1` 天的零点。

        取整到零点是必须的：图表按天分桶（`group_by(func.date(...))`），起点带着当前时分秒的话，
        最早那一天只统计"此刻之后"的记录，折线图第一个点永远偏低，而且随刷新时间漂移。
        """
        window_end = end or naive_utcnow()
        midnight = window_end.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight - dt.timedelta(days=self.range_days() - 1)

