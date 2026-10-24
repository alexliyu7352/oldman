# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms).
# Original path: src/wtforms/utils.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

import os
import re
from collections.abc import Iterable, Mapping
from typing import Any, cast

_LEADING_SYMBOL = "#" if os.name == "nt" else "-"

# https://docs.python.org/3/library/datetime.html#technical-detail (see NOTE #9)
_DATETIME_STRIP_ZERO_PADDING_FORMATS_RE = re.compile(
    f"%{_LEADING_SYMBOL}["
    "d"  # day of month
    "m"  # month
    "H"  # hour (24-hour)
    "I"  # hour (12-hour)
    "M"  # minutes
    "S"  # seconds
    "U"  # week of year (Sunday first day of week)
    "W"  # week of year (Monday first day of week)
    "V"  # week of year (ISO 8601)
    "]",
    re.MULTILINE,
)


def clean_datetime_format_for_strptime(formats):
    """
    Remove dashes used to disable zero-padding with strftime formats (for
    compatibility with strptime).
    """
    return [
        re.sub(
            _DATETIME_STRIP_ZERO_PADDING_FORMATS_RE,
            lambda m: m[0].replace(_LEADING_SYMBOL, ""),
            format,
        )
        for format in formats
    ]


class UnsetValue:
    """
    An unset value.

    This is used in situations where a blank value like `None` is acceptable
    usually as the default value of a class variable or function parameter
    (iow, usually when `None` is a valid value.)
    """

    def __str__(self):
        return "<unset value>"

    def __repr__(self):
        return "<unset value>"

    def __bool__(self):
        return False

    def __nonzero__(self):
        return False


unset_value = UnsetValue()


def comes_from_wtforms(obj):
    """Whether ``obj`` is an instance of a class defined in the wtforms package.

    WTForms fields and validators share this core's duck-typed protocol, so one left over from
    ``from wtforms import ...`` would be bound or called as if it were ours and keep WTForms' own
    behaviour (translations, error classes). Callers reject such objects instead.
    """
    module = type(obj).__module__
    return module == "wtforms" or module.startswith("wtforms.")


class WebobInputWrapper:
    """
    Wrap a webob MultiDict for use as passing as `formdata` to Field.

    Since for consistency, we have decided in WTForms to support as input a
    small subset of the API provided in common between cgi.FieldStorage,
    Django's QueryDict, and Werkzeug's MultiDict, we need to wrap Webob, the
    only supported framework whose multidict does not fit this API, but is
    nevertheless used by a lot of frameworks.

    While we could write a full wrapper to support all the methods, this will
    undoubtedly result in bugs due to some subtle differences between the
    various wrappers. So we will keep it simple.
    """

    def __init__(self, multidict):
        self._wrapped = multidict

    def __iter__(self):
        return iter(self._wrapped)

    def __len__(self):
        return len(self._wrapped)

    def __contains__(self, name):
        return name in self._wrapped

    def getlist(self, name):
        return self._wrapped.getall(name)


class SanicFormData:
    """Adapt Sanic form data to the form core's getlist protocol.

    把 Sanic 表单数据适配为表单核心需要的 `getlist` 协议。
    """

    def __init__(self, data: Mapping[str, Any] | None, files: Mapping[str, Any] | None = None):
        """保存普通字段和上传文件映射。"""
        self.data = data or {}
        self.files = files or {}

    def getlist(self, key: str) -> list[Any]:
        """Return the field's list of values.

        返回字段的多值列表。
        """
        file_values = self._mapping_getlist(self.files, key)
        return file_values[:1] if file_values else self._mapping_getlist(self.data, key)

    @staticmethod
    def _mapping_getlist(data: Mapping[str, Any], key: str) -> list[Any]:
        """从普通 Mapping 或 Sanic 多值映射读取一个字段。"""
        native_getlist = getattr(data, "getlist", None)
        if callable(native_getlist):
            return list(cast(Iterable[Any], native_getlist(key)))
        value = data.get(key)
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def get(self, key: str, default: Any = None) -> Any:
        """Return the first field value from ordinary mappings or Sanic parameter objects.

        返回字段的第一个值，兼容普通 mapping 和 Sanic 参数对象。
        """
        values = self.getlist(key)
        return values[0] if values else default

    def items(self):
        """Return original field items for debugging and tests.

        返回原始字段项，供调试和测试读取。
        """
        return self.data.items()

    def __iter__(self):
        """迭代普通字段名，供 FieldList 发现带索引输入。"""
        return iter(self.data)

    def to_dict(self) -> dict[str, Any]:
        """Convert raw input to an ordinary dict while preserving multi-value lists.

        把原始输入转换为普通 dict，保留多值字段列表。
        """
        return {key: values[0] if len(values) == 1 else values for key in self.data for values in [self.getlist(key)]}

    def __contains__(self, key: str) -> bool:
        """判断字段是否存在。"""
        return key in self.files or key in self.data
