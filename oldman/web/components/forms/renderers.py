"""Form renderer 协议和模板化主题输出。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any, cast

from markupsafe import Markup
from wtforms import BooleanField, Field, PasswordField, RadioField, SelectField, SelectMultipleField
from wtforms.fields import HiddenField

from oldman.i18n import gettext_lazy
from oldman.web.html import css_classes, void_tag
from oldman.web.template import render_component_template

from .fields import JSONListField, SlugField, UploadField
from .widgets import AjaxAutocompleteWidget, AjaxSelectWidget, DateTimePickerWidget, InputSpinnerWidget

_SAVE_LABEL = gettext_lazy("Save")
_CANCEL_LABEL = gettext_lazy("Cancel")
_FILTER_LABEL = gettext_lazy("Filter")
_SHOW_PASSWORD_LABEL = gettext_lazy("Show password")
_HIDE_PASSWORD_LABEL = gettext_lazy("Hide password")
_FORM_INVALID_MESSAGE = gettext_lazy("Form validation failed")
_ADD_ITEM_LABEL = gettext_lazy("Add item")
_REMOVE_ITEM_LABEL = gettext_lazy("Remove item")
_MOVE_ITEM_UP_LABEL = gettext_lazy("Move item up")
_MOVE_ITEM_DOWN_LABEL = gettext_lazy("Move item down")
_FORM_STEPS_LABEL = gettext_lazy("Form steps")
_PREVIOUS_LABEL = gettext_lazy("Previous")
_NEXT_LABEL = gettext_lazy("Next")


def display_text(value: object) -> str:
    """Resolve lazy text without treating arbitrary strings as message ids."""
    return str(value)


class FormRenderer:
    """无主题表单整体 renderer。"""

    template_namespace = "oldman/forms/default"
    fields_wrapper_class = ""
    field_wrapper_extra_class = ""
    status_class = ""
    error_class = ""
    actions_class = ""
    submit_button_class = ""
    cancel_button_class = ""

    def __init__(self, form: Any) -> None:
        """保存当前要渲染的表单实例。"""
        self.form = form

    async def render(self, **kwargs: Any) -> Markup:
        """渲染完整表单 HTML。"""
        action = kwargs.get("action", "")
        method = kwargs.get("method", "post")
        form_mode = kwargs.get("form_mode", "html")
        target = kwargs.get("target")
        swap = kwargs.get("swap")
        submit_label = kwargs.get("submit_label", _SAVE_LABEL)
        cancel_url = kwargs.get("cancel_url")
        cancel_label = kwargs.get("cancel_label", _CANCEL_LABEL)
        extra_buttons = kwargs.get("extra_buttons", "")
        form_class = kwargs.get("form_class", "")
        component_name = kwargs.get("component_name", "form")
        validate = bool(kwargs.get("validate", False))
        feedback_target = kwargs.get("feedback_target")

        if form_mode not in {"json", "html"}:
            raise ValueError("form_mode must be 'json' or 'html'")
        if swap not in {None, "inner", "outer"}:
            raise ValueError("swap must be 'inner' or 'outer'")

        layout_actions = self.form.get_layout_actions()
        if layout_actions is not None:
            submit_label = layout_actions.submit
            cancel_url = layout_actions.cancel_url
            cancel_label = layout_actions.cancel_label

        has_steps = bool(self.form.get_layout_steps())
        attrs = {
            "method": method,
            "action": action or None,
            "class": form_class or None,
            "data-om-component": component_name or None,
            "data-om-form": True,
            "data-om-form-mode": form_mode if form_mode != "html" else None,
            "data-om-target": target,
            "data-om-swap": swap,
            "data-om-form-validate": True if validate or has_steps else None,
            "data-om-feedback-target": feedback_target,
            "novalidate": True,
        }
        return await self.render_with_attrs(
            attrs,
            method=method,
            submit_label=submit_label,
            cancel_url=cancel_url,
            cancel_label=cancel_label,
            extra_buttons=extra_buttons,
            validator=validate or has_steps,
        )

    async def render_table_filter(self, **kwargs: Any) -> Markup:
        """渲染 TableFilterForm 专用 HTML。"""
        action = kwargs.get("action", "")
        method = kwargs.get("method", "get")
        table_target = kwargs.get("table_target")
        submit_label = kwargs.get("submit_label", _FILTER_LABEL)
        cancel_url = kwargs.get("cancel_url")
        cancel_label = kwargs.get("cancel_label", _CANCEL_LABEL)
        extra_buttons = kwargs.get("extra_buttons", "")
        form_class = css_classes("om-filter-toolbar", kwargs.get("form_class", ""))

        if not table_target:
            raise ValueError("table_target is required")

        layout_actions = self.form.get_layout_actions()
        if layout_actions is not None:
            submit_label = layout_actions.submit
            cancel_url = layout_actions.cancel_url
            cancel_label = layout_actions.cancel_label

        attrs = {
            "method": method,
            "action": action or None,
            "class": form_class or None,
            "data-om-component": "table-filter-form",
            "data-om-table-target": table_target,
            "novalidate": True,
        }
        return await self.render_with_attrs(
            attrs,
            method=method,
            submit_label=submit_label,
            cancel_url=cancel_url,
            cancel_label=cancel_label,
            extra_buttons=extra_buttons,
            validator=False,
        )

    async def render_with_attrs(
        self,
        attrs: dict[str, Any],
        *,
        method: str,
        submit_label: object,
        cancel_url: str | None,
        cancel_label: object,
        extra_buttons: Markup | str,
        validator: bool = False,
    ) -> Markup:
        """使用指定 form 属性渲染完整表单模板。"""
        if any(isinstance(field, UploadField) for field in self.form._fields.values()):
            attrs["enctype"] = "multipart/form-data"
        await self.form.prepare_async_fields()
        csrf_field = Markup("")
        if method.lower() != "get" and self.form.csrf_token:
            csrf_field = void_tag("input", {"type": "hidden", "name": "csrfmiddlewaretoken", "value": self.form.csrf_token})
        has_steps = bool(self.form.get_layout_steps())
        return await render_component_template(
            self.form,
            self.template_name("form.html"),
            {
                "actions_html": await self.render_actions(
                    submit_label=submit_label,
                    cancel_url=cancel_url,
                    cancel_label=cancel_label,
                    extra_buttons=extra_buttons,
                ),
                "attrs": attrs,
                "csrf_field": csrf_field,
                "fields_html": await self.render_fields(),
                "fields_wrapper_class": "" if has_steps else self.fields_wrapper_class,
                "hidden_fields": [field() for field in self.form.hidden_fields()],
                "message_html": await self.render_message(),
                "status_html": await self.render_status(),
                "validator": validator,
            },
        )

    def template_name(self, name: str) -> str:
        """返回当前 renderer 使用的模板路径。"""
        return f"{self.template_namespace}/{name}"

    async def render_fields(self) -> Markup:
        """按字段布局渲染表单字段。"""
        steps = self.form.get_layout_steps()
        if steps:
            rendered_steps = []
            for index, step in enumerate(steps):
                rendered_steps.append(
                    {
                        "description": display_text(step.description) if step.description else "",
                        "fields_html": await self._render_field_layouts(self.form.iter_step_layout(step)),
                        "index": index,
                        "title": display_text(step.title),
                    }
                )
            return await render_component_template(
                self.form,
                self.template_name("multi_step.html"),
                {
                    "field_grid_class": self.fields_wrapper_class,
                    "form_steps_label": display_text(_FORM_STEPS_LABEL),
                    "next_label": display_text(_NEXT_LABEL),
                    "navigation_attrs": {"class": self.actions_class or None, "data-om-step-navigation": True, "hidden": True},
                    "next_attrs": {"type": "button", "class": self.submit_button_class or None, "data-om-step-next": True},
                    "previous_label": display_text(_PREVIOUS_LABEL),
                    "previous_attrs": {"type": "button", "class": self.cancel_button_class or None, "data-om-step-previous": True},
                    "steps": rendered_steps,
                },
            )
        return await self._render_field_layouts(self.form.iter_layout())

    async def _render_field_layouts(self, layouts: Iterable[Any]) -> Markup:
        """渲染一组已经展开的字段布局。"""
        fields: list[dict[str, Any]] = []
        for layout in layouts:
            field = self.form._fields.get(layout.name)
            if field is None or isinstance(field, HiddenField):
                continue
            fields.append(
                {
                    "attrs": {
                        "class": css_classes(layout_width_classes(layout.width), self.field_wrapper_extra_class),
                        "data-om-form-field": True,
                        "data-om-form-field-name": field.name,
                    },
                    "field": field,
                    "field_html": await self.form.render_field(field),
                    "layout": layout,
                }
            )
        return await render_component_template(self.form, self.template_name("fields.html"), {"fields": fields})

    async def render_status(self) -> Markup:
        """渲染前端 Form 组件用于显示提交状态的锚点。"""
        return await render_component_template(
            self.form,
            self.template_name("status.html"),
            {
                "attrs": {
                    "class": self.status_class or None,
                    "data-om-form-status": True,
                    "role": "status",
                    "aria-live": "polite",
                    "hidden": True,
                }
            },
        )

    async def render_actions(self, *, submit_label: object, cancel_url: str | None, cancel_label: object, extra_buttons: Markup | str) -> Markup:
        """渲染表单底部按钮。"""
        return await render_component_template(
            self.form,
            self.template_name("actions.html"),
            {
                "attrs": {"class": self.actions_class or None, "data-om-form-actions": True},
                "cancel_attrs": {
                    "href": cancel_url,
                    "class": self.cancel_button_class or None,
                    "data-om-history-back": True if cancel_url else None,
                    "data-om-history-fallback": cancel_url,
                },
                "cancel_label": display_text(cancel_label),
                "cancel_url": cancel_url,
                "extra_buttons": Markup(extra_buttons) if extra_buttons else Markup(""),
                "submit_attrs": {"type": "submit", "class": self.submit_button_class or None},
                "submit_label": display_text(submit_label),
            },
        )

    async def render_message(self) -> Markup:
        """渲染唯一的表单顶部校验消息区域。"""
        message = self.form.error_message
        if message is None and self.form.errors:
            message = _FORM_INVALID_MESSAGE
        return await render_component_template(
            self.form,
            self.template_name("message.html"),
            {
                "attrs": {
                    "class": self.error_class or None,
                    "data-om-form-message": True,
                    "data-om-tone": "error" if message is not None else None,
                    "role": "alert" if message is not None else None,
                    "hidden": message is None,
                },
                "message": display_text(message) if message is not None else "",
            },
        )


class FieldRenderer:
    """无主题字段 renderer，负责字段上下文和 widget attrs。"""

    template_namespace = "oldman/forms/default"
    label_class = ""
    boolean_label_class = ""
    boolean_wrapper_class = ""
    radio_group_class = ""
    radio_input_class = ""
    radio_option_class = ""
    help_class = ""
    error_class = ""

    def __init__(self, form: Any) -> None:
        """保存当前字段所属表单。"""
        self.form = form

    async def render(self, field: Any) -> Markup:
        """渲染单个字段 HTML。"""
        if isinstance(field, JSONListField):
            return await self.render_json_list_field(field)
        if isinstance(field, RadioField):
            return await self.render_radio_field(field)
        if isinstance(field, BooleanField):
            return await self.render_boolean_field(field)
        if isinstance(field, PasswordField) and self.password_toggle_enabled(field):
            return await self.render_password_field(field)

        control = await self.render_widget(field)
        help_text = await self.render_help(field)
        errors = await self.render_field_errors(field)
        return await render_component_template(
            self.form,
            self.template_name("field.html"),
            {
                "control_html": control,
                "errors_html": errors,
                "field": field,
                "help_html": help_text,
                "label_attrs": {"class": self.label_class or None, "for": field.id},
                "label_text": display_text(field.label.text),
            },
        )

    async def render_radio_field(self, field: RadioField) -> Markup:
        """把 RadioField 渲染为可正常布局的原生单选组。"""
        error_id = f"{field.id}-error"
        options: list[dict[str, Any]] = []
        for option in field:
            attrs = dict(getattr(option, "render_kw", None) or {})
            attrs["class"] = css_classes(attrs.get("class"), self.radio_input_class, self.invalid_class() if field.errors else None)
            attrs["aria-describedby"] = error_id
            if field.errors:
                attrs["aria-invalid"] = "true"
            options.append(
                {
                    "control_html": option(**attrs),
                    "label_attrs": {"class": self.radio_option_class or None, "for": option.id},
                    "label_text": display_text(option.label.text),
                }
            )
        return await render_component_template(
            self.form,
            self.template_name("radio_field.html"),
            {
                "attrs": {"data-om-radio-group": True},
                "errors_html": await self.render_field_errors(field, error_id=error_id),
                "field": field,
                "group_attrs": {"class": self.radio_group_class or None},
                "help_html": await self.render_help(field),
                "label_attrs": {"class": self.label_class or None},
                "label_text": display_text(field.label.text),
                "options": options,
            },
        )

    async def render_json_list_field(self, field: JSONListField) -> Markup:
        """渲染标量列表现有行和供前端克隆的空白模板。"""
        rows = [await self._json_list_row(entry, index, len(field.entries), field.min_entries) for index, entry in enumerate(field.entries)]
        template_row = await self._json_list_row(field.template_entry(), "__index__", len(field.entries), field.min_entries)
        return await render_component_template(
            self.form,
            self.template_name("json_list_field.html"),
            {
                "add_disabled": field.max_entries is not None and len(field.entries) >= field.max_entries,
                "add_label": display_text(_ADD_ITEM_LABEL),
                "field": field,
                "help_html": await self.render_help(field),
                "label_attrs": {"class": self.label_class or None},
                "label_text": display_text(field.label.text),
                "rows": rows,
                "template_row": template_row,
            },
        )

    async def _json_list_row(self, entry: Any, index: int | str, total: int, min_entries: int) -> dict[str, Any]:
        """构建一个列表子字段的模板上下文。"""
        error_id = f"{entry.id}-error"
        return {
            "control_html": await self.render_widget(entry, **{"aria-describedby": error_id}),
            "down_disabled": isinstance(index, int) and index == total - 1,
            "down_label": display_text(_MOVE_ITEM_DOWN_LABEL),
            "errors_html": await self.render_field_errors(entry, error_id=error_id),
            "field": entry,
            "index": index,
            "label_attrs": {"class": self.label_class or None, "for": entry.id},
            "label_text": display_text(entry.label.text),
            "remove_disabled": total <= min_entries,
            "remove_label": display_text(_REMOVE_ITEM_LABEL),
            "up_disabled": isinstance(index, int) and index == 0,
            "up_label": display_text(_MOVE_ITEM_UP_LABEL),
        }

    async def render_password_field(self, field: PasswordField) -> Markup:
        """渲染带共享可见性控件的密码字段。"""
        control = await self.render_widget(field)
        help_text = await self.render_help(field)
        errors = await self.render_field_errors(field)
        return await render_component_template(
            self.form,
            self.template_name("password_field.html"),
            {
                "button_attrs": {
                    "type": "button",
                    "class": "oldman-icon-button absolute right-0 top-1/2 -translate-y-1/2 text-default-500",
                    "data-om-password-toggle": True,
                    "data-om-password-visible": "false",
                    "aria-controls": field.id,
                    "aria-pressed": "false",
                    "aria-label": display_text(_SHOW_PASSWORD_LABEL),
                    "data-om-label-show": display_text(_SHOW_PASSWORD_LABEL),
                    "data-om-label-hide": display_text(_HIDE_PASSWORD_LABEL),
                },
                "control_html": control,
                "control_wrapper_attrs": {
                    "class": "relative",
                    "data-om-password-control": True,
                },
                "errors_html": errors,
                "field": field,
                "help_html": help_text,
                "label_attrs": {"class": self.label_class or None, "for": field.id},
                "label_text": display_text(field.label.text),
            },
        )

    def password_toggle_enabled(self, field: PasswordField) -> bool:
        """返回字段是否启用共享密码可见性控件。"""
        render_kw = getattr(field, "render_kw", None) or {}
        return render_kw.get("password_toggle", True) is not False

    async def render_boolean_field(self, field: BooleanField) -> Markup:
        """渲染布尔开关字段。"""
        control = await self.render_widget(field)
        errors = await self.render_field_errors(field)
        return await render_component_template(
            self.form,
            self.template_name("boolean_field.html"),
            {
                "control_html": control,
                "errors_html": errors,
                "field": field,
                "label_attrs": {"class": self.boolean_label_class or None, "for": field.id},
                "label_text": display_text(field.label.text),
                "wrapper_attrs": {"class": self.boolean_wrapper_class or None},
            },
        )

    async def render_widget(self, field: Field, **extra_attrs: Any) -> Markup:
        """渲染字段 widget，远程组件走可替换模板。"""
        attrs = self.widget_attrs(field)
        attrs.update(extra_attrs)
        widget = getattr(field, "widget", None)
        render_async = getattr(widget, "render_async", None)
        if callable(render_async):
            renderer = cast(Callable[..., Awaitable[Markup]], render_async)
            return await renderer(field, self.form, **attrs)
        return field(**attrs)

    def template_name(self, name: str) -> str:
        """返回当前字段 renderer 使用的模板路径。"""
        return f"{self.template_namespace}/{name}"

    async def render_help(self, field: Field) -> Markup:
        """渲染字段帮助文本。"""
        description = getattr(field, "description", "")
        return await render_component_template(
            self.form,
            self.template_name("help.html"),
            {
                "attrs": {"class": self.help_class or None},
                "text": display_text(description) if description else "",
            },
        )

    async def render_field_errors(self, field: Field, *, error_id: str | None = None) -> Markup:
        """渲染字段级错误。"""
        return await render_component_template(
            self.form,
            self.template_name("field_errors.html"),
            {
                "attrs": {
                    "id": error_id,
                    "class": self.error_class or None,
                    "data-om-error-for": field.name,
                    "hidden": not bool(field.errors),
                },
                "message": display_text(field.errors[0]) if field.errors else "",
            },
        )

    def widget_attrs(self, field: Field) -> dict[str, Any]:
        """根据字段类型返回控件属性。"""
        base_class = self.widget_base_class(field)
        render_kw = dict(getattr(field, "render_kw", None) or {})
        render_kw.pop("password_toggle", None)
        render_kw["class"] = css_classes(render_kw.get("class"), base_class, self.invalid_class() if field.errors else None)
        if isinstance(field, SlugField):
            render_kw["data-om-component"] = "slug-input"
            if field.source_field:
                source = self.form._fields.get(field.source_field)
                if source is None:
                    raise ValueError(f"SlugField source_field {field.source_field!r} does not exist")
                render_kw["data-om-slug-source"] = f"#{source.id}"
            if field.allow_unicode:
                render_kw["data-om-slug-allow-unicode"] = "true"
        widget = getattr(field, "widget", None)
        if isinstance(widget, (AjaxSelectWidget, AjaxAutocompleteWidget, DateTimePickerWidget)):
            render_kw.update({key: value for key, value in widget.bind_attrs(field, self.form).items() if value is not None})
            field.render_kw = dict(render_kw)
        if field.errors:
            render_kw["aria-invalid"] = "true"
        return render_kw

    def widget_base_class(self, field: Field) -> str:
        """返回无主题默认控件 class。"""
        return ""

    def invalid_class(self) -> str:
        """返回字段错误状态 class。"""
        return ""


class TailwindFormRenderer(FormRenderer):
    """Tailwind/Oldman 表单整体 renderer。"""

    template_namespace = "oldman/forms/default"
    fields_wrapper_class = "om-form-grid"
    field_wrapper_extra_class = "om-form-field min-w-0"
    status_class = "text-xs text-default-500"
    error_class = "om-alert-danger"
    actions_class = "om-form-actions om-form-actions-end"
    submit_button_class = "om-button om-button-primary"
    cancel_button_class = "om-button om-button-light"


class TailwindFieldRenderer(FieldRenderer):
    """Tailwind/Oldman 字段 renderer。"""

    template_namespace = "oldman/forms/default"
    label_class = "om-form-label"
    boolean_label_class = "text-sm font-medium text-default-700"
    boolean_wrapper_class = "flex min-h-9 items-center gap-2"
    radio_group_class = "om-radio-group"
    radio_input_class = "om-radio"
    radio_option_class = "om-radio-option"
    help_class = "om-form-help"
    error_class = "om-form-error"

    def widget_base_class(self, field: Field) -> str:
        """返回 Tailwind 控件 class。"""
        if isinstance(field, SelectMultipleField):
            return "om-select om-select-multiple"
        if isinstance(field, SelectField):
            return "om-select"
        if isinstance(field, BooleanField):
            return "om-check"
        if isinstance(field, PasswordField) and self.password_toggle_enabled(field):
            return "om-field pe-11"
        if isinstance(getattr(field, "widget", None), InputSpinnerWidget):
            return "om-field om-input-spinner-control"
        return "om-field"

    def invalid_class(self) -> str:
        """返回字段错误 class。"""
        return "border-red-300 focus:border-red-400 focus:ring-red-200/60"


def layout_width_classes(width: str) -> str:
    """返回声明式 Tailwind grid column span。"""
    if not width:
        return ""
    return " ".join(width.split())


__all__ = ["FieldRenderer", "FormRenderer", "TailwindFieldRenderer", "TailwindFormRenderer", "layout_width_classes"]
