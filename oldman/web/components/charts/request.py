"""Chart 请求状态对象。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast


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


def get_arg(args: object, key: str, default: object = None) -> object:
    """从 request.args 读取单值参数，并兼容 Sanic 多值参数。"""
    getter = getattr(args, "get", None)
    if getter is None:
        return default
    return first_arg_value(getter(key, default))


def iter_args(args: object) -> list[tuple[str, object]]:
    """遍历 request.args 中的单值参数。"""
    if hasattr(args, "items"):
        return [(key, first_arg_value(value)) for key, value in cast(Any, args).items()]
    return []


def first_arg_value(value: object) -> object:
    """把 Sanic 多值查询参数规范为首个值。"""
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value
