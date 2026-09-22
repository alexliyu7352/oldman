"""基于 WTForms 的后端表单封装。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Self, cast

from markupsafe import Markup
from wtforms import Field, Form
from wtforms.fields import HiddenField
from wtforms.meta import DefaultMeta
from wtforms.validators import ValidationError

from oldman.i18n import LazyTranslation, gettext_lazy
from oldman.i18n.translations import current_translations
from oldman.web.api import ApiErrorCode, DefaultApiFormResponse

from .fields import JSONListField
from .layouts import Actions, FieldGroup, FieldLayout, FormLayout, FormStep, Row
from .renderers import _FORM_INVALID_MESSAGE, FieldRenderer, FormRenderer

_SAVE_LABEL = gettext_lazy("Save")
_CANCEL_LABEL = gettext_lazy("Cancel")
_FILTER_LABEL = gettext_lazy("Filter")


class SanicFormData:
    """把 Sanic 表单数据适配为 WTForms 需要的 `getlist` 协议。"""

    def __init__(self, data: Mapping[str, Any] | None, files: Mapping[str, Any] | None = None):
        """保存普通字段和上传文件映射。"""
        self.data = data or {}
        self.files = files or {}

    def getlist(self, key: str) -> list[Any]:
        """返回字段的多值列表。"""
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
        """返回字段的第一个值，兼容普通 mapping 和 Sanic 参数对象。"""
        values = self.getlist(key)
        return values[0] if values else default

    def items(self):
        """返回原始字段项，供调试和测试读取。"""
        return self.data.items()

    def __iter__(self):
        """迭代普通字段名，供 WTForms FieldList 发现带索引输入。"""
        return iter(self.data)

    def to_dict(self) -> dict[str, Any]:
        """把原始输入转换为普通 dict，保留多值字段列表。"""
        return {key: values[0] if len(values) == 1 else values for key in self.data for values in [self.getlist(key)]}

    def __contains__(self, key: str) -> bool:
        """判断字段是否存在。"""
        return key in self.files or key in self.data


class OldmanFormMeta(DefaultMeta):
    """Oldman 表单字段绑定策略。"""

    auto_id = "id_%s"

    def get_translations(self, form: Any):
        """Return the request catalog through WTForms' native i18n hook."""
        request_context = getattr(getattr(form, "request", None), "ctx", None)
        request_catalog = getattr(request_context, "translations", None)
        return request_catalog if request_catalog is not None else current_translations.get()

    def bind_field(self, form, unbound_field, options):
        """在 WTForms 字段绑定源头生成 Django 风格 id。"""
        field_options = dict(options)
        render_kw = unbound_field.kwargs.get("render_kw") or {}
        explicit_id = unbound_field.kwargs.get("id") or render_kw.get("id")

        if explicit_id:
            field_options["id"] = str(explicit_id)
        elif self.auto_id:
            html_name = f"{field_options.get('prefix', '')}{field_options['name']}"
            field_options["id"] = self.auto_id % html_name

        return super().bind_field(form, unbound_field, field_options)


