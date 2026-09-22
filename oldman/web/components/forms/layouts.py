"""声明式 Form layout 对象。"""

from __future__ import annotations

from dataclasses import dataclass

from oldman.i18n import LazyTranslation, gettext_lazy

_SAVE_LABEL = gettext_lazy("Save")
_CANCEL_LABEL = gettext_lazy("Cancel")


@dataclass(frozen=True)
class FieldLayout:
    """表单字段布局定义。

    ``advanced`` 只对筛选表单的 inline 布局有意义：这类字段收进"更多筛选"面板。
    ``range_end`` 由 ``Row(..., as_range=True)`` 生成：本字段是范围起点，对应字段是终点，两者渲染成一个范围控件。
    """

    name: str
    width: str = "md:col-span-12"
    advanced: bool = False
    range_end: str | None = None
    range_label: str | LazyTranslation | None = None


@dataclass(frozen=True)
class Row:
    """声明一行字段及其默认栅格宽度；``as_range=True`` 把恰好两个字段合成一个范围控件。"""

    fields: tuple[str, ...]
    width: str = "md:col-span-12"
    as_range: bool = False
    advanced: bool = False
    label: str | LazyTranslation | None = None

    def __init__(
        self,
        *fields: str,
        width: str = "md:col-span-12",
        as_range: bool = False,
        advanced: bool = False,
        label: str | LazyTranslation | None = None,
    ) -> None:
        """保存当前行字段名、默认宽度、范围 / 高级筛选标记和范围控件的标签。"""
        if as_range and len(fields) != 2:
            raise ValueError("Row(as_range=True) needs exactly two fields: the range start and end")
        if label is not None and not as_range:
            raise ValueError("Row(label=...) is only meaningful together with as_range=True")
        object.__setattr__(self, "fields", tuple(fields))
        object.__setattr__(self, "width", width)
        object.__setattr__(self, "as_range", as_range)
        object.__setattr__(self, "advanced", advanced)
        object.__setattr__(self, "label", label)


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
class FieldGroup:
    """声明一组带标题（和可选说明）的字段；渲染为 fieldset，字段仍在同一张表单里。"""

    title: str | LazyTranslation
    items: tuple[object, ...]
    description: str | LazyTranslation = ""

    def __init__(self, title: str | LazyTranslation, *items: object, description: str | LazyTranslation = "") -> None:
        """保存分组标题、字段布局和可选说明。"""
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


__all__ = ["Actions", "FieldGroup", "FieldLayout", "FormLayout", "FormStep", "Row"]
