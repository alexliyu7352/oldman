"""Form 字段类。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Collection, Sequence
from pathlib import PurePosixPath
from typing import Any, Literal, cast

from slugify import slugify
from wtforms import FieldList, FileField, Form, FormField, SelectField, SelectMultipleField, StringField, TextAreaField, ValidationError
from wtforms.utils import unset_value

from oldman.i18n import LazyTranslation

from .choices import ModelChoice
from .widgets import AjaxSelectWidget, ColorPickerWidget, RichTextWidget, TagsInputWidget


def _normalize_tags(value: object, delimiter: str) -> str:
    """把分隔文本整理为去空、去重且顺序稳定的字符串。"""
    items = (item.strip() for item in str(value or "").split(delimiter))
    return delimiter.join(dict.fromkeys(item for item in items if item))


class ColorPickerField(StringField):
    """保存规范化的六位 RGB 或八位 RGBA HEX 颜色。"""

    def __init__(self, *args: Any, allow_alpha: bool = True, **kwargs: Any) -> None:
        kwargs.setdefault("widget", ColorPickerWidget(allow_alpha=allow_alpha))
        super().__init__(*args, **kwargs)
        self.allow_alpha = allow_alpha

    def process_formdata(self, valuelist: list[Any]) -> None:
        """统一输出小写 HEX，便于模型和前端稳定比较。"""
        super().process_formdata(valuelist)
        if self.data:
            self.data = str(self.data).strip().lower()

    def pre_validate(self, form: Form) -> None:
        """拒绝浏览器或客户端提交的非 HEX 值。"""
        super().pre_validate(form)
        if not self.data:
            return
        pattern = r"#[0-9a-f]{6}(?:[0-9a-f]{2})?" if self.allow_alpha else r"#[0-9a-f]{6}"
        if re.fullmatch(pattern, str(self.data)) is None:
            raise ValidationError(self.gettext("Not a valid color value."))


class SlugField(StringField):
    """把提交值规范为 URL slug，并可从同一表单的其他字段补全空值。"""

    def __init__(
        self,
        *args: Any,
        source_field: str | None = None,
        allow_unicode: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.source_field = source_field
        self.allow_unicode = allow_unicode

    def process_formdata(self, valuelist: list[Any]) -> None:
        """只规范用户提交的值，不改写用于编辑展示的模型初始值。"""
        super().process_formdata(valuelist)
        if self.data:
            self.data = slugify(str(self.data), allow_unicode=self.allow_unicode)

    def validate(self, form: Form, extra_validators: Any = ()) -> bool:
        """空值可从指定源字段生成；用户已填写时始终保留其语义。"""
        if not self.data and self.source_field:
            source = form._fields.get(self.source_field)
            if source is None:
                raise ValueError(f"SlugField source_field {self.source_field!r} does not exist")
            self.data = slugify(str(source.data or ""), allow_unicode=self.allow_unicode)
            if self.data and self.raw_data is not None:
                self.raw_data = [self.data]
        return super().validate(form, extra_validators)


class TagsField(StringField):
    """以单个字符串保存可渐进增强的文本标签。"""

    def __init__(self, *args: Any, delimiter: str = ",", **kwargs: Any) -> None:
        if not isinstance(delimiter, str):
            raise TypeError("delimiter must be a string")
        if len(delimiter) != 1:
            raise ValueError("delimiter must be exactly one character")
        self.delimiter = delimiter
        kwargs.setdefault("widget", TagsInputWidget(delimiter=delimiter))
        super().__init__(*args, **kwargs)

    def process_data(self, value: Any) -> None:
        """规范模型或默认值，确保首次渲染与提交结果一致。"""
        super().process_data(value)
        self.data = _normalize_tags(self.data, self.delimiter)

    def process_formdata(self, valuelist: list[Any]) -> None:
        """规范浏览器提交值，保留字符串数据合同。"""
        super().process_formdata(valuelist)
        self.data = _normalize_tags(self.data, self.delimiter)


class RichTextField(TextAreaField):
    """使用原生 textarea 提交 HTML，并可在服务端显式清洗。"""

    def __init__(
        self,
        *args: Any,
        sanitizer: Callable[[str], str] | None = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("widget", RichTextWidget())
        super().__init__(*args, **kwargs)
        self.sanitizer = sanitizer

    def process_formdata(self, valuelist: list[Any]) -> None:
        """只在配置 sanitizer 时清洗提交值，不猜测业务信任策略。"""
        super().process_formdata(valuelist)
        if self.sanitizer is not None and self.data is not None:
            self.data = self.sanitizer(str(self.data))


class JSONListField(FieldList):
    """把 Text 中的 JSON 数组绑定为 WTForms 标量字段列表。"""

    def __init__(self, unbound_field: Any, *args: Any, **kwargs: Any) -> None:
        """拒绝嵌套字段；第一版只维护一维标量列表。"""
        if issubclass(unbound_field.field_class, (FieldList, FormField)):
            raise TypeError("JSONListField only accepts scalar child fields")
        self.list_errors: list[Any] = []
        self._process_list_errors: list[Any] = []
        super().__init__(unbound_field, *args, **kwargs)

    def process(self, formdata: Any, data: Any = unset_value, extra_filters: Any = None) -> None:
        """解码模型值，并在 WTForms 截断前检查提交索引和数量。"""
        self._process_list_errors = []
        decoded = data if data is unset_value else self._decode_model_value(data)
        if formdata is not None:
            indices = self._submitted_indices(formdata)
            if self.max_entries is not None and len(indices) > self.max_entries:
                self._process_list_errors.append(self.gettext("This field accepts at most %(max)d entries.") % {"max": self.max_entries})
        self.list_errors = list(self._process_list_errors)
        super().process(formdata, decoded, extra_filters=extra_filters)

    def validate(self, form: Form, extra_validators: Any = ()) -> bool:
        """保留子字段错误，并把列表级失败交给表单顶部消息。"""
        valid = super().validate(form, extra_validators=extra_validators)
        self.list_errors = list(self._process_list_errors)
        self.list_errors.extend(error for error in self.errors if not isinstance(error, (list, tuple)))
        child_errors = [list(entry.errors) for entry in self.entries]
        self.errors = child_errors if any(child_errors) else []
        try:
            self.encode(self.data)
        except (TypeError, ValueError):
            self.list_errors.append(self.gettext("This field must contain JSON-compatible scalar values."))
        return valid and not self.list_errors and not self.errors

    def template_entry(self, index: str = "__index__") -> Any:
        """创建不写入 entries 的空白子字段，供 HTML template 克隆。"""
        field_list = cast(Any, self)
        entry = cast(Any, self.unbound_field).bind(
            form=None,
            name=f"{self.short_name}{field_list._separator}{index}",
            prefix=field_list._prefix,
            id=f"{self.id}{field_list._separator}{index}",
            _meta=self.meta,
            translations=field_list._translations,
        )
        entry.process(None)
        return entry

    @staticmethod
    def encode(value: list[Any]) -> str:
        """返回数据库 Text 使用的稳定紧凑 JSON。"""
        if any(not isinstance(item, (str, int, float, bool, type(None))) for item in value):
            raise TypeError("JSONListField values must be scalar")
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    def _decode_model_value(self, value: Any) -> list[Any]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                self._process_list_errors.append(self.gettext("Stored JSON value is invalid."))
                return []
        if not isinstance(value, list):
            self._process_list_errors.append(self.gettext("Stored JSON value must be a list."))
            return []
        try:
            self.encode(value)
        except (TypeError, ValueError):
            self._process_list_errors.append(self.gettext("This field must contain JSON-compatible scalar values."))
            return []
        return value

    def _submitted_indices(self, formdata: Any) -> set[int]:
        prefix = f"{self.name}{cast(Any, self)._separator}"
        indices: set[int] = set()
        for key in formdata:
            if not key.startswith(prefix):
                continue
            raw_index = key[len(prefix) :]
            if not raw_index.isascii() or not raw_index.isdigit():
                self._process_list_errors.append(self.gettext("This field contains an invalid item index."))
                continue
            indices.add(int(raw_index))
        return indices


class UploadField(FileField):
    """绑定 Sanic 单个上传文件的 WTForms 字段。"""

    def process_data(self, value: Any) -> None:
        """编辑模型时不把数据库中的逻辑文件名当作本次上传。"""
        del value
        self.data = None


class FileSize:
    """限制上传文件的字节数。"""

    def __init__(self, max_bytes: int, message: str | LazyTranslation | None = None) -> None:
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
            raise TypeError("max_bytes must be an integer")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.max_bytes = max_bytes
        self.message = message

    def __call__(self, form: Form, field: UploadField) -> None:
        del form
        file = field.data
        if file is None:
            return
        if len(file.body) > self.max_bytes:
            message = self.message if self.message is not None else field.gettext("File is too large.")
            raise ValidationError(cast(str, message))


class FileExtension:
    """限制上传文件名最后一个扩展名。"""

    def __init__(self, extensions: Collection[str], message: str | LazyTranslation | None = None) -> None:
        if isinstance(extensions, (str, bytes)) or not isinstance(extensions, Collection):
            raise TypeError("extensions must be a collection of strings")
        normalized: set[str] = set()
        for extension in extensions:
            if not isinstance(extension, str):
                raise TypeError("extensions must contain only strings")
            value = extension.removeprefix(".").lower()
            if not value:
                raise ValueError("extensions must not contain empty values")
            normalized.add(value)
        if not normalized:
            raise ValueError("extensions must not be empty")
        self.extensions = frozenset(normalized)
        self.message = message

    def __call__(self, form: Form, field: UploadField) -> None:
        del form
        file = field.data
        if file is None:
            return
        suffix = PurePosixPath(file.name.replace("\\", "/")).suffix.removeprefix(".").lower()
        if suffix not in self.extensions:
            message = self.message if self.message is not None else field.gettext("File extension is not allowed.")
            raise ValidationError(cast(str, message))


class ModelChoiceField(SelectField):
    """本地模型外键选择字段。"""

    def __init__(self, *args: Any, model_choice: ModelChoice, coerce: Any = int, **kwargs: Any) -> None:
        """保存 ModelChoice 配置并初始化 SelectField。"""
        def coerce_choice(value: Any) -> Any:
            return None if value is None or value == "" else coerce(value)

        super().__init__(*args, choices=[], coerce=coerce_choice, **kwargs)
        self.model_choice = model_choice
        self._choice_values: set[Any] = set()
        self._choices_prepared = False

    async def prepare_choices(self, form: Any) -> None:
        """加载本地候选项并写入 WTForms choices。"""
        if self._choices_prepared:
            return
        objects = await self.model_choice.get_queryset(form.request, form.session)
        choices: list[tuple[Any, str]] = []
        if self.model_choice.empty_label is not None:
            choices.append(("", self.model_choice.empty_label))
        for obj in objects:
            value = self.model_choice.value_from_instance(obj)
            choices.append((value, self.model_choice.label_from_instance(obj)))
        self.choices = choices
        self._choice_values = {self.coerce(value) for value, _label in choices if value != ""}
        self._choices_prepared = True

    def pre_validate(self, form: Form) -> None:
        """校验提交值必须来自当前可见 choices。"""
        if self.data in {None, ""}:
            return
        if self.data not in self._choice_values:
            raise ValidationError(self.gettext("Not a valid choice."))


class AjaxSelectField(SelectField):
    """远程 Select provider 的便捷字段封装。"""

    def __init__(
        self,
        *args: Any,
        provider: str,
        endpoint: str | None = None,
        route_name: str | None = None,
        page_size: int = 20,
        dependent_fields: Sequence[str] = (),
        enhance_choices: bool = False,
        label_mode: Literal["text", "html"] = "text",
        route_kwargs: dict[str, object] | None = None,
        coerce: Any = int,
        **kwargs: Any,
    ) -> None:
        """组合 SelectField 和 AjaxSelectWidget，供简单场景快速声明。"""
        kwargs.setdefault("validate_choice", False)
        kwargs.setdefault(
            "widget",
            AjaxSelectWidget(
                provider=provider,
                endpoint=endpoint,
                route_name=route_name,
                page_size=page_size,
                dependent_fields=dependent_fields,
                enhance_choices=enhance_choices,
                label_mode=label_mode,
                route_kwargs=route_kwargs,
            ),
        )
        super().__init__(*args, choices=[], coerce=coerce, **kwargs)


class AjaxSelectMultipleField(SelectMultipleField):
    """远程多选 Select provider 的便捷字段封装。"""

    def __init__(
        self,
        *args: Any,
        provider: str,
        endpoint: str | None = None,
        route_name: str | None = None,
        page_size: int = 20,
        dependent_fields: Sequence[str] = (),
        enhance_choices: bool = False,
        tags: bool = False,
        label_mode: Literal["text", "html"] = "text",
        route_kwargs: dict[str, object] | None = None,
        coerce: Any = int,
        **kwargs: Any,
    ) -> None:
        """组合 SelectMultipleField 和 AjaxSelectWidget，供多选场景快速声明。"""
        kwargs.setdefault("validate_choice", False)
        kwargs.setdefault(
            "widget",
            AjaxSelectWidget(
                provider=provider,
                endpoint=endpoint,
                route_name=route_name,
                page_size=page_size,
                dependent_fields=dependent_fields,
                enhance_choices=enhance_choices,
                tags=tags,
                label_mode=label_mode,
                route_kwargs=route_kwargs,
            ),
        )
        super().__init__(*args, choices=[], coerce=coerce, **kwargs)


__all__ = [
    "AjaxSelectField",
    "AjaxSelectMultipleField",
    "ColorPickerField",
    "FileExtension",
    "FileSize",
    "JSONListField",
    "ModelChoiceField",
    "RichTextField",
    "SlugField",
    "TagsField",
    "UploadField",
]