class OldmanForm(Form):
    """Oldman 后端渲染表单基类。"""

    class Meta(OldmanFormMeta):
        """WTForms Meta 配置。"""

    field_layout: tuple[FieldLayout | str, ...] = ()
    layout: FormLayout | None = None
    renderer_class = FormRenderer
    field_renderer_class = FieldRenderer

    def __init__(
        self,
        *args: Any,
        request: Any = None,
        data: Mapping[str, Any] | SanicFormData | None = None,
        files: Mapping[str, Any] | None = None,
        obj: Any = None,
        session: Any = None,
        initial: dict[str, Any] | None = None,
        prefix: str = "",
        csrf_token: str = "",
        select_secret_key: str = "",
        **kwargs: Any,
    ) -> None:
        """初始化表单并保存请求、数据库 session 和 CSRF token。"""
        formdata = kwargs.pop("formdata", None)
        if data is not None and formdata is not None:
            raise TypeError("OldmanForm accepts either data= or formdata=, not both")
        if isinstance(data, SanicFormData):
            bound_formdata = data
        elif data is not None:
            bound_formdata = SanicFormData(data, files)
        elif formdata is not None:
            bound_formdata = formdata
        elif files is not None:
            bound_formdata = SanicFormData(None, files)
        else:
            bound_formdata = None
        if initial is not None:
            kwargs.setdefault("data", initial)
        self.request = request
        self.session = session
        self.initial = dict(initial or {})
        self.obj = obj
        self.files = dict(files or {})
        self.prefix = prefix
        self.is_bound = bound_formdata is not None
        self._input_data = bound_formdata.to_dict() if isinstance(bound_formdata, SanicFormData) else {}
        super().__init__(*args, formdata=cast(Any, bound_formdata), obj=obj, prefix=prefix, **kwargs)
        # CSRF token 由 oldman.web.csrf 装饰器写入 request.ctx，Form 只读取并输出 hook。
        self.csrf_token = csrf_token or str(getattr(getattr(request, "ctx", None), "csrf_token", "") or "")
        self.select_secret_key = select_secret_key
        self._cleaned_data: dict[str, Any] = {}
        self._error_message: str | LazyTranslation | None = None
        self._validation_succeeded = False
        self.configure_remote_select_fields()
        self._set_list_error_message()

    def configure_remote_select_fields(self) -> None:
        """配置远程 Select widget 的字段校验边界。"""
        from .widgets import AjaxAutocompleteWidget, AjaxSelectWidget

        for field in self._fields.values():
            if isinstance(getattr(field, "widget", None), (AjaxSelectWidget, AjaxAutocompleteWidget)):
                # 远程选项不在初始 HTML choices 内，WTForms 本地 choices 校验会误杀合法提交。
                cast(Any, field).validate_choice = False

    def add_error(self, field_name: str, message: str | LazyTranslation) -> None:
        """向真实字段添加一条错误，拒绝拼错或伪造的字段名。"""
        field = self._fields.get(field_name)
        if not field_name or field_name == "__all__" or field is None:
            raise ValueError(f"{field_name!r} is not a real form field")
        if not isinstance(field.errors, list):
            field.errors = list(field.errors)
        cast(list[Any], field.errors).append(message)

    @classmethod
    def from_request(
        cls,
        request,
        *,
        obj: Any = None,
        session: Any = None,
        initial: dict[str, Any] | None = None,
        prefix: str = "",
        csrf_token: str = "",
        select_secret_key: str = "",
        **kwargs: Any,
    ) -> Self:
        """从 Sanic 请求创建表单实例。"""
        is_submission = request.method.upper() in {"POST", "PUT", "PATCH"}
        files = getattr(request, "files", None) if is_submission else None
        formdata = SanicFormData(getattr(request, "form", None), files) if is_submission else None
        return cls(
            formdata=formdata,
            obj=obj,
            request=request,
            session=session,
            initial=initial,
            files=files,
            prefix=prefix,
            csrf_token=csrf_token,
            select_secret_key=select_secret_key,
            **kwargs,
        )

    @classmethod
    def from_query(
        cls, request, *, obj: Any = None, session: Any = None, initial: dict[str, Any] | None = None, prefix: str = "", **kwargs: Any
    ) -> OldmanForm:
        """从 Sanic 查询参数创建 GET 筛选表单实例。"""
        return cls(
            formdata=SanicFormData(getattr(request, "args", None)),
            obj=obj,
            request=request,
            session=session,
            initial=initial,
            prefix=prefix,
            **kwargs,
        )

    async def render(
        self,
        *,
        action: str = "",
        method: str = "post",
        form_mode: str = "html",
        target: str | None = None,
        swap: str | None = None,
        submit_label: str | LazyTranslation = _SAVE_LABEL,
        cancel_url: str | None = None,
        cancel_label: str | LazyTranslation = _CANCEL_LABEL,
        extra_buttons: Markup | str = "",
        form_class: str = "",
        component_name: str | None = "form",
        validate: bool = False,
        feedback_target: str | None = None,
    ) -> Markup:
        """渲染完整表单 HTML。"""
        return await self.get_renderer().render(
            action=action,
            method=method,
            form_mode=form_mode,
            target=target,
            swap=swap,
            submit_label=submit_label,
            cancel_url=cancel_url,
            cancel_label=cancel_label,
            extra_buttons=extra_buttons,
            form_class=form_class,
            component_name=component_name,
            validate=validate,
            feedback_target=feedback_target,
        )

    def get_renderer(self) -> FormRenderer:
        """返回当前表单的整体渲染器实例。"""
        return self.renderer_class(self)

    def get_field_renderer(self) -> FieldRenderer:
        """返回当前表单的字段渲染器实例。"""
        return self.field_renderer_class(self)

    async def render_field(self, field: Field | str) -> Markup:
        """渲染单个字段的 label、控件和错误。"""
        if isinstance(field, str):
            field = self._fields[field]
        return await self.get_field_renderer().render(field)

    async def render_actions(
        self,
        *,
        submit_label: str | LazyTranslation = _SAVE_LABEL,
        cancel_url: str | None = None,
        cancel_label: str | LazyTranslation = _CANCEL_LABEL,
        extra_buttons: Markup | str = "",
    ) -> Markup:
        """渲染表单底部操作区，供模板局部调用。"""
        return await self.get_renderer().render_actions(
            submit_label=submit_label,
            cancel_url=cancel_url,
            cancel_label=cancel_label,
            extra_buttons=extra_buttons,
        )

    def visible_fields(self) -> list[Field]:
        """返回可见字段列表。"""
        return [field for field in self._fields.values() if not isinstance(field, HiddenField)]

    def hidden_fields(self) -> list[Field]:
        """返回隐藏字段列表。"""
        return [field for field in self._fields.values() if isinstance(field, HiddenField)]

    def iter_layout(self) -> Iterable[FieldLayout]:
        """返回表单布局字段。"""
        if self.layout is not None:
            for item in self.layout.items:
                if isinstance(item, FormStep):
                    yield from self.iter_step_layout(item)
                else:
                    yield from self._iter_layout_items((item,))
            return
        if self.field_layout:
            for item in self.field_layout:
                yield item if isinstance(item, FieldLayout) else FieldLayout(item)
            return
        for name in self._fields:
            yield FieldLayout(name)

    def get_layout_steps(self) -> tuple[FormStep, ...]:
        """返回布局中声明的多步骤字段分组。"""
        if self.layout is None:
            return ()
        steps = tuple(item for item in self.layout.items if isinstance(item, FormStep))
        if steps and any(not isinstance(item, (Actions, FormStep)) for item in self.layout.items):
            raise ValueError("FormStep layouts cannot contain fields outside a step")
        return steps

    def iter_step_layout(self, step: FormStep) -> Iterable[FieldLayout]:
        """展开一个步骤中的字段布局。"""
        yield from self._iter_layout_items(step.items)

    def iter_layout_segments(self) -> Iterable[tuple[FieldGroup | None, tuple[FieldLayout, ...]]]:
        """按分组切分顶层布局：连续的散字段成一段，每个 FieldGroup 自成一段。"""
        if self.layout is None:
            yield None, tuple(self.iter_layout())
            return
        yield from self._iter_segments(self.layout.items)

    def iter_step_segments(self, step: FormStep) -> Iterable[tuple[FieldGroup | None, tuple[FieldLayout, ...]]]:
        """按分组切分一个步骤里的布局。"""
        yield from self._iter_segments(step.items)

    def _iter_segments(self, items: Iterable[object]) -> Iterable[tuple[FieldGroup | None, tuple[FieldLayout, ...]]]:
        pending: list[FieldLayout] = []
        for item in items:
            if isinstance(item, (Actions, FormStep)):
                continue
            if isinstance(item, FieldGroup):
                if pending:
                    yield None, tuple(pending)
                    pending = []
                yield item, tuple(self._iter_layout_items(item.items))
            else:
                pending.extend(self._iter_layout_items((item,)))
        if pending:
            yield None, tuple(pending)

    def _iter_layout_items(self, items: Iterable[object]) -> Iterable[FieldLayout]:
        """把字符串、Row、FieldGroup 和 FieldLayout 统一展开为字段布局。"""
        for item in items:
            if isinstance(item, Row):
                if item.as_range:
                    start, end = item.fields
                    yield FieldLayout(start, item.width, advanced=item.advanced, range_end=end, range_label=item.label)
                    continue
                for field_name in item.fields:
                    yield FieldLayout(field_name, item.width, advanced=item.advanced)
            elif isinstance(item, FieldGroup):
                yield from self._iter_layout_items(item.items)
            elif isinstance(item, FieldLayout):
                yield item
            elif isinstance(item, str):
                yield FieldLayout(item)

    def get_layout_actions(self) -> Actions | None:
        """返回布局中声明的 actions 配置。"""
        if self.layout is None:
            return None
        for item in self.layout.items:
            if isinstance(item, Actions):
                return item
        return None

    async def is_valid(self) -> bool:
        """执行异步表单校验并返回是否通过。"""
        return await self.validate()

    async def validate(self, extra_validators: dict[str, Any] | None = None) -> bool:
        """执行 WTForms 同步校验和 Oldman 异步 clean 生命周期。"""
        self._cleaned_data = {}
        self._error_message = None
        self._validation_succeeded = False
        if not self.is_bound:
            for field in self._fields.values():
                field.errors = []
            return False

        await self.prepare_async_fields()
        fields_valid = super().validate(extra_validators=extra_validators)
        self._set_list_error_message()

        for name, field in self._fields.items():
            # HiddenField 只是"不渲染成可见控件"，它承载的仍然是数据——声明一个
            # HiddenField("record_id") 就是为了把它读回来。渲染器按类型跳过它是对的
            # （隐藏字段由 hidden_fields() 统一输出），但数据层跳过它就让这个字段没法用：
            # 调用方拿到 KeyError，populate_obj() 也不会写它。WTForms 自己的 form.data
            # 是包含隐藏字段的。
            if field.errors or getattr(field, "list_errors", None):
                continue
            self._cleaned_data[name] = field.data
            cleaner = getattr(self, f"clean_{name}", None)
            if cleaner is None:
                continue
            try:
                cleaned_value = await cleaner()
            except ValidationError as exc:
                self.add_error(name, _validation_error_message(exc))
            else:
                self._cleaned_data[name] = cleaned_value
            if field.errors:
                self._cleaned_data.pop(name, None)

        try:
            form_cleaned_data = await self.clean()
        except ValidationError as exc:
            self._error_message = _validation_error_message(exc)
            form_cleaned_data = None
        if isinstance(form_cleaned_data, dict):
            # 合并而不是替换。替换语义下，一个只想补一个键的子类
            # （`return {"extra": 1}`）会静默丢光所有字段数据，而且不报错。
            # 想覆盖某个键照样可以——同名键以返回值为准。
            self._cleaned_data.update(form_cleaned_data)
        errors = self.errors
        for name in errors:
            self._cleaned_data.pop(name, None)
        self._validation_succeeded = fields_valid and not errors and self._error_message is None
        return self._validation_succeeded

    async def clean(self) -> dict[str, Any] | None:
        """执行跨字段校验，业务子类可覆盖。

        返回 `None` 表示不改动 `cleaned_data`；返回 dict 则把其中的键**合并**进去，
        同名键以返回值为准。跨字段错误用 `raise ValidationError(...)` 报，它会成为表单级
        错误消息。
        """
        return None

    @property
    def data(self) -> dict[str, Any]:
        """返回原始输入数据，和 cleaned_data 区分。"""
        return dict(self._input_data)

    @property
    def cleaned_data(self) -> dict[str, Any]:
        """返回通过验证后的字段数据。"""
        return dict(self._cleaned_data)

    def populate_obj(self, obj: Any) -> None:
        """把 cleaned_data 中的字段写回普通对象。"""
        for field_name, value in self._cleaned_data.items():
            setattr(obj, field_name, value)

    @property
    def errors(self) -> dict[str, list[str | LazyTranslation]]:
        """返回每个真实字段的完整错误列表。"""
        errors: dict[str, list[str | LazyTranslation]] = {}
        for name, field in self._fields.items():
            if isinstance(field, JSONListField):
                for entry in field.entries:
                    if entry.errors:
                        errors[entry.name] = list(entry.errors)
            elif field.errors:
                errors[name] = list(field.errors)
        return errors

    @property
    def error_message(self) -> str | LazyTranslation | None:
        """返回无法归属到具体字段的顶部校验消息。"""
        return self._error_message

    def to_api_response(self) -> DefaultApiFormResponse:
        """把当前表单状态转换为统一 API 响应对象。

        每个字段只带**第一条**错误，因为前端一个字段下面只显示一条提示。这和 `errors`
        属性的形状不同——那里是完整的列表——所以要拿全部错误请读 `errors`，不要从这个
        响应里推断。
        """
        errors = self.errors
        if errors or self._error_message is not None:
            return DefaultApiFormResponse(
                error_code=ApiErrorCode.FORM_INVALID,
                message=self._error_message or _FORM_INVALID_MESSAGE,
                errors={(self._fields[name].name if name in self._fields else name): messages[0] for name, messages in errors.items() if messages},
            )
        return DefaultApiFormResponse(error_code=ApiErrorCode.OK)

    async def prepare_async_fields(self) -> None:
        """准备需要异步数据源的字段。"""
        for field in self._fields.values():
            prepare = getattr(field, "prepare_choices", None)
            if prepare is None:
                continue
            await prepare(self)

    def _set_list_error_message(self) -> None:
        """把第一个列表级错误放入表单唯一顶部消息。"""
        for field in self._fields.values():
            list_errors = getattr(field, "list_errors", None)
            if list_errors:
                self._error_message = list_errors[0]
                return


