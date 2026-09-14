"""Table 查询结果对象。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TableResult[T_co]:
    """表格查询结果，不是 HTTP 响应 DTO。"""

    rows: Sequence[T_co]
    row_contexts: Sequence[Mapping[str, object]] = field(default_factory=list)
    total: int = 0
    filtered_total: int = 0
    page: int = 1
    page_size: int = 20

    def __post_init__(self) -> None:
        """校验行上下文和行数量一致。"""
        if len(self.row_contexts) != len(self.rows):
            raise ValueError("row_contexts length must match rows length")
