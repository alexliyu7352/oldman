"""Oldman 后端 Form 组件当前协议测试。"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any

from sqlalchemy import Column, Numeric
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from wtforms import BooleanField, IntegerField, RadioField, SelectField, SelectMultipleField, StringField, ValidationError
from wtforms.validators import DataRequired, InputRequired

from oldman.web.api.enums import ApiErrorCode
from oldman.web.api.responses import DefaultApiFormResponse
from oldman.web.components.forms import (
    Actions,
    AjaxAutocompleteWidget,
    AjaxSelectMultipleField,
    AjaxSelectWidget,
    ColorPickerField,
    DateTimePickerWidget,
    FormLayout,
    FormStep,
    InputSpinnerWidget,
    ModelChoice,
    ModelChoiceField,
    OldmanForm,
    RichTextField,
    Row,
    SanicFormData,
    SlugField,
    TagsField,
    TagsSelectWidget,
    TailwindForm,
    TailwindModelForm,
    TailwindTableFilterForm,
)
from oldman.web.components.forms.models import model_field_for_column
from oldman.web.components.selects import verify_select_context


class AsyncProfileForm(TailwindForm):
    """测试异步 clean 生命周期的 Tailwind 表单。"""

    name = StringField("Name", validators=[DataRequired()])

    async def clean_name(self) -> str:
        """清洗名称字段并返回规范化值。"""
        return str(self.cleaned_data["name"]).strip().title()

    async def clean(self) -> None:
        """执行跨字段校验。"""
        if self.cleaned_data.get("name") == "Blocked":
            raise ValidationError("Blocked user")


class FormTestBase(DeclarativeBase):
    """隔离本文件 ModelForm 测试使用的 SQLAlchemy metadata。"""


class FormTestProfile(FormTestBase):
    """提供最小的可映射模型。"""

    __tablename__ = "task1_form_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class ProfileModelForm(TailwindModelForm):
    """验证 ModelForm 最近一次校验结果和保存边界。"""

    name = StringField("Name", validators=[DataRequired()])

    class Meta(TailwindModelForm.Meta):
        """绑定测试模型及显式可编辑字段。"""

        model = FormTestProfile
        fields = ("name",)


class RecordingSession:
    """记录 ModelForm 是否越权 add 或 flush 的最小 Session。"""

    def __init__(self) -> None:
        """初始化调用记录。"""
        self.added: list[Any] = []
        self.flush_calls = 0

    def add(self, instance: Any) -> None:
        """记录加入当前事务的实例。"""
        self.added.append(instance)

    async def flush(self) -> None:
        """记录 flush，不执行数据库 I/O。"""
        self.flush_calls += 1


class BackendFormComponentTest(unittest.TestCase):
    """验证当前 Tailwind Form 后端协议。"""

    def test_multi_step_layout_renders_one_ordinary_form(self) -> None:
        """多步骤布局只分组现有字段，不建立第二套提交协议。"""

        class WizardForm(TailwindForm):
            name = StringField("Name", validators=[DataRequired()])
            age = IntegerField("Age", validators=[InputRequired()])
            layout = FormLayout(
                FormStep("Identity", "name", description="Who are you?"),
                FormStep("Details", Row("age", width="md:col-span-6")),
                Actions(submit="Finish"),
            )

        html = str(asyncio.run(WizardForm().render(action="/wizard")))

        self.assertEqual(html.count("<form"), 1)
        self.assertIn('data-om-component="multi-step-form"', html)
        self.assertEqual(html.count("data-om-step-panel="), 2)
        self.assertEqual(html.count(' id="id_name" name="name"'), 1)
        self.assertEqual(html.count(' id="id_age" name="age"'), 1)
        self.assertIn("Who are you?", html)
        self.assertIn('data-om-form-actions', html)
        self.assertIn('data-om-component="form-validator"', html)

    def test_form_constructor_and_prefix_binding_state(self) -> None:
        """构造函数暴露绑定状态，prefix 同时影响字段 name 和数据读取。"""
        form = AsyncProfileForm(data={"profile-name": " alex "}, prefix="profile", files={"avatar": object()}, session="session")

        self.assertTrue(form.is_bound)
        self.assertEqual(form.name.name, "profile-name")
        self.assertEqual(form.name.id, "id_profile-name")
        self.assertEqual(form.data, {"profile-name": " alex "})
        self.assertEqual(set(form.files), {"avatar"})
        self.assertEqual(form.session, "session")
        self.assertTrue(asyncio.run(form.validate()))
        self.assertEqual(form.cleaned_data, {"name": "Alex"})

    def test_from_request_preserves_multivalue_form_data(self) -> None:
        """from_request 应该把 Sanic 多值表单转成 WTForms 可消费 formdata。"""

        class MultiDict(dict):
            def getlist(self, key: str) -> list[str]:
                value = self[key]
                return value if isinstance(value, list) else [value]

        class Request:
            method = "POST"
            form = MultiDict({"name": [" alex "]})
            files = {"avatar": object()}

        form = AsyncProfileForm.from_request(Request(), session="session")

        self.assertTrue(form.is_bound)
        self.assertTrue(asyncio.run(form.validate()))
        self.assertEqual(form.cleaned_data, {"name": "Alex"})
        self.assertEqual(set(form.files), {"avatar"})

    def test_get_request_with_empty_files_keeps_object_values_unbound(self) -> None:
        """GET 请求的空 files 映射不能覆盖对象提供的初始字段值。"""

        class BooleanForm(TailwindForm):
            enabled = BooleanField("Enabled")

        request = SimpleNamespace(method="GET", form={}, files={})
        form = BooleanForm.from_request(request, obj=SimpleNamespace(enabled=True))

        self.assertFalse(form.is_bound)
        self.assertTrue(form.enabled.data)

    def test_unbound_validation_stops_before_field_or_form_work(self) -> None:
        """未绑定 Form 不应查询 choices、运行 validator 或 clean 生命周期。"""
        events: list[str] = []

        class PreparedField(StringField):
            async def prepare_choices(self, form: OldmanForm) -> None:
                """记录异步字段准备是否被错误调用。"""
                del form
                events.append("prepare")

        def validate_name(form: OldmanForm, field: StringField) -> None:
            """记录 WTForms validator 是否被错误调用。"""
            del form, field
            events.append("validator")

        class ProbeForm(TailwindForm):
            name = PreparedField("Name", validators=[validate_name])

            async def clean_name(self) -> str:
                """记录字段 cleaner 是否被错误调用。"""
                events.append("clean_name")
                return str(self.name.data or "")

            async def clean(self) -> None:
                """记录 Form cleaner 是否被错误调用。"""
                events.append("clean")

        form = ProbeForm()
        form.add_error("name", "stale")

        self.assertFalse(asyncio.run(form.validate()))
        self.assertEqual([], events)
        self.assertEqual({}, form.errors)
        self.assertEqual({}, form.cleaned_data)
        self.assertIsNone(form.error_message)

    def test_from_query_is_bound_even_when_query_is_empty(self) -> None:
        """空查询仍表示用户提交了一个可校验的筛选 Form。"""

        class Request:
            args: dict[str, str] = {}

        form = AsyncProfileForm.from_query(Request())

        self.assertTrue(form.is_bound)

    def test_model_choice_empty_label_renders_with_integer_values(self) -> None:
        """ModelChoice 的空选项不能在渲染阶段执行 int("")。"""

        class Team:
            id = 1
            name = "Platform"

        class StaticChoice(ModelChoice):
            async def get_queryset(self, request: Any, session: Any) -> list[Team]:
                del request, session
                return [Team()]

        choice = StaticChoice(model=Team, empty_label="All teams")

        class FilterForm(TailwindForm):
            team_id = ModelChoiceField("Team", model_choice=choice)

        form = FilterForm()
        asyncio.run(form.team_id.prepare_choices(form))

        html = str(form.team_id())
        self.assertIn('value=""', html)
        self.assertIn('value="1"', html)

    def test_field_cleaner_can_replace_an_empty_string_with_none(self) -> None:
        """clean_<field>() 返回 None 必须作为合法最终值保存。"""

        class NullableEmailForm(TailwindForm):
            email = StringField("Email")

            async def clean_email(self) -> None:
                """把空邮箱转换成数据库可保存的 NULL。"""
                return None

        form = NullableEmailForm(data={"email": ""})

        self.assertTrue(asyncio.run(form.validate()))
        self.assertEqual({"email": None}, form.cleaned_data)

    def test_field_cleaner_validation_error_stays_on_its_field(self) -> None:
        """字段 cleaner 的 ValidationError 不应逃逸成程序异常。"""

        class InvalidFieldForm(TailwindForm):
            name = StringField("Name")

            async def clean_name(self) -> str:
                """返回一个正常的字段校验失败。"""
                raise ValidationError("Invalid name")

        form = InvalidFieldForm(data={"name": "alice"})

        self.assertFalse(asyncio.run(form.validate()))
        self.assertEqual({"name": ["Invalid name"]}, form.errors)
        self.assertEqual({}, form.cleaned_data)
        self.assertIsNone(form.error_message)

    def test_field_cleaner_program_error_is_not_hidden(self) -> None:
        """字段 cleaner 的非校验异常必须原样抛出。"""

        class BrokenFieldForm(TailwindForm):
            name = StringField("Name")

            async def clean_name(self) -> str:
                """模拟业务代码错误。"""
                raise RuntimeError("broken cleaner")

        with self.assertRaisesRegex(RuntimeError, "broken cleaner"):
            asyncio.run(BrokenFieldForm(data={"name": "alice"}).validate())

    def test_form_clean_replacement_cannot_restore_invalid_fields(self) -> None:
        """clean() 返回的新字典不能把已有错误字段放回 cleaned_data。"""

        class ReplacementForm(TailwindForm):
            invalid = StringField("Invalid", validators=[DataRequired()])
            valid = StringField("Valid")

            async def clean(self) -> dict[str, str]:
                """模拟跨字段清洗返回完整替换字典。"""
                return {"invalid": "restored", "valid": "cleaned"}

        form = ReplacementForm(data={"invalid": "", "valid": "source"})

        self.assertFalse(asyncio.run(form.validate()))
        self.assertEqual({"valid": "cleaned"}, form.cleaned_data)

    def test_form_clean_validation_error_becomes_top_message(self) -> None:
        """跨字段 ValidationError 只进入顶部 error_message。"""
        form = AsyncProfileForm(data={"name": "blocked"})

        self.assertFalse(asyncio.run(form.validate()))
        self.assertEqual({}, form.errors)
        self.assertEqual("Blocked user", form.error_message)

    def test_add_error_rejects_non_field_and_unknown_names(self) -> None:
        """拼错字段名不能静默降级成表单级错误。"""
        form = AsyncProfileForm(data={"name": "alice"})

        for field_name in (None, "__all__", "missing"):
            with self.subTest(field_name=field_name):
                with self.assertRaisesRegex(ValueError, "real form field"):
                    form.add_error(field_name, "Invalid")  # type: ignore[arg-type]

    def test_to_api_response_uses_project_default_api_form_response(self) -> None:
        """响应只暴露每个真实字段的第一条错误和统一顶部消息。"""

        def first_error(form: OldmanForm, field: StringField) -> None:
            """添加第一条字段错误。"""
            del form, field
            raise ValidationError("First error")

        def second_error(form: OldmanForm, field: StringField) -> None:
            """添加第二条字段错误。"""
            del form, field
            raise ValidationError("Second error")

        class MultipleErrorsForm(TailwindForm):
            name = StringField("Name", validators=[first_error, second_error])

        form = MultipleErrorsForm(data={"wizard-name": "alice"}, prefix="wizard")

        self.assertFalse(asyncio.run(form.validate()))
        response = form.to_api_response()
        payload = response.to_dict()

        self.assertIsInstance(response, DefaultApiFormResponse)
        self.assertEqual(payload["error_code"], ApiErrorCode.FORM_INVALID)
        self.assertEqual(["First error", "Second error"], form.errors["name"])
        self.assertEqual("First error", payload["errors"]["wizard-name"])
        self.assertEqual("Form validation failed", payload["message"])
        self.assertEqual({}, payload["data"])

    def test_to_api_response_has_no_html_or_data_shortcut(self) -> None:
        """Form 响应转换不能继续夹带 HTML 或任意业务数据。"""
        form = AsyncProfileForm(data={"name": "alice"})
        self.assertTrue(asyncio.run(form.validate()))

        with self.assertRaises(TypeError):
            form.to_api_response(data={"html": "<form></form>"})  # type: ignore[call-arg]

    def test_model_form_save_requires_latest_successful_validation(self) -> None:
        """未校验或校验失败的 ModelForm 不能修改模型。"""
        unvalidated = ProfileModelForm(data={"name": "Alice"})
        with self.assertRaisesRegex(ValueError, "validated"):
            asyncio.run(unvalidated.save())

        invalid = ProfileModelForm(data={"name": ""})
        self.assertFalse(asyncio.run(invalid.validate()))
        with self.assertRaisesRegex(ValueError, "validated"):
            asyncio.run(invalid.save())

    def test_model_form_subclass_keeps_inherited_declared_fields(self) -> None:
        """布局专用子类不能把父类显式字段重新猜测成模型字段。"""

        class ChildProfileForm(ProfileModelForm):
            pass

        self.assertIs(ChildProfileForm.name, ProfileModelForm.name)

    def test_model_form_commit_flag_only_controls_add_and_flush(self) -> None:
        """commit=False 只改实例，commit=True 才加入并 flush 当前事务。"""
        passive_session = RecordingSession()
        passive = ProfileModelForm(data={"name": "Alice"}, session=passive_session)
        self.assertTrue(asyncio.run(passive.validate()))

        instance = asyncio.run(passive.save(commit=False))
        self.assertEqual("Alice", instance.name)
        self.assertEqual([], passive_session.added)
        self.assertEqual(0, passive_session.flush_calls)

        active_session = RecordingSession()
        active = ProfileModelForm(data={"name": "Bob"})
        self.assertTrue(asyncio.run(active.validate()))
        instance = asyncio.run(active.save(commit=True, session=active_session))

        self.assertEqual([instance], active_session.added)
        self.assertEqual(1, active_session.flush_calls)

    def test_render_outputs_tailwind_form_protocol_attributes(self) -> None:
        """TailwindForm 渲染必须输出前端 form 组件协议。"""
        html = str(
            asyncio.run(
                AsyncProfileForm().render(
                    action="/profile",
                    target="#profile-form",
                    swap="outer",
                    feedback_target="#profile-feedback",
                )
            )
        )

        self.assertIn('action="/profile"', html)
        self.assertIn('data-om-component="form"', html)
        self.assertIn("data-om-form", html)
        self.assertIn('data-om-target="#profile-form"', html)
        self.assertIn('data-om-swap="outer"', html)
        self.assertIn('data-om-feedback-target="#profile-feedback"', html)
        self.assertNotIn("data-om-form-mode", html)
        self.assertNotIn("data-om-form-replace-target", html)

        json_html = str(asyncio.run(AsyncProfileForm().render(form_mode="json")))
        self.assertIn('data-om-form-mode="json"', json_html)

    def test_render_choice_groups_with_control_specific_markup(self) -> None:
        """Radio 和原生多选不能套用固定高度的普通输入框样式。"""

        class ChoiceForm(TailwindForm):
            priority = RadioField("Priority", choices=[("low", "Low"), ("high", "High")])
            regions = SelectMultipleField("Regions", choices=[("us", "United States"), ("eu", "Europe")])

        html = str(asyncio.run(ChoiceForm().render()))

        self.assertIn('<fieldset data-om-radio-group', html)
        self.assertEqual(2, html.count('class="om-radio"'))
        self.assertIn('class="om-select om-select-multiple"', html)

    def test_render_keeps_message_and_transient_status_separate(self) -> None:
        """服务器 message 与前端瞬时状态必须使用两个独立节点。"""
        form = AsyncProfileForm(data={"name": "blocked"})
        self.assertFalse(asyncio.run(form.validate()))

        html = str(asyncio.run(form.render(action="/profile")))

        self.assertEqual(1, html.count("data-om-form-message"))
        self.assertEqual(1, html.count("data-om-form-status"))
        self.assertIn('data-om-tone="error"', html)
        self.assertIn('role="alert"', html)
        self.assertIn("Blocked user", html)

    def test_render_rejects_unknown_form_mode(self) -> None:
        """form_mode 只能是 json 或 html。"""
        with self.assertRaises(ValueError):
            asyncio.run(AsyncProfileForm().render(action="/profile", form_mode="xml"))

        with self.assertRaises(ValueError):
            asyncio.run(AsyncProfileForm().render(action="/profile", swap="append"))

    def test_table_filter_form_uses_table_filter_protocol(self) -> None:
        """TailwindTableFilterForm 应输出 table-filter-form 协议。"""

        class StatusFilterForm(TailwindTableFilterForm):
            status = SelectField("Status", choices=[("", "All"), ("active", "Active")])

        html = str(asyncio.run(StatusFilterForm().render(table_target="#records-table")))

        self.assertIn('data-om-component="table-filter-form"', html)
        self.assertIn('data-om-table-target="#records-table"', html)
        self.assertIn('name="status"', html)
        self.assertIn('id="id_status"', html)

    def test_layout_actions_override_render_actions(self) -> None:
        """声明式 FormLayout actions 应覆盖 render 参数。"""

        class LayoutForm(TailwindForm):
            name = StringField("Name")
            layout = FormLayout("name", Actions(submit="Apply", cancel_url="/profiles", cancel_label="Reset"))

        html = str(asyncio.run(LayoutForm().render(action="/profiles/new", submit_label="Save", cancel_url="/ignored")))

        self.assertIn(">Apply</button>", html)
        self.assertIn('href="/profiles"', html)
        self.assertIn(">Reset</a>", html)
        self.assertNotIn("/ignored", html)

    def test_sanic_form_data_normalizes_single_and_multi_values(self) -> None:
        """SanicFormData 应规范普通 mapping 和多值 mapping。"""

        class MultiDict(dict):
            def getlist(self, key: str) -> list[str]:
                value = self[key]
                return value if isinstance(value, list) else [value]

        formdata = SanicFormData(MultiDict({"name": ["alex"], "tag": ["a", "b"]}))

        self.assertEqual(formdata.getlist("name"), ["alex"])
        self.assertEqual(formdata.getlist("tag"), ["a", "b"])
        self.assertEqual(formdata.to_dict(), {"name": "alex", "tag": ["a", "b"]})

    def test_component_package_exports_tailwind_forms_without_bootstrap_aliases(self) -> None:
        """正式组件入口暴露 Tailwind 表单，不污染 Web 基础类型入口。"""
        import oldman.web as ui
        from oldman.web.components import forms

        self.assertIs(forms.TailwindForm, TailwindForm)
        self.assertIs(forms.TailwindTableFilterForm, TailwindTableFilterForm)
        self.assertIs(forms.OldmanForm, OldmanForm)
        self.assertFalse(hasattr(ui, "TailwindForm"))
        self.assertFalse(hasattr(ui, "BootstrapForm"))
        self.assertFalse(hasattr(ui, "BootstrapTableFilterForm"))

    def test_model_form_does_not_gain_unreviewed_numeric_mapping(self) -> None:
        """目录迁移不得顺手增加迁移前不存在的 SQLAlchemy 字段映射。"""
        column = Column("amount", Numeric(10, 2))

        with self.assertRaisesRegex(ValueError, "Unsupported model field type"):
            model_field_for_column(column)

    def test_remote_widgets_emit_signed_source_protocol(self) -> None:
        class WidgetForm(TailwindForm):
            channel = StringField("Channel")

        form = WidgetForm()
        form.select_secret_key = "component-test-secret"
        for widget, component in (
            (AjaxSelectWidget(provider="channels", endpoint="/selects/channels"), "select"),
            (AjaxAutocompleteWidget(provider="channels", endpoint="/selects/channels"), "autocomplete"),
        ):
            with self.subTest(component=component):
                attrs = widget.bind_attrs(form.channel, form)
                context = verify_select_context(attrs["data-om-select-bind"], secret_key=form.select_secret_key)
                self.assertEqual(attrs["data-om-component"], component)
                self.assertEqual(attrs["data-om-select-src"], "/selects/channels")
                self.assertEqual(context.provider, "channels")
                self.assertEqual(context.field_name, "channel")

    def test_datetime_widget_keeps_explicit_frontend_contract(self) -> None:
        class WidgetForm(TailwindForm):
            happened_at = StringField("Happened at")

        form = WidgetForm()
        attrs = DateTimePickerWidget(date_format="Y-m-d H:i").bind_attrs(form.happened_at, form)

        self.assertEqual(attrs["data-om-component"], "date-time-picker")
        self.assertEqual(attrs["data-provider"], "flatpickr")
        self.assertEqual(attrs["data-date-format"], "Y-m-d H:i")
        self.assertTrue(attrs["data-enable-time"])

    def test_slug_field_normalizes_submitted_and_generated_values(self) -> None:
        """SlugField 只在空值时读取源字段，并支持 Unicode slug。"""

        class SlugForm(TailwindForm):
            title = StringField("Title")
            slug = SlugField("Slug", source_field="title", validators=[InputRequired()])

        generated = SlugForm(data={"title": "Hello, Oldman!", "slug": ""})
        manual = SlugForm(data={"title": "Ignored", "slug": "Custom Path"})

        self.assertTrue(asyncio.run(generated.validate()))
        self.assertEqual("hello-oldman", generated.cleaned_data["slug"])
        self.assertTrue(asyncio.run(manual.validate()))
        self.assertEqual("custom-path", manual.cleaned_data["slug"])

        html = str(asyncio.run(SlugForm(prefix="profile").render()))
        self.assertIn('data-om-component="slug-input"', html)
        self.assertIn('data-om-slug-source="#id_profile-title"', html)

        class UnicodeSlugForm(TailwindForm):
            slug = SlugField("Slug", allow_unicode=True)

        unicode_form = UnicodeSlugForm(data={"slug": "中文 标题"})
        self.assertTrue(asyncio.run(unicode_form.validate()))
        self.assertEqual("中文-标题", unicode_form.cleaned_data["slug"])
        unicode_html = str(asyncio.run(UnicodeSlugForm().render()))
        self.assertIn('data-om-slug-allow-unicode="true"', unicode_html)

    def test_tags_field_normalizes_delimited_text(self) -> None:
        """TagsField 对初始值和提交值使用同一套稳定字符串规则。"""

        class TagsForm(TailwindForm):
            tags = TagsField("Tags", delimiter="|")

        initial = TagsForm(data={"tags": " Python | sanic || Python | Redis "})
        submitted = TagsForm(formdata=SanicFormData({"tags": " 中文标签 | internal space | 中文标签 "}))
        case_sensitive = TagsForm(formdata=SanicFormData({"tags": "Python|python"}))

        self.assertEqual("Python|sanic|Redis", initial.tags.data)
        self.assertEqual("中文标签|internal space", submitted.tags.data)
        self.assertEqual("Python|python", case_sensitive.tags.data)

    def test_tags_field_rejects_invalid_delimiters(self) -> None:
        """TagsField 只接受一个字符的字符串分隔符。"""
        for delimiter, error in (("", ValueError), ("::", ValueError), (None, TypeError)):
            with self.subTest(delimiter=delimiter), self.assertRaises(error):

                class InvalidTagsForm(TailwindForm):
                    tags = TagsField("Tags", delimiter=delimiter)  # type: ignore[arg-type]

                InvalidTagsForm()

    def test_tags_field_renders_component_contract(self) -> None:
        """TagsField 保留原生输入属性并声明前端渐进增强协议。"""

        class TagsForm(TailwindForm):
            tags = TagsField(
                "Tags",
                delimiter="|",
                default="Python|Sanic",
                render_kw={"placeholder": "Add tags", "disabled": True},
            )

        html = str(asyncio.run(TagsForm().render()))

        self.assertIn('data-om-component="tags-input"', html)
        self.assertIn('data-om-tags-delimiter="|"', html)
        self.assertIn('name="tags"', html)
        self.assertIn('id="id_tags"', html)
        self.assertIn('value="Python|Sanic"', html)
        self.assertIn('placeholder="Add tags"', html)
        self.assertIn("disabled", html)

    def test_tags_select_widget_keeps_multiple_values(self) -> None:
        """本地 Select 标签展示不改变多值字段的数据类型。"""

        class TagsSelectForm(TailwindForm):
            categories = SelectMultipleField(
                "Categories",
                choices=(("api", "API"), ("web", "Web")),
                widget=TagsSelectWidget(),
            )

        form = TagsSelectForm(formdata=SanicFormData({"categories": ["api", "web"]}))
        html = str(asyncio.run(form.render_field("categories")))

        self.assertEqual(["api", "web"], form.categories.data)
        self.assertIn("<select", html)
        self.assertIn("multiple", html)
        self.assertIn('data-om-component="select"', html)
        self.assertIn("data-choices", html)
        self.assertIn("data-choices-removeItem", html)
        self.assertIn("data-choices-sorting-false", html)

    def test_ajax_select_multiple_tags_enable_existing_select_ui(self) -> None:
        """远程 Select 只在 tags=True 时启用现有标签化 Choices 展示。"""

        class RemoteTagsForm(TailwindForm):
            tag_ids = AjaxSelectMultipleField(provider="tags", endpoint="/select/tags", tags=True)
            plain_ids = AjaxSelectMultipleField(provider="tags", endpoint="/select/tags")

        form = RemoteTagsForm()
        form.select_secret_key = "component-test-secret"
        tags_html = str(asyncio.run(form.render_field("tag_ids")))
        plain_html = str(asyncio.run(form.render_field("plain_ids")))

        self.assertIn("multiple", tags_html)
        self.assertIn('data-om-select-src="/select/tags"', tags_html)
        self.assertIn("data-om-select-bind", tags_html)
        self.assertIn("data-choices", tags_html)
        self.assertIn("data-choices-removeItem", tags_html)
        self.assertIn("data-choices-sorting-false", tags_html)
        self.assertNotIn("data-choices", plain_html)

    def test_input_spinner_widget_renders_native_number_contract(self) -> None:
        """InputSpinnerWidget 保留原生 number 字段及提交属性。"""

        class SpinnerForm(TailwindForm):
            quantity = IntegerField(
                "Quantity",
                default=2,
                widget=InputSpinnerWidget(),
                render_kw={"min": 1, "max": 5, "step": 2},
            )

        html = str(asyncio.run(SpinnerForm().render()))

        self.assertIn('data-om-component="input-spinner"', html)
        self.assertIn('name="quantity"', html)
        self.assertIn('id="id_quantity"', html)
        self.assertIn('type="number"', html)
        self.assertIn('min="1"', html)
        self.assertIn('max="5"', html)
        self.assertIn('step="2"', html)

    def test_color_picker_field_validates_and_keeps_native_fallback(self) -> None:
        """ColorPickerField 接受 RGB/RGBA HEX，并保留无脚本可提交的 color input。"""

        class ColorForm(TailwindForm):
            accent = ColorPickerField("Accent", default="#0ea5e9cc")

        form = ColorForm(data={"accent": "#22C55E80"})
        self.assertTrue(asyncio.run(form.validate()))
        self.assertEqual("#22c55e80", form.cleaned_data["accent"])

        html = str(asyncio.run(ColorForm().render()))
        self.assertIn('data-om-component="color-picker"', html)
        self.assertIn('type="color"', html)
        self.assertIn('name="accent"', html)
        self.assertIn('value="#0ea5e9"', html)
        self.assertIn('data-om-color-picker-value', html)

        invalid = ColorForm(data={"accent": "red"})
        self.assertFalse(asyncio.run(invalid.validate()))
        self.assertEqual(1, len(invalid.accent.errors))

    def test_rich_text_field_sanitizes_and_renders_native_textarea(self) -> None:
        """RichTextField 按需清洗 HTML，并保留无脚本 textarea。"""

        class ArticleForm(TailwindForm):
            body = RichTextField(
                "Body",
                sanitizer=lambda value: value.replace("<script>bad()</script>", ""),
            )

        form = ArticleForm(data={"body": "<p>Safe</p><script>bad()</script>"})
        self.assertTrue(asyncio.run(form.validate()))
        self.assertEqual("<p>Safe</p>", form.cleaned_data["body"])

        html = str(asyncio.run(ArticleForm(data={"body": "<p>Hello</p>"}).render()))
        self.assertIn('data-om-component="rich-text-editor"', html)
        self.assertIn('data-om-rich-text-value', html)
        self.assertIn('name="body"', html)
        self.assertIn('&lt;p&gt;Hello&lt;/p&gt;', html)
        self.assertIn('data-om-rich-text-editor', html)


if __name__ == "__main__":
    unittest.main()
