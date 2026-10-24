"""Oldman server-rendered forms: web integration on top of the form core.

基于表单核心的后端表单封装：校验、输入与错误的语义在核心里，这里只加请求、渲染和布局。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Self, cast

from markupsafe import Markup

from oldman.i18n import LazyTranslation, gettext_lazy
from oldman.i18n.translations import current_translations
from oldman.web.api import ApiErrorCode, DefaultApiFormResponse

from ._core import Field, HiddenField
from ._core import Form as CoreForm
from ._core.form import BaseForm
from ._core.i18n import DummyTranslations
from ._core.meta import DefaultMeta
from ._core.utils import SanicFormData
from .layouts import Actions, FieldGroup, FieldLayout, FormLayout, FormStep, Row
from .renderers import _FORM_INVALID_MESSAGE, FieldRenderer, FormRenderer

_SAVE_LABEL = gettext_lazy("Save")
_CANCEL_LABEL = gettext_lazy("Cancel")
_FILTER_LABEL = gettext_lazy("Filter")


class Form(CoreForm):
    """Base class for Oldman server-rendered forms.

    Oldman 后端渲染表单基类。
    """

    # A nested Meta replaces the core's `Meta = DefaultMeta` by design: FormMeta merges every Meta in the MRO.
    class Meta(DefaultMeta):  # pyrefly: ignore[bad-override]
        """WTForms 的选项:Django 风格的字段 id,翻译取当前请求的词条目录。"""

        auto_id = "id_%s"

        def get_translations(self, form: BaseForm) -> Any:
            """Return the request catalog through WTForms' native i18n hook.

            Without one, WTForms' own untranslated messages - what its fields fall back to when
            this returns None, as ``DefaultMeta`` itself does with ``locales = False``.
            """
            request_context = getattr(getattr(form, "request", None), "ctx", None)
            request_catalog = getattr(request_context, "translations", None)
            catalog = request_catalog if request_catalog is not None else current_translations.get()
            return catalog if catalog is not None else DummyTranslations()

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
        """Initialize the form and keep the request, database session and CSRF token.

        初始化表单并保存请求、数据库 session 和 CSRF token。输入、初值与校验语义都在表单核心里。
        """
        # Meta.get_translations reads the request while the core binds the fields, so it comes first.
        self.request = request
        self.session = session
        super().__init__(*args, obj=obj, prefix=prefix, data=data, files=files, initial=initial, **kwargs)
        # CSRF token 由 oldman.web.security.csrf 的装饰器写入 request.ctx，Form 只读取并输出 hook。
        self.csrf_token = csrf_token or str(getattr(getattr(request, "ctx", None), "csrf_token", "") or "")
        self.select_secret_key = select_secret_key
        self.configure_remote_select_fields()

    def configure_remote_select_fields(self) -> None:
        """Configure field-validation boundaries for remote Select widgets.

        配置远程 Select widget 的字段校验边界。
        """
        from .widgets import AjaxAutocompleteWidget, AjaxSelectWidget

        for field in self._fields.values():
            if isinstance(getattr(field, "widget", None), (AjaxSelectWidget, AjaxAutocompleteWidget)):
                # 远程选项不在初始 HTML choices 内，WTForms 本地 choices 校验会误杀合法提交。
                cast(Any, field).validate_choice = False

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
        """Create a form instance from a Sanic request.

        从 Sanic 请求创建表单实例。
        """
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
    ) -> Form:
        """Create a GET filter form from Sanic query parameters.

        从 Sanic 查询参数创建 GET 筛选表单实例。
        """
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
        """Render complete form HTML.

        渲染完整表单 HTML。
        """
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
        """Return the current form renderer instance.

        返回当前表单的整体渲染器实例。
        """
        return self.renderer_class(self)

    def get_field_renderer(self) -> FieldRenderer:
        """Return the current form's field renderer instance.

        返回当前表单的字段渲染器实例。
        """
        return self.field_renderer_class(self)

    async def render_field(self, field: Field | str) -> Markup:
        """Render a field's label, control, and errors.

        渲染单个字段的 label、控件和错误。
        """
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
        """Render the bottom action area for partial template use.

        渲染表单底部操作区，供模板局部调用。
        """
        return await self.get_renderer().render_actions(
            submit_label=submit_label,
            cancel_url=cancel_url,
            cancel_label=cancel_label,
            extra_buttons=extra_buttons,
        )

    def visible_fields(self) -> list[Field]:
        """Return visible fields.

        返回可见字段列表。
        """
        return [field for field in self._fields.values() if not isinstance(field, HiddenField)]

    def hidden_fields(self) -> list[Field]:
        """Return hidden fields.

        返回隐藏字段列表。
        """
        return [field for field in self._fields.values() if isinstance(field, HiddenField)]

    def iter_layout(self) -> Iterable[FieldLayout]:
        """Return form-layout fields.

        返回表单布局字段。
        """
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
        """Return multi-step field groups declared in the layout.

        返回布局中声明的多步骤字段分组。
        """
        if self.layout is None:
            return ()
        steps = tuple(item for item in self.layout.items if isinstance(item, FormStep))
        if steps and any(not isinstance(item, (Actions, FormStep)) for item in self.layout.items):
            raise ValueError("FormStep layouts cannot contain fields outside a step")
        return steps

    def iter_step_layout(self, step: FormStep) -> Iterable[FieldLayout]:
        """Expand field layouts within one step.

        展开一个步骤中的字段布局。
        """
        yield from self._iter_layout_items(step.items)

    def iter_layout_segments(self) -> Iterable[tuple[FieldGroup | None, tuple[FieldLayout, ...]]]:
        """Split the top-level layout into consecutive ungrouped-field sections and individual FieldGroup sections.

        按分组切分顶层布局：连续的散字段成一段，每个 FieldGroup 自成一段。
        """
        if self.layout is None:
            yield None, tuple(self.iter_layout())
            return
        yield from self._iter_segments(self.layout.items)

    def iter_step_segments(self, step: FormStep) -> Iterable[tuple[FieldGroup | None, tuple[FieldLayout, ...]]]:
        """Split one step's layout into grouped sections.

        按分组切分一个步骤里的布局。
        """
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
        """Return actions configuration declared in the layout.

        返回布局中声明的 actions 配置。
        """
        if self.layout is None:
            return None
        for item in self.layout.items:
            if isinstance(item, Actions):
                return item
        return None

    def to_api_response(self) -> DefaultApiFormResponse:
        """Convert current form state to a common API response object.

        把当前表单状态转换为统一 API 响应对象。

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


class TableFilterForm(Form):
    """A filter form specifically for driving Table APIs.

    专门用于驱动 Table API 的筛选表单。

    ``layout_style``: ``"inline"``（默认，一行、标签嵌在控件左侧、``advanced`` 字段收进"更多筛选"）
    或 ``"grid"``（标签在上的栅格，字段很多且都要一直可见时用）。
    """

    layout_style: str = "inline"

    # Renders only as a table's filter bar: the general form options (form_mode, target, validate...) do not apply.
    async def render(  # pyrefly: ignore[bad-override]
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
        """Render Table filter-component HTML.

        渲染 Table 筛选组件 HTML。
        """
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
