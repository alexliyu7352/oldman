"""声明式 Form layout 对象。"""

from __future__ import annotations

from dataclasses import dataclass

from oldman.i18n import LazyTranslation, gettext_lazy

_SAVE_LABEL = gettext_lazy("Save")
_CANCEL_LABEL = gettext_lazy("Cancel")


@dataclass(frozen=True)
class FieldLayout:
    """表单字段布局定义。"""

    name: str
    width: str = "md:col-span-12"


@dataclass(frozen=True)
class Row:
    """声明一行字段及其默认栅格宽度。"""

    fields: tuple[str, ...]
    width: str = "md:col-span-12"

    def __init__(self, *fields: str, width: str = "md:col-span-12") -> None:
        """保存当前行字段名和默认宽度。"""
        object.__setattr__(self, "fields", tuple(fields))
        object.__setattr__(self, "width", width)


@dataclass(frozen=True)
class Actions:
    """声明表单底部动作按钮。"""

    submit: str | LazyTranslation = _SAVE_LABEL
    cancel_url: str | None = None
    cancel_label: str | LazyTranslation = _CANCEL_LABEL


@dataclass(frozen=True)
class FormStep:
    """声明多步骤表单中的一个字段分组。"""

    title: str | LazyTranslation
    items: tuple[object, ...]
    description: str | LazyTranslation = ""

    def __init__(self, title: str | LazyTranslation, *items: object, description: str | LazyTranslation = "") -> None:
        """保存步骤标题、字段布局和可选说明。"""
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "items", tuple(items))
        object.__setattr__(self, "description", description)


@dataclass(frozen=True)
class FormLayout:
    """声明式表单布局。"""

    items: tuple[object, ...]

    def __init__(self, *items: object) -> None:
        """保存布局项。"""
        object.__setattr__(self, "items", tuple(items))


__all__ = ["Actions", "FieldLayout", "FormLayout", "FormStep", "Row"]
