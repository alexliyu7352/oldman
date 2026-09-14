"""HTML 标签渲染辅助函数。"""

from __future__ import annotations

from html import escape
from typing import Any

from markupsafe import Markup


def html_attrs(attributes: dict[str, Any] | None = None) -> Markup:
    """把属性映射渲染成安全的 HTML 属性字符串。"""
    if not attributes:
        return Markup("")

    rendered: list[str] = []
    for name, value in attributes.items():
        if value is None or value is False:
            continue
        escaped_name = escape(str(name), quote=True)
        if value is True:
            rendered.append(f" {escaped_name}")
            continue
        rendered.append(f' {escaped_name}="{escape(str(value), quote=True)}"')
    return Markup("".join(rendered))


def tag(name: str, content: Any = "", attributes: dict[str, Any] | None = None) -> Markup:
    """渲染带闭合标签的 HTML 片段。

    content 必须已经是安全内容：普通业务文本先走 text()，可信结构化 HTML 显式传 Markup。
    """
    return Markup(f"<{escape(name)}{html_attrs(attributes)}>{content}</{escape(name)}>")


def void_tag(name: str, attributes: dict[str, Any] | None = None) -> Markup:
    """渲染无需闭合的 HTML 标签。"""
    return Markup(f"<{escape(name)}{html_attrs(attributes)}>")


def join_html(parts: list[Any] | tuple[Any, ...]) -> Markup:
    """合并多个已经转义或可信的 HTML 片段。"""
    return Markup("".join(str(part) for part in parts if part is not None))


def css_classes(*classes: str | None | bool) -> str:
    """合并 CSS class，并自动忽略空值。"""
    return " ".join(str(item).strip() for item in classes if item and str(item).strip())


def text(value: Any) -> str:
    """把普通业务值转成可放入 HTML 的安全文本。"""
    return escape("" if value is None else str(value))
