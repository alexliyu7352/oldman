"""旧版 ServerTable 兼容层。"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from markupsafe import Markup

from oldman.web.html import css_classes, join_html, tag, text


def warn_legacy_api(name: str) -> None:
    """提示调用方旧表格 API 已弃用，避免新代码继续扩展兼容层。"""
    warnings.warn(
        f"{name} 是旧版 ServerTable 兼容 API，已弃用；新代码必须使用 BaseTableView/SQLAlchemyTableView。",
        DeprecationWarning,
        stacklevel=3,
    )


def translate(message: str) -> str:
    """在缺少请求上下文时安全翻译文本。"""
    from oldman.i18n import gettext

    try:
        return gettext(message)
    except LookupError:
        return message


@dataclass(frozen=True)
class TableState:
    """旧版表格请求状态。"""

    path: str
    query: dict[str, Any]
    sort: str = ""
    direction: str = "asc"
    page: int = 1

    def url(self, **updates: Any) -> str:
        """基于当前请求状态生成新的表格 URL。"""
        params = {key: value for key, value in self.query.items() if value not in {None, ""}}
        params.update({key: value for key, value in updates.items() if value not in {None, ""}})
        querystring = urlencode(params)
        return f"{self.path}?{querystring}" if querystring else self.path

    @classmethod
    def from_request(cls, request, *, path: str) -> TableState:
        """从 Sanic 请求解析旧版表格状态。"""
        warn_legacy_api("TableState.from_request")
        query = {key: request.args.get(key) for key in request.args}
        page = parse_int(query.get("page"), 1)
        return cls(path=path, query=query, sort=str(query.get("sort") or ""), direction=str(query.get("direction") or "asc"), page=max(page, 1))


@dataclass(frozen=True)
class TableColumn:
    """旧版服务端表格列定义。"""

    name: str
    label: str
    accessor: str | Callable[[Any], Any] | None = None
    sortable: bool = True
    header_class: str = ""
    cell_class: str = ""
    formatter: Callable[[Any, Any], Any] | None = None

    def value(self, row: Any) -> Any:
        """读取当前行的列值。"""
        if self.formatter:
            return self.formatter(row, self)
        accessor = self.accessor or self.name
        if callable(accessor):
            return accessor(row)
        return resolve_attr(row, accessor)


@dataclass(frozen=True)
class RowAction:
    """旧版表格行操作按钮。"""

    label: str
    href: Callable[[Any], str]
    css_class: str = "om-button om-button-sm om-button-soft-primary"

    def render(self, row: Any) -> Markup:
        """渲染当前行操作按钮。"""
        return tag("a", text(translate(self.label)), {"href": self.href(row), "class": self.css_class})


class ServerTable:
    """旧版服务端渲染表格。"""

    def __init__(
        self,
        *,
        columns: list[TableColumn],
        rows: list[Any],
        state: TableState,
        total: int,
        page: int,
        total_pages: int,
        actions: list[RowAction] | None = None,
        empty_message: str = "No records found.",
        aria_label: str = "Table",
    ) -> None:
        """初始化旧版表格实例。"""
        warn_legacy_api("ServerTable")
        self.columns = columns
        self.rows = rows
        self.state = state
        self.total = total
        self.page = page
        self.total_pages = total_pages
        self.actions = actions or []
        self.empty_message = empty_message
        self.aria_label = aria_label

    def render(self) -> Markup:
        """渲染完整表格和分页。"""
        return join_html([self.render_table_shell(), self.render_footer()])

    def render_table_shell(self) -> Markup:
        """渲染表格外层滚动容器。"""
        table = tag(
            "table",
            join_html([self.render_head(), self.render_body()]),
            {"class": "om-table min-w-full", "aria-label": translate(self.aria_label)},
        )
        return tag("div", table, {"class": "om-table-shell om-table-scroll"})

    def render_head(self) -> Markup:
        """渲染表头。"""
        headers = [tag("th", self.render_header_cell(column), {"class": column.header_class or None}) for column in self.columns]
        if self.actions:
            headers.append(tag("th", text(translate("Actions")), {"class": "text-end"}))
        return tag("thead", tag("tr", join_html(headers)))

    def render_header_cell(self, column: TableColumn) -> Markup:
        """渲染单个表头单元格。"""
        if not column.sortable:
            return Markup(text(translate(column.label)))
        next_direction = "asc" if self.state.sort != column.name or self.state.direction == "desc" else "desc"
        icon = ""
        if self.state.sort == column.name:
            icon = " &darr;" if self.state.direction == "desc" else " &uarr;"
        href = self.state.url(sort=column.name, direction=next_direction, page=1)
        return tag("a", Markup(text(translate(column.label)) + icon), {"href": href, "class": "text-default-500"})

    def render_body(self) -> Markup:
        """渲染表格主体。"""
        if not self.rows:
            column_count = len(self.columns) + (1 if self.actions else 0)
            empty = tag("td", text(translate(self.empty_message)), {"colspan": column_count, "class": "py-4 text-center text-default-500"})
            return tag("tbody", tag("tr", empty))
        return tag("tbody", join_html([self.render_row(row) for row in self.rows]))

    def render_row(self, row: Any) -> Markup:
        """渲染单行数据。"""
        cells = [tag("td", self.render_value(column.value(row)), {"class": column.cell_class or None}) for column in self.columns]
        if self.actions:
            actions = join_html([action.render(row) for action in self.actions])
            cells.append(tag("td", actions, {"class": "text-end"}))
        return tag("tr", join_html(cells))

    def render_value(self, value: Any) -> Markup:
        """渲染单元格值。"""
        if isinstance(value, Markup):
            return value
        return Markup(text("-" if value is None or value == "" else value))

    def render_footer(self) -> Markup:
        """渲染表格分页底部。"""
        total = tag("div", f"{text(translate('Total'))}: {text(self.total)}", {"class": "text-default-500"})
        previous_url = self.state.url(page=max(self.page - 1, 1))
        next_url = self.state.url(page=min(self.page + 1, self.total_pages))
        previous = tag("a", text(translate("Previous")), {"href": previous_url, "class": css_classes("om-page-button", "disabled" if self.page <= 1 else None)})
        current = tag("span", f"{text(self.page)} / {text(self.total_pages)}", {"class": "om-page-button is-active"})
        next_link = tag("a", text(translate("Next")), {"href": next_url, "class": css_classes("om-page-button", "disabled" if self.page >= self.total_pages else None)})
        pager = tag("div", join_html([previous, current, next_link]), {"class": "om-pagination"})
        return tag("div", join_html([total, pager]), {"class": "mt-4 flex items-center justify-between"})


def parse_int(value: Any, default: int) -> int:
    """解析整数，失败时返回默认值。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def resolve_attr(row: Any, path: str) -> Any:
    """按点路径读取对象或字典属性。"""
    current = row
    for bit in path.split("."):
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(bit)
        else:
            current = getattr(current, bit, None)
    return current
