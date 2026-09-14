"""Form widget 类。"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Literal, cast

from markupsafe import Markup
from wtforms import Field, SelectMultipleField
from wtforms.fields import SelectFieldBase
from wtforms.widgets import Select as SelectWidget
from wtforms.widgets import TextInput

from oldman.i18n import gettext_lazy
from oldman.web.components.selects.signing import SelectContext, sign_select_context
from oldman.web.template import render_component_template

_DECREASE_VALUE_LABEL = gettext_lazy("Decrease value")
_INCREASE_VALUE_LABEL = gettext_lazy("Increase value")
_CHOOSE_COLOR_LABEL = gettext_lazy("Choose color")


class TagsInputWidget(TextInput):
    """输出原生文本框，并声明 TagsInput 渐进增强。"""

    def __init__(self, *, delimiter: str = ",") -> None:
        self.delimiter = delimiter

    def __call__(self, field: Field, **kwargs: Any) -> Markup:
        """保留 WTForms 文本输入合同并附加标签配置。"""
        kwargs.setdefault("data-om-component", "tags-input")
        kwargs.setdefault("data-om-tags-delimiter", self.delimiter)
        return super().__call__(field, **kwargs)


class TagsSelectWidget(SelectWidget):
    """用现有 Select 组件把本地多选项显示为可移除标签。"""

    def __init__(self) -> None:
        super().__init__(multiple=True)

    def __call__(self, field: SelectFieldBase, **kwargs: Any) -> Markup:
        """保留原生多选提交，并启用 Choices 标签展示。"""
        kwargs.setdefault("data-om-component", "select")
        kwargs.setdefault("data-choices", True)
        kwargs.setdefault("data-choices-removeItem", True)
        kwargs.setdefault("data-choices-sorting-false", True)
        return super().__call__(field, **kwargs)


class ColorPickerWidget:
    """输出原生颜色输入，并声明可选的 Pickr 渐进增强。"""

    def __init__(self, *, allow_alpha: bool = True) -> None:
        self.allow_alpha = allow_alpha

    async def render_async(self, field: Field, form: Any, **kwargs: Any) -> Markup:
        """原生 input 负责无脚本提交，挂载后由隐藏字段承载完整 HEXA 值。"""
        value = str(cast(Any, field)._value() or "")
        native_value = value[:7] if re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", value) else "#000000"
        classes = " ".join(filter(None, (str(kwargs.pop("class", "")), "om-color-picker-native")))
        return await render_component_template(
            form,
            f"{form.get_field_renderer().template_namespace}/widgets/color_picker.html",
            {
                "allow_alpha": self.allow_alpha,
                "choose_label": str(_CHOOSE_COLOR_LABEL),
                "input_attrs": {
                    "id": field.id,
                    "name": field.name,
                    "type": "color",
                    "value": native_value,
                    "class": classes,
                    "data-om-color-picker-native": True,
                    **kwargs,
                },
                "value": value,
            },
        )

    def __call__(self, field: Field, **kwargs: Any) -> Markup:
        """要求通过 Oldman 的异步 renderer 输出完整组合控件。"""
        raise RuntimeError("ColorPickerWidget must be rendered through async form.render() or form.render_field()")


class InputSpinnerWidget:
    """为 WTForms 数字字段输出可渐进增强的加减控件。"""

    async def render_async(self, field: Field, form: Any, **kwargs: Any) -> Markup:
        """保留原生 number input，并在外层声明 InputSpinner 组件。"""
        return await render_component_template(
            form,
            f"{form.get_field_renderer().template_namespace}/widgets/input_spinner.html",
            {
                "decrease_label": str(_DECREASE_VALUE_LABEL),
                "increase_label": str(_INCREASE_VALUE_LABEL),
                "input_attrs": {
                    "id": field.id,
                    "name": field.name,
                    "type": "number",
                    "value": cast(Any, field)._value(),
                    "data-om-input-spinner-input": True,
                    **kwargs,
                },
            },
        )

    def __call__(self, field: Field, **kwargs: Any) -> Markup:
        """要求通过 Oldman 的异步 renderer 输出完整组合控件。"""
        raise RuntimeError("InputSpinnerWidget must be rendered through async form.render() or form.render_field()")


class RichTextWidget:
    """输出可由 Quill 渐进增强的原生 textarea。"""

    async def render_async(self, field: Field, form: Any, **kwargs: Any) -> Markup:
        """保留 textarea 作为真实提交控件，并提供编辑器挂载点。"""
        classes = " ".join(filter(None, (str(kwargs.pop("class", "")), "om-rich-text-value")))
        return await render_component_template(
            form,
            f"{form.get_field_renderer().template_namespace}/widgets/rich_text.html",
            {
                "input_attrs": {
                    "id": field.id,
                    "name": field.name,
                    "class": classes,
                    "data-om-rich-text-value": True,
                    **kwargs,
                },
                "value": cast(Any, field)._value(),
            },
        )

    def __call__(self, field: Field, **kwargs: Any) -> Markup:
        """要求通过 Oldman 的异步 renderer 输出组合控件。"""
        raise RuntimeError("RichTextWidget must be rendered through async form.render() or form.render_field()")


class AjaxSelectWidget(SelectWidget):
    """远程 Select provider 的 WTForms widget。"""

    def __init__(
        self,
        *,
        provider: str,
        endpoint: str | None = None,
        route_name: str | None = None,
        page_size: int = 20,
        dependent_fields: Sequence[str] = (),
        enhance_choices: bool = False,
        tags: bool = False,
        label_mode: Literal["text", "html"] = "text",
        route_kwargs: dict[str, object] | None = None,
    ) -> None:
        """保存远程 provider 绑定配置。"""
        super().__init__()
        self.provider = provider
        self.endpoint = endpoint
        self.route_name = route_name
        self.page_size = page_size
        self.dependent_fields = tuple(dependent_fields)
        self.enhance_choices = enhance_choices or tags
        self.tags = tags
        self.label_mode: Literal["text", "html"] = label_mode
        self.route_kwargs = dict(route_kwargs or {})
        if not self.endpoint and not self.route_name:
            raise ValueError("AjaxSelectWidget requires endpoint or route_name")
        if label_mode not in {"text", "html"}:
            raise ValueError("AjaxSelectWidget label_mode must be 'text' or 'html'")
        if label_mode == "html" and not self.enhance_choices:
            raise ValueError("AjaxSelectWidget label_mode='html' requires enhance_choices=True")

    def bind_attrs(self, field: Field, form: Any) -> dict[str, Any]:
        """生成前端 Select 组件需要的 data 属性。"""
        if not form.select_secret_key:
            raise RuntimeError("AjaxSelectWidget requires form.select_secret_key")

        context = SelectContext(
            provider=self.provider,
            field_name=field.name,
            multiple=isinstance(field, SelectMultipleField),
            dependent_fields=self.dependent_fields,
            page_size=self.page_size,
            value_field="id",
            label_mode=self.label_mode,
        )
        return {
            "data-om-component": "select",
            "data-om-select-control": True,
            "data-om-select-src": self.resolve_endpoint(form),
            "data-om-select-bind": sign_select_context(context, secret_key=form.select_secret_key),
            "data-om-select-page-size": str(self.page_size),
            "data-om-select-dependent-fields": ",".join(self.dependent_fields) or None,
            "data-om-select-label-mode": self.label_mode,
            "data-choices": True if self.enhance_choices else None,
            "data-choices-removeItem": True if self.tags else None,
            "data-choices-sorting-false": True if self.tags else None,
        }

    def resolve_endpoint(self, form: Any) -> str:
        """返回远程 provider endpoint，优先使用显式 URL，其次使用 route name 反解。"""
        if self.endpoint:
            return self.endpoint
        request = getattr(form, "request", None)
        app = getattr(request, "app", None)
        if app is None or not self.route_name:
            raise RuntimeError("AjaxSelectWidget route_name requires form.request.app")
        route_kwargs = {"provider_name": self.provider, **self.route_kwargs}
        try:
            return app.url_for(self.route_name, **route_kwargs)
        except Exception:
            app_name = getattr(app, "name", "")
            return app.url_for(f"{app_name}.{self.route_name}", **route_kwargs)

    def __call__(self, field: Field, **kwargs: Any) -> Markup:
        """禁止绕过异步 renderer 直接同步渲染远程 Select。"""
        raise RuntimeError("AjaxSelectWidget must be rendered through async form.render() or form.render_field()")

    async def render_async(self, field: Field, form: Any, **kwargs: Any) -> Markup:
        """通过模板渲染远程 select 控件。"""
        return await render_component_template(
            form,
            f"{form.get_field_renderer().template_namespace}/widgets/ajax_select.html",
            {
                "attrs": {"id": field.id, "name": field.name, "multiple": isinstance(field, SelectMultipleField), **kwargs},
                "field": field,
                "options": select_options(field),
            },
        )


class AjaxAutocompleteWidget:
    """远程 Autocomplete provider 的 WTForms widget。"""

    def __init__(
        self,
        *,
        provider: str,
        endpoint: str | None = None,
        route_name: str | None = None,
        page_size: int = 20,
        dependent_fields: Sequence[str] = (),
        label_mode: Literal["text", "html"] = "text",
        route_kwargs: dict[str, object] | None = None,
    ) -> None:
        """保存远程 provider 绑定配置。"""
        self.provider = provider
        self.endpoint = endpoint
        self.route_name = route_name
        self.page_size = page_size
        self.dependent_fields = tuple(dependent_fields)
        self.label_mode: Literal["text", "html"] = label_mode
        self.route_kwargs = dict(route_kwargs or {})
        if not self.endpoint and not self.route_name:
            raise ValueError("AjaxAutocompleteWidget requires endpoint or route_name")
        if label_mode not in {"text", "html"}:
            raise ValueError("AjaxAutocompleteWidget label_mode must be 'text' or 'html'")

    def bind_attrs(self, field: Field, form: Any) -> dict[str, Any]:
        """生成前端 Autocomplete 组件需要的 data 属性。"""
        if not form.select_secret_key:
            raise RuntimeError("AjaxAutocompleteWidget requires form.select_secret_key")

        context = SelectContext(
            provider=self.provider,
            field_name=field.name,
            multiple=False,
            dependent_fields=self.dependent_fields,
            page_size=self.page_size,
            value_field="id",
            label_mode=self.label_mode,
        )
        return {
            "data-om-component": "autocomplete",
            "data-om-select-src": self.resolve_endpoint(form),
            "data-om-select-bind": sign_select_context(context, secret_key=form.select_secret_key),
            "data-om-select-page-size": str(self.page_size),
            "data-om-select-dependent-fields": ",".join(self.dependent_fields) or None,
            "data-om-select-label-mode": self.label_mode,
        }

    def resolve_endpoint(self, form: Any) -> str:
        """返回远程 autocomplete provider endpoint。"""
        if self.endpoint:
            return self.endpoint
        request = getattr(form, "request", None)
        app = getattr(request, "app", None)
        if app is None or not self.route_name:
            raise RuntimeError("AjaxAutocompleteWidget route_name requires form.request.app")
        route_kwargs = {"provider_name": self.provider, **self.route_kwargs}
        try:
            return app.url_for(self.route_name, **route_kwargs)
        except Exception:
            app_name = getattr(app, "name", "")
            return app.url_for(f"{app_name}.{self.route_name}", **route_kwargs)

    async def render_async(self, field: Field, form: Any, **kwargs: Any) -> Markup:
        """通过模板渲染 autocomplete 控件。"""
        return await render_component_template(
            form,
            f"{form.get_field_renderer().template_namespace}/widgets/ajax_autocomplete.html",
            {
                "field": field,
                "input_attrs": autocomplete_input_attrs(field, kwargs),
                "root_attrs": {key: value for key, value in kwargs.items() if key.startswith("data-om-")},
                "value": "" if field.data is None else field.data,
            },
        )

    def __call__(self, field: Field, **kwargs: Any) -> Markup:
        """禁止绕过异步 renderer 直接同步渲染远程 Autocomplete。"""
        raise RuntimeError("AjaxAutocompleteWidget must be rendered through async form.render() or form.render_field()")


class DateTimePickerWidget:
    """显式 opt-in 的 Oldman flatpickr 日期时间 widget。"""

    def __init__(
        self,
        *,
        date_format: str = "Y-m-d\\TH:i",
        enable_time: bool = True,
        provider: str = "flatpickr",
        input_type: str = "text",
        extra_attrs: dict[str, Any] | None = None,
    ) -> None:
        """保存 datetime picker 渲染配置。"""
        self.date_format = date_format
        self.enable_time = enable_time
        self.provider = provider
        self.input_type = input_type
        self.extra_attrs = dict(extra_attrs or {})

    def bind_attrs(self, field: Field, form: Any) -> dict[str, Any]:
        """生成前端 DateTimePicker 组件需要的 data 属性。"""
        attrs: dict[str, Any] = {
            "type": self.input_type,
            "autocomplete": "off",
            "data-om-component": "date-time-picker",
            "data-provider": self.provider,
            "data-date-format": self.date_format,
        }
        if self.enable_time:
            attrs["data-enable-time"] = True
        attrs.update(self.extra_attrs)
        return attrs

    def __call__(self, field: Field, **kwargs: Any) -> Markup:
        """渲染输入框；属性由 FieldRenderer.widget_attrs 合并。"""
        return TextInput()(field, **kwargs)


def select_options(field: Field) -> list[dict[str, object]]:
    """把 WTForms choices 转换为模板 option 上下文。"""
    data = getattr(field, "data", None)
    selected_values = {str(item) for item in data} if isinstance(data, (list, tuple, set)) else {str(data)} if data not in {None, ""} else set()
    options: list[dict[str, object]] = []
    for value, label, *_rest in getattr(field, "choices", []) or []:
        options.append({"value": value, "label": label, "selected": str(value) in selected_values})
    return options


def autocomplete_input_attrs(field: Field, attrs: dict[str, Any]) -> dict[str, Any]:
    """生成 autocomplete 可见输入框属性。"""
    input_attrs = {
        key: value
        for key, value in attrs.items()
        if not key.startswith("data-om-select-") and key not in {"data-om-component"}
    }
    input_attrs.update(
        {
            "id": field.id,
            "type": "text",
            "autocomplete": "off",
            "data-om-autocomplete-input": True,
        }
    )
    return input_attrs


__all__ = [
    "AjaxAutocompleteWidget",
    "AjaxSelectWidget",
    "ColorPickerWidget",
    "DateTimePickerWidget",
    "InputSpinnerWidget",
    "RichTextWidget",
    "TagsInputWidget",
    "TagsSelectWidget",
]
