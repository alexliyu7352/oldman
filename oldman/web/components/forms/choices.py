"""本地模型 choices 配置。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any


@dataclass
class ModelChoice:
    """本地模型选择器配置。"""

    model: type[Any]
    value_field: str = "id"
    label_field: str = "name"
    order_by: Sequence[str] = dataclass_field(default_factory=tuple)
    max_choices: int = 200
    empty_label: str | None = None

    async def get_queryset(self, request: Any, session: Any) -> Sequence[Any]:
        """返回当前 request/session 可见的本地候选对象。"""
        if session is None:
            raise RuntimeError("ModelChoice requires form session")
        from sqlalchemy import select

        query = select(self.model)
        order_by = tuple(self.order_by) or (self.value_field,)
        for field_name in order_by:
            descending = str(field_name).startswith("-")
            name = str(field_name)[1:] if descending else str(field_name)
            column = getattr(self.model, name)
            query = query.order_by(column.desc() if descending else column.asc())
        query = query.limit(self.max_choices + 1)
        result = await session.execute(query)
        rows = list(result.scalars().all())
        if len(rows) > self.max_choices:
            raise RuntimeError(
                f"ModelChoice for {self.model.__name__} exceeds max_choices={self.max_choices}; "
                "use a larger explicit ModelChoice limit for text-xs tables or AjaxSelectWidget for large tables."
            )
        return rows

    def value_from_instance(self, obj: Any) -> Any:
        """从候选对象读取提交值。"""
        return getattr(obj, self.value_field)

    def label_from_instance(self, obj: Any) -> str:
        """从候选对象读取显示文本。"""
        return str(getattr(obj, self.label_field))


__all__ = ["ModelChoice"]
