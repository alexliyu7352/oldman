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
_MORE_FILTERS_LABEL = gettext_lazy("More filters")
_RESET_LABEL = gettext_lazy("Reset")
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
        layout_style = str(getattr(self.form, "layout_style", "inline") or "inline")
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
            "data-om-layout": layout_style,
            "novalidate": True,
        }
        if layout_style == "inline":
            return await self.render_inline_filter(attrs, submit_label=submit_label, extra_buttons=extra_buttons)
        return await self.render_with_attrs(
            attrs,
            method=method,
            submit_label=submit_label,
            cancel_url=cancel_url,
            cancel_label=cancel_label,
            extra_buttons=extra_buttons,
            validator=False,
        )

    async def render_inline_filter(self, attrs: dict[str, Any], *, submit_label: object, extra_buttons: Markup | str) -> Markup:
        """一行式筛选条：搜索框、带前缀标签的控件、范围控件、"更多筛选"面板和右端动作。"""
        await self.form.prepare_async_fields()
        field_renderer = self.form.get_field_renderer()
        search_html: Markup | None = None
        controls: list[Markup] = []
        advanced: list[Any] = []
        for layout in self.form.iter_layout():
            field = self.form._fields.get(layout.name)
            if field is None or isinstance(field, HiddenField):
                continue
            if layout.advanced:
                advanced.append(layout)
                continue
            if layout.range_end:
                end_field = self.form._fields.get(layout.range_end)
                if end_field is None:
                    raise ValueError(f"Range end field {layout.range_end!r} does not exist")
                controls.append(await field_renderer.render_filter_range(field, end_field, label=layout.range_label))
            elif search_html is None and is_search_field(field):
                search_html = await field_renderer.render_filter_search(field)
            else:
                controls.append(await field_renderer.render_filter_control(field))
        advanced_fields = await self._render_field_layouts(advanced)
        return await render_component_template(
            self.form,
            self.template_name("filter_inline.html"),
            {
                "advanced_fields": advanced_fields,
                "attrs": attrs,
                "controls": controls,
                "extra_buttons": extra_buttons,
                "grid_class": self.fields_wrapper_class,
                "hidden_fields": [field() for field in self.form.hidden_fields()],
                "message_html": await self.render_message(),
                "more_label": display_text(_MORE_FILTERS_LABEL),
                "reset_label": display_text(_RESET_LABEL),
                "search_html": search_html,
                "status_html": await self.render_status(),
                "submit_label": display_text(submit_label),
            },
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
                        "fields_html": await self._render_segments(self.form.iter_step_segments(step)),
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
        return await self._render_segments(self.form.iter_layout_segments())

    async def _render_segments(self, segments: Iterable[tuple[Any, Iterable[Any]]]) -> Markup:
        """渲染按 FieldGroup 切分的字段布局；`fields` 仍给出扁平列表以兼容自定义模板。"""
        rendered_segments: list[dict[str, Any]] = []
        flat_fields: list[dict[str, Any]] = []
        for group, layouts in segments:
            fields = await self._render_field_layouts(layouts)
            if not fields:
                continue
            flat_fields.extend(fields)
            rendered_segments.append(
                {
                    "fields": fields,
                    "group": None
                    if group is None
                    else {
                        "description": display_text(group.description) if group.description else "",
                        "title": display_text(group.title),
                    },
                    "grid_class": self.fields_wrapper_class,
                }
            )
        return await render_component_template(
            self.form,
            self.template_name("fields.html"),
            {"fields": flat_fields, "segments": rendered_segments},
        )

    async def _render_field_layouts(self, layouts: Iterable[Any]) -> list[dict[str, Any]]:
        """展开一组字段布局为模板条目。"""
        fields: list[dict[str, Any]] = []
        for layout in layouts:
            field = self.form._fields.get(layout.name)
            if field is None or isinstance(field, HiddenField):
                continue
            if layout.range_end:
                end_field = self.form._fields.get(layout.range_end)
                if end_field is None:
                    raise ValueError(f"Range end field {layout.range_end!r} does not exist")
                field_html = await self.form.get_field_renderer().render_range_field(field, end_field, label=layout.range_label)
            else:
                field_html = await self.form.render_field(field)
            fields.append(
                {
                    "attrs": {
                        "class": css_classes(layout_width_classes(layout.width), self.field_wrapper_extra_class),
                        "data-om-form-field": True,
                        "data-om-form-field-name": field.name,
                    },
                    "field": field,
                    "field_html": field_html,
                    "layout": layout,
                }
            )
        return fields

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
                # 原样当 HTML 插入，不转义。类型允许 str 是为了方便，但语义是"调用方保证
                # 这段 HTML 可信"——和 MessageFormat.HTML、modal_response 的 html 一样。
                # 任何用户数据在传进来之前必须自己转义。
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
    #: Presentation used when a BooleanField keeps WTForms' plain CheckboxInput: checkbox | switch | switch-card.
    default_boolean_presentation = "checkbox"
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
                    "class": "oldman-icon-button oldman-icon-button-sm absolute right-0.5 top-1/2 -translate-y-1/2",
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

    def boolean_presentation(self, field: BooleanField) -> str:
        """返回布尔字段的呈现方式：widget 自带的优先，否则用 renderer 默认。"""
        presentation = getattr(getattr(field, "widget", None), "presentation", None)
        return str(presentation or self.default_boolean_presentation)

    async def render_boolean_field(self, field: BooleanField) -> Markup:
        """渲染布尔字段：复选框行、开关行或开关卡片。"""
        presentation = self.boolean_presentation(field)
        extra_attrs: dict[str, Any] = {}
        if presentation != "checkbox" and getattr(getattr(field, "widget", None), "presentation", None) is None:
            extra_attrs["role"] = "switch"
        control = await self.render_widget(field, **extra_attrs)
        help_text = await self.render_help(field)
        errors = await self.render_field_errors(field)
        template = "boolean_switch_card.html" if presentation == "switch-card" else "boolean_field.html"
        return await render_component_template(
            self.form,
            self.template_name(template),
            {
                "control_html": control,
                "errors_html": errors,
                "field": field,
                "help_html": help_text,
                "label_attrs": {"class": self.boolean_label_class or None, "for": field.id},
                "label_text": display_text(field.label.text),
                "presentation": presentation,
                "wrapper_attrs": {"class": self.boolean_wrapper_class or None, "data-om-boolean": presentation},
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

    async def render_range_field(self, start: Field, end: Field, *, label: object = None) -> Markup:
        """栅格布局里的范围字段：范围标签（默认取起点字段标签）+ 两个控件并排。"""
        return await render_component_template(
            self.form,
            self.template_name("range_field.html"),
            {
                "end_html": await self.render_widget(end, **{"aria-label": display_text(end.label.text)}),
                "errors_html": Markup("").join([await self.render_field_errors(start), await self.render_field_errors(end)]),
                "field": start,
                "help_html": await self.render_help(start),
                "label_attrs": {"class": self.label_class or None, "for": start.id},
                "label_text": display_text(label) if label else display_text(start.label.text),
                "start_html": await self.render_widget(start, **{"aria-label": display_text(start.label.text)}),
            },
        )

    async def render_filter_search(self, field: Field) -> Markup:
        """inline 筛选条的搜索框：无前缀，占满剩余宽度。"""
        return await render_component_template(
            self.form,
            self.template_name("filter_search.html"),
            {
                "control_html": await self.render_widget(field),
                "field": field,
                "label_text": display_text(field.label.text),
            },
        )

    async def render_filter_control(self, field: Field) -> Markup:
        """inline 筛选条的控件：标签是控件左侧的前缀段。"""
        return await render_component_template(
            self.form,
            self.template_name("filter_control.html"),
            {
                "control_html": await self.render_widget(field),
                "field": field,
                "label_text": display_text(field.label.text),
            },
        )

    async def render_filter_range(self, start: Field, end: Field, *, label: object = None) -> Markup:
        """inline 筛选条的范围控件：一个前缀（默认取起点字段标签），起止两个输入。"""
        return await render_component_template(
            self.form,
            self.template_name("filter_range.html"),
            {
                "end_html": await self.render_widget(end, **{"aria-label": display_text(end.label.text)}),
                "field": start,
                "label_text": display_text(label) if label else display_text(start.label.text),
                "start_html": await self.render_widget(start, **{"aria-label": display_text(start.label.text)}),
            },
        )

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
    boolean_label_class = "om-boolean-label"
    boolean_wrapper_class = "om-boolean-row"
    default_boolean_presentation = "switch-card"
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
            return "om-check" if self.boolean_presentation(field) == "checkbox" else "om-switch"
        if isinstance(field, PasswordField) and self.password_toggle_enabled(field):
            return "om-field pe-11"
        if isinstance(getattr(field, "widget", None), InputSpinnerWidget):
            return "om-field om-input-spinner-control"
        return "om-field"

    def invalid_class(self) -> str:
        """返回字段错误 class。"""
        return "border-danger focus:border-danger focus:ring-danger/20"


def is_search_field(field: Field) -> bool:
    """搜索框：``render_kw["type"] == "search"`` 或字段名是 ``q`` / ``search``。"""
    render_kw = getattr(field, "render_kw", None) or {}
    return str(render_kw.get("type", "")).lower() == "search" or field.name in {"q", "search"}


def layout_width_classes(width: str) -> str:
    """返回声明式 Tailwind grid column span。"""
    if not width:
        return ""
    return " ".join(width.split())


__all__ = ["FieldRenderer", "FormRenderer", "TailwindFieldRenderer", "TailwindFormRenderer", "layout_width_classes"]