def _validation_error_message(error: ValidationError) -> str | LazyTranslation:
    """保留 ValidationError 中的延迟翻译，其他值规范成文本。"""
    message = error.args[0] if error.args else str(error)
    return message if isinstance(message, (str, LazyTranslation)) else str(message)


class TableFilterForm(OldmanForm):
    """专门用于驱动 Table API 的筛选表单。

    ``layout_style``: ``"inline"``（默认，一行、标签嵌在控件左侧、``advanced`` 字段收进"更多筛选"）
    或 ``"grid"``（标签在上的栅格，字段很多且都要一直可见时用）。
    """

    layout_style: str = "inline"

    async def render(
        self,
        *,
        table_target: str = "",
        action: str = "",
        method: str = "get",
        submit_label: str | LazyTranslation = _FILTER_LABEL,
        cancel_url: str | None = None,
        cancel_label: str | LazyTranslation = _CANCEL_LABEL,
        extra_buttons: Markup | str = "",
        form_class: str = "",
    ) -> Markup:
        """渲染 Table 筛选组件 HTML。"""
        if not table_target:
            raise ValueError("table_target is required")
        return await self.get_renderer().render_table_filter(
            action=action,
            method=method,
            table_target=table_target,
            submit_label=submit_label,
            cancel_url=cancel_url,
            cancel_label=cancel_label,
            extra_buttons=extra_buttons,
            form_class=form_class,
        )
