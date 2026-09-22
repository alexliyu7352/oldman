"""Chart 请求错误，单独成模块以便请求对象和视图都能引用。"""

from __future__ import annotations


class ChartInvalidRequest(Exception):
    """图表请求参数非法。"""


__all__ = ["ChartInvalidRequest"]
