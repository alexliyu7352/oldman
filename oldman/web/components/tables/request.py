"""Table 请求状态对象。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TableRequest:
    """标准化后的表格请求。"""

    request: Any
    q: str
    page: int
    page_size: int
    sort: str
    filters: dict[str, object]
    route_kwargs: dict[str, object]


def parse_positive_int(value: object, default: int, *, maximum: int | None = None) -> int:
    """解析正整数，非法或超过上限时抛出 ValueError。"""
    if value in {"", None}:
        return default
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        raise ValueError("expected positive integer") from None
    if number < 1:
        raise ValueError("expected positive integer")
    if maximum is not None and number > maximum:
        raise ValueError("positive integer exceeds maximum")
    return number
