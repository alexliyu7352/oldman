"""Select/Autocomplete 候选项和 JSON 结果对象。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from markupsafe import Markup, escape


@dataclass(frozen=True)
class SelectChoice:
    """后端选择器候选项。"""

    id: Any
    text: str
    html: Markup | str | None = None
    selected: bool = False
    disabled: bool = False
    data: dict[str, object] | None = None

    def to_option(self, *, label_mode: Literal["text", "html"] = "text") -> dict[str, object]:
        """转换为前端 SelectOption JSON。"""
        payload: dict[str, object] = {
            "id": str(self.id),
            "text": self.text,
        }
        if label_mode == "html" and self.html is not None:
            payload["html"] = str(self.html if isinstance(self.html, Markup) else escape(self.html))
        if self.selected:
            payload["selected"] = True
        if self.disabled:
            payload["disabled"] = True
        if self.data:
            payload["data"] = self.data
        return payload


@dataclass(frozen=True)
class SelectResult:
    """远程 Select/Autocomplete 正式 JSON 响应。"""

    results: list[SelectChoice]
    more: bool = False

    def to_json(self, *, label_mode: Literal["text", "html"] = "text") -> dict[str, object]:
        """转换为正式前端协议 JSON。"""
        return {
            "results": [choice.to_option(label_mode=label_mode) for choice in self.results],
            "more": self.more,
        }
