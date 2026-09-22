"""Table 模板 renderer。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, cast

from markupsafe import Markup, escape

from oldman.i18n import gettext_lazy
from oldman.web.template import (
    render_component_template,
    render_component_template_sync,
)

from .cells import render_display_value
from .columns import Column
from .request import TableRequest
from .results import TableResult

_LOADING_MESSAGE = cast(str, gettext_lazy("Loading..."))
_TOOLBAR_TOOLS = ("columns", "density", "export")
_EXPORT_FORMAT_LABELS = {"csv": "CSV"}


class TableRenderer:
    """无主题 Table renderer，负责把表格状态转换为模板上下文。"""

    template_namespace = "oldman/tables/default"

    def __init__(self, table: Any) -> None:
        """保存当前表格实例。"""
        self.table = table

    def template_name(self, name: str) -> str:
        """返回当前 renderer 使用的模板路径。"""
        return f"{self.template_namespace}/{name}"

    async def render_shell(
        self,
        *,
        route_kwargs: dict[str, object],
        html_id: str | None = None,
        show_search: bool = True,
        data_format: Literal["html", "json"] = "html",
        bulk_actions_html: Markup | str | None = None,
    ) -> Markup:
        """渲染表格外壳。"""
        if data_format not in {"html", "json"}:
            raise ValueError("data_format must be 'html' or 'json'")
        attrs = self.shell_attrs(route_kwargs, html_id=html_id, data_format=data_format)
        return await render_component_template(
            self.table,
            self.template_name("shell.html"),
            {
                "attrs": attrs,
                "empty_templates_html": self.render_empty_templates() if data_format == "json" else Markup(""),
                "initial_fragment_html": self.render_initial_fragment(data_format=data_format),
                "toolbar_html": self.render_toolbar(show_search=show_search, bulk_actions_html=bulk_actions_html),
            },
        )

    def render_empty_state(self, *, filtered: bool) -> Markup:
        """Empty-state block for the table body: plain when there is nothing, with a reset when filters hide everything."""
        return render_component_template_sync(
            self.table,
            self.template_name("empty.html"),
            {
                "description": (self.table.empty_filtered_description if filtered else self.table.empty_description) or "",
                "filtered": filtered,
                "title": self.table.empty_filtered_message if filtered else self.table.empty_message,
            },
        )

    def render_empty_templates(self) -> Markup:
        """Both empty-state variants as <template> elements for the JSON mode, which builds rows in the browser."""
        return Markup("").join(
            Markup('<template data-om-table-empty-template="{name}">{body}</template>').format(name=name, body=self.render_empty_state(filtered=filtered))
            for name, filtered in (("all", False), ("filtered", True))
        )

    def render_toolbar(self, *, show_search: bool = True, bulk_actions_html: Markup | str | None = None) -> Markup:
        """Render the table toolbar; empty output when nothing would appear in it."""
        tools = self.toolbar_tools()
        bulk_actions = Markup(bulk_actions_html) if bulk_actions_html else Markup("")
        selectable = bool(self.table.selectable)
        if not (show_search or tools or selectable or bulk_actions):
            return Markup("")
        export_formats = [
            {"name": name, "label": _EXPORT_FORMAT_LABELS.get(name, name.upper())}
            for name in self.export_formats()
        ]
        return render_component_template_sync(
            self.table,
            self.template_name("toolbar.html"),
            {
                "bulk_actions_html": bulk_actions,
                "columns": [column for column in self.table.get_columns() if self.column_is_hideable(column)],
                "export_formats": export_formats,
                "initial_query": self.table.initial_query or "",
                "selectable": selectable,
                "show_search": show_search,
                "tools": tools,
            },
        )

    def toolbar_tools(self) -> list[str]:
        """Return the enabled toolbar tools in declared order."""
        tools: list[str] = []
        for name in getattr(self.table, "toolbar", ()) or ():
            tool = str(name)
            if tool not in _TOOLBAR_TOOLS:
                raise ValueError(f"Unknown table toolbar tool: {tool!r}")
            if tool == "export" and not self.export_formats():
                continue
            if tool == "columns" and not any(self.column_is_hideable(column) for column in self.table.get_columns()):
                continue
            if tool not in tools:
                tools.append(tool)
        return tools

    def export_formats(self) -> list[str]:
        """Return the declared export formats as lowercase names."""
        return [str(name).lower() for name in getattr(self.table, "export_formats", ()) or ()]

    @staticmethod
    def column_is_hideable(column: Column) -> bool:
        """The row-action column is never hideable; other columns follow their own flag."""
        return bool(column.hideable) and column.name != "action"

    def shell_attrs(
        self,
        route_kwargs: dict[str, object],
        *,
        html_id: str | None,
        data_format: Literal["html", "json"] = "html",
    ) -> dict[str, object]:
        """生成表格外层容器属性。"""
        attrs: dict[str, object] = {
            "id": html_id,
            "data-om-component": "table",
            "data-table": True,
            "data-om-table-src": self.table.build_data_url(route_kwargs),
            "data-om-table-page-size": str(self.table.initial_page_size or self.table.page_size),
            "data-om-table-page-size-options": ",".join(self.resolve_page_size_options()),
        }
        if data_format == "json":
            attrs["data-om-table-format"] = "json"
            attrs["data-om-table-empty-message"] = self.table.empty_message
        if self.table.sync_page_url:
            attrs["data-om-table-sync-url"] = "true"
            attrs["data-om-table-initial-page"] = str(self.table.initial_page or 1)
            attrs["data-om-table-default-page-size"] = str(self.table.page_size)
        if self.table.initial_sort:
            attrs["data-om-table-initial-sort"] = self.table.initial_sort
        if self.table.initial_query:
            attrs["data-om-table-initial-query"] = self.table.initial_query
        for name, value in self.table.initial_filters.items():
            if value in {"", None}:
                continue
            attrs[f"data-om-filter-{to_kebab_case(str(name))}"] = value
        return attrs

    def render_initial_fragment(self, *, data_format: Literal["html", "json"] = "html") -> Markup:
        """渲染远程表格首屏占位片段，避免数据到达前出现空白区域。"""
        page_size = self.table.initial_page_size or self.table.page_size
        initial_result = TableResult(
            rows=[],
            row_contexts=[],
            total=0,
            filtered_total=0,
            page=self.table.initial_page or 1,
            page_size=page_size,
        )
        show_footer = data_format == "json"
        return render_component_template_sync(
            self.table,
            self.template_name("fragment.html"),
            {
                "columns": self.table.get_columns(),
                "current_page_size": str(page_size),
                "empty_html": self.render_empty_state(filtered=False),
                "head_html": self.render_html_head(),
                "loading": True,
                "loading_message": _LOADING_MESSAGE,
                "page_size_options": self.resolve_page_size_options(),
                "pagination_html": self.render_html_pagination(initial_result) if show_footer else Markup(""),
                "partial_attrs": {
                    "data-om-table-partial": True,
                    "data-om-initial-table-partial": True,
                },
                "rows": [],
                "selectable": self.table.selectable,
                "show_footer": show_footer,
                "summary_html": self.render_html_summary(initial_result) if show_footer else Markup(""),
            },
        )

    async def render_html_fragment(self, table_request: TableRequest, result: TableResult) -> Markup:
        """渲染 HTML Table 局部片段。"""
        rows = [
            self.render_html_row(row, context, row_index=index, request=table_request.request)
            for index, (row, context) in enumerate(zip(result.rows, result.row_contexts, strict=True))
        ]
        return render_component_template_sync(
            self.table,
            self.template_name("fragment.html"),
            {
                "columns": self.table.get_columns(),
                "empty_html": self.render_empty_state(filtered=result.filtered_total < result.total),
                "head_html": self.render_html_head(),
                "pagination_html": self.render_html_pagination(result),
                "current_page_size": str(result.page_size),
                "page_size_options": self.resolve_page_size_options(current_page_size=result.page_size),
                "partial_attrs": {"data-om-table-partial": True},
                "rows": rows,
                "selectable": self.table.selectable,
                "show_footer": True,
                "summary_html": self.render_html_summary(result),
            },
        )

    def resolve_page_size_options(self, *, current_page_size: int | None = None) -> list[str]:
        """Return stable page-size choices even if the request view instance shadows defaults."""
        options: list[int] = []

        def append(value: object) -> None:
            try:
                parsed = int(cast(Any, value))
            except (TypeError, ValueError):
                return
            if parsed <= 0 or parsed in options:
                return
            options.append(parsed)

        raw_options = getattr(self.table, "page_size_options", ()) or ()
        for option in raw_options:
            append(option)

        if not options:
            for cls in type(self.table).__mro__:
                for option in cls.__dict__.get("page_size_options", ()) or ():
                    append(option)
                if options:
                    break

        append(current_page_size)
        append(getattr(self.table, "initial_page_size", None))
        append(getattr(self.table, "page_size", None))

        maximum = getattr(self.table, "max_page_size", None)
        if maximum is not None:
            try:
                max_page_size = int(maximum)
            except (TypeError, ValueError):
                max_page_size = None
            if max_page_size is not None:
                options = [option for option in options if option <= max_page_size or option == current_page_size]

        return [str(option) for option in options]

    def render_html_head(self) -> Markup:
        """渲染带列 metadata 的表头。"""
        header_cells = []
        for column in self.table.get_columns():
            label = escape(column.label or column.name)
            header_cells.append(
                {
                    "attrs": {
                        "class": "sort sorting" if column.sortable else None,
                        "data-om-column": column.name,
                        "data-om-column-type": column.type,
                        "data-om-column-sortable": "true" if column.sortable else "false",
                        "data-om-column-searchable": "true" if column.searchable else "false",
                    },
                    "column": column,
                    "label": label,
                }
            )
        return render_component_template_sync(
            self.table,
            self.template_name("head.html"),
            {
                "header_cells": header_cells,
                "selectable": self.table.selectable,
            },
        )

    def render_error_fragment(self, message: str) -> Markup:
        """渲染表格错误局部片段。"""
        return render_component_template_sync(self.table, self.template_name("error.html"), {"message": message})

    def render_html_row(self, row: object, context: Mapping[str, object], *, row_index: int, request: Any) -> Markup:
        """渲染 HTML Table 单行。"""
        cells = [
            self.render_html_cell(row, column, context, row_index=row_index, column_index=index, request=request)
            for index, column in enumerate(self.table.get_columns())
        ]
        row_id = self.table.get_row_id(row)
        return render_component_template_sync(
            self.table,
            self.template_name("row.html"),
            {
                "cells": cells,
                "row_id": row_id,
                "selectable": self.table.selectable,
            },
        )

    def render_html_summary(self, result: TableResult) -> Markup:
        """渲染表格总数摘要。"""
        return render_component_template_sync(
            self.table,
            self.template_name("summary.html"),
            {"result": result},
        )

    def render_html_pagination(self, result: TableResult) -> Markup:
        """渲染服务端分页按钮。"""
        page_count = max(1, (result.filtered_total + result.page_size - 1) // result.page_size)
        pages = []
        previous_page: int | None = None
        if page_count > 1:
            for page in self.table.pagination_window(result.page, page_count):
                if previous_page is not None and page - previous_page > 1:
                    pages.append({"ellipsis": True})
                pages.append({"ellipsis": False, "active": page == result.page, "page": page})
                previous_page = page
        return render_component_template_sync(
            self.table,
            self.template_name("pagination.html"),
            {
                "page_count": page_count,
                "pages": pages,
                "next_page": result.page + 1 if result.page < page_count else None,
                "previous_page": result.page - 1 if result.page > 1 else None,
                "result": result,
            },
        )

    def render_html_cell(self, row: object, column: Column, context: Mapping[str, object], *, row_index: int, column_index: int, request: Any) -> Markup:
        """渲染 HTML Table 单元格。"""
        display_value, raw_value = self.table.get_cell_values(row, column, context, row_index=row_index, column_index=column_index, request=request)
        return render_component_template_sync(
            self.table,
            self.template_name("cell.html"),
            {
                "column": column,
                "column_label": escape(column.label or column.name),
                "display_value": render_display_value(display_value),
                "raw_value": "" if raw_value is None else raw_value,
            },
        )


class TailwindTableRenderer(TableRenderer):
    """Tailwind/Oldman Table renderer。"""

    template_namespace = "oldman/tables/default"


def to_kebab_case(value: str) -> str:
    """把筛选字段名转换为 HTML data 属性后缀。"""
    return value.replace("_", "-").replace(".", "-")


__all__ = ["TableRenderer", "TailwindTableRenderer"]
