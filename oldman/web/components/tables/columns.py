"""Table 列定义和字段路径解析。"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from markupsafe import Markup

DEFAULT_FIELD_PATH = object()

CellDisplayValue = str | int | float | Decimal | bool | None | Markup
CellRawValue = str | int | float | bool | None
CellReturnValue = CellDisplayValue | tuple[CellDisplayValue, CellRawValue]


@dataclass(frozen=True)
class Column:
    """标准化后的表格列定义。"""

    name: str
    label: str | None = None
    field_path: str | None | object = DEFAULT_FIELD_PATH
    type: str = "string"
    callback: str | None = None
    sortable: bool = field(default=False, init=False)
    searchable: bool = field(default=False, init=False)
    exportable: bool = True
    visible: bool = True
    header_attrs: dict[str, object] = field(default_factory=dict)
    cell_attrs: dict[str, object] = field(default_factory=dict)

    def normalized(self, *, search_fields: set[str], unsortable_columns: set[str]) -> Column:
        """返回补齐 field_path、label、排序和搜索能力后的列对象。"""
        field_path = self.name if self.field_path is DEFAULT_FIELD_PATH else self.field_path
        is_virtual = field_path is None
        sortable = not is_virtual and self.name not in unsortable_columns and str(field_path) not in unsortable_columns
        searchable = bool(not is_virtual and str(field_path) in search_fields)
        label = self.label if self.label is not None else humanize_field_name(self.name)
        return Column(
            name=self.name,
            label=label,
            field_path=field_path,
            type=self.type,
            callback=self.callback,
            exportable=self.exportable,
            visible=self.visible,
            header_attrs=dict(self.header_attrs),
            cell_attrs=dict(self.cell_attrs),
        ).with_metadata(sortable=sortable, searchable=searchable)

    def with_metadata(self, *, sortable: bool, searchable: bool) -> Column:
        """返回带内部排序和搜索 metadata 的列对象。"""
        object.__setattr__(self, "sortable", sortable)
        object.__setattr__(self, "searchable", searchable)
        return self


def normalize_columns(column_defs: list[object] | tuple[object, ...], *, search_fields: set[str], unsortable_columns: set[str]) -> list[Column]:
    """把字符串、tuple 和 Column 声明标准化为 Column 列表。"""
    columns: list[Column] = []
    for index, definition in enumerate(column_defs):
        column = normalize_column(definition, index=index)
        columns.append(column.normalized(search_fields=search_fields, unsortable_columns=unsortable_columns))
    return columns


def normalize_column(definition: object, *, index: int) -> Column:
    """标准化单个列声明。"""
    if isinstance(definition, Column):
        return definition
    if isinstance(definition, str):
        return Column(name=definition, field_path=definition)
    if isinstance(definition, tuple):
        return normalize_tuple_column(definition, index=index)
    raise TypeError(f"Unsupported table column definition: {definition!r}")


def normalize_tuple_column(definition: tuple[object, ...], *, index: int) -> Column:
    """标准化旧式 tuple 列声明。"""
    if len(definition) == 2:
        label, field_path = definition
        callback = None
    elif len(definition) == 3:
        label, field_path, callback = definition
    else:
        raise TypeError("Table column tuple must contain 2 or 3 items")

    field = None if field_path is None else str(field_path)
    callback_name = None if callback is None else str(callback)
    name = infer_column_name(field, callback_name, index=index)
    return Column(name=name, label=str(label), field_path=field, callback=callback_name)


def infer_column_name(field_path: str | None, callback: str | None, *, index: int) -> str:
    """根据字段路径或回调名推导稳定列名。"""
    if field_path:
        return field_path
    if callback:
        name = callback
        if name.startswith("get_column_") and name.endswith("_data"):
            return name.removeprefix("get_column_").removesuffix("_data")
    return f"column_{index}"


def humanize_field_name(name: str) -> str:
    """把字段名转换为默认表头文本。"""
    return name.replace("_", " ").replace(".", " ").title()


def resolve_field_path(row: object, path: str | None) -> object:
    """按点号路径读取 dict、dataclass 或普通对象字段。"""
    if not path:
        return None
    current: object = row
    for part in path.split("."):
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current
