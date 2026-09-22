"""Oldman 后端 Select/Autocomplete 新协议测试。"""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from markupsafe import Markup
from wtforms import StringField
from wtforms.validators import Optional

from oldman.db import DatabaseManager
from oldman.db import db_manager as default_db_manager
from oldman.web.api.enums import ApiErrorCode
from oldman.web.components.forms import (
    AjaxAutocompleteField,
    AjaxAutocompleteWidget,
    AjaxSelectField,
    AjaxSelectMultipleField,
    AjaxSelectWidget,
    SanicFormData,
    TailwindForm,
)
from oldman.web.components.selects import (
    DataSelectProvider,
    ModelSelectProvider,
    SelectBindError,
    SelectChoice,
    SelectContext,
    SelectProviderConfigError,
    SelectRegistry,
    SelectResult,
    sign_select_context,
    verify_select_context,
)
from oldman.web.components.selects.views import select_provider_payload


class SelectChoiceContractTest(unittest.TestCase):
    """验证后端候选项到前端 option 的转换协议。"""

    def test_choice_to_option_escapes_plain_html_and_keeps_markup(self) -> None:
        """普通 html 字符串必须转义，Markup 可以作为安全 HTML 透传。"""
        escaped = SelectChoice(id=1, text="BBC", html="<b>BBC</b>", selected=True, disabled=True, data={"kind": "tv"}).to_option(label_mode="html")
        safe = SelectChoice(id=2, text="CNN", html=Markup("<span>CNN</span>")).to_option(label_mode="html")

        self.assertEqual(escaped["id"], "1")
        self.assertEqual(escaped["html"], "&lt;b&gt;BBC&lt;/b&gt;")
        self.assertTrue(escaped["selected"])
        self.assertTrue(escaped["disabled"])
        self.assertEqual(escaped["data"], {"kind": "tv"})
        self.assertEqual(safe["html"], "<span>CNN</span>")

    def test_text_label_mode_never_serializes_candidate_html(self) -> None:
        """默认文本模式不应把 provider 的 HTML 发送给浏览器。"""
        payload = SelectChoice(id=1, text="BBC", html=Markup("<strong>BBC</strong>")).to_option(label_mode="text")

        self.assertNotIn("html", payload)

    def test_select_result_outputs_formal_protocol_without_select2_pagination(self) -> None:
        """SelectResult 只输出 results 和顶层 more，不保留 Select2 pagination.more。"""
        payload = SelectResult(results=[SelectChoice(id=1, text="BBC")], more=True).to_json(label_mode="text")

        self.assertEqual(payload, {"results": [{"id": "1", "text": "BBC"}], "more": True})


class RemoteSelectWidgetContractTest(unittest.TestCase):
    """验证 Form 对远程候选显示模式的公开配置。"""

    def test_widgets_sign_and_emit_html_label_mode(self) -> None:
        """增强 Select 与 Autocomplete 应把 HTML 显示模式写入签名和 DOM。"""

        class WidgetForm(TailwindForm):
            channel = StringField("Channel")

        form = WidgetForm()
        form.select_secret_key = "select-secret"

        for widget in (
            AjaxSelectWidget(provider="channels", endpoint="/choices", enhance_choices=True, label_mode="html"),
            AjaxAutocompleteWidget(provider="channels", endpoint="/choices", label_mode="html"),
        ):
            with self.subTest(widget=type(widget).__name__):
                attrs = widget.bind_attrs(form.channel, form)
                context = verify_select_context(attrs["data-om-select-bind"], secret_key=form.select_secret_key)
                self.assertEqual(context.label_mode, "html")
                self.assertEqual(attrs["data-om-select-label-mode"], "html")

    def test_html_select_requires_choices_enhancement(self) -> None:
        """原生 select 不支持候选 HTML，配置时应立即报错。"""
        with self.assertRaisesRegex(ValueError, "enhance_choices"):
            AjaxSelectWidget(provider="channels", endpoint="/choices", label_mode="html")

    def test_ajax_select_field_forwards_label_mode(self) -> None:
        """便捷字段不能吞掉公开的 label_mode 配置。"""

        class SelectForm(TailwindForm):
            channel = AjaxSelectField(provider="channels", endpoint="/choices", enhance_choices=True, label_mode="html")

        self.assertEqual(cast(AjaxSelectWidget, SelectForm().channel.widget).label_mode, "html")


class AjaxInitialChoiceTest(unittest.TestCase):
    """远程字段的编辑页首屏回显与空提交处理。"""

    class EditForm(TailwindForm):
        """一个单选、一个多选、一个 autocomplete，都指向同一个 provider。"""

        channel = AjaxSelectField(provider="channels", endpoint="/choices", validators=[Optional()])
        channels = AjaxSelectMultipleField(provider="channels", endpoint="/choices", validators=[Optional()])
        channel_lookup = AjaxAutocompleteField(provider="channels", endpoint="/choices", validators=[Optional()])

    def test_initial_choice_seeds_the_only_option_of_an_empty_remote_field(self) -> None:
        form = self.EditForm()
        form.channel.initial_choice(7, "CCTV 1")
        form.channels.initial_choices([(7, "CCTV 1"), (9, "CCTV 9")])
        form.channel_lookup.initial_choice(7, "CCTV 1")

        self.assertEqual([(7, "CCTV 1")], form.channel.choices)
        self.assertEqual(7, form.channel.data)
        self.assertEqual([(7, "CCTV 1"), (9, "CCTV 9")], form.channels.choices)
        self.assertEqual([7, 9], form.channels.data)
        self.assertEqual("7", form.channel_lookup.data)
        self.assertEqual("CCTV 1", (form.channel_lookup.render_kw or {})["value"])

    def test_a_blank_multiple_submission_is_an_empty_list(self) -> None:
        """提交空字符串和完全不提交都表示"一个都没选"，调用方不该遇到两种结果。"""
        blank = self.EditForm(formdata=SanicFormData({"channels": [""]}))
        absent = self.EditForm(formdata=SanicFormData({"other": ["x"]}))

        self.assertEqual([], blank.channels.data)
        self.assertEqual([], absent.channels.data)
        self.assertTrue(blank.validate())

    def test_a_cleared_multiple_select_stays_cleared(self) -> None:
        """多选一个都不选时浏览器不提交这个 key，回显入口不能把旧值写回去。"""
        cleared = self.EditForm(formdata=SanicFormData({"other": ["x"]}))
        cleared.channels.initial_choices([(7, "CCTV 1"), (9, "CCTV 9")])
        cleared.channel.initial_choice(7, "CCTV 1")
        cleared.channel_lookup.initial_choice(7, "CCTV 1")

        self.assertEqual([], cleared.channels.data)
        self.assertEqual([], cleared.channels.choices)
        self.assertIsNone(cleared.channel.data)
        self.assertIsNone(cleared.channel_lookup.data)

    def test_initial_choice_runs_the_value_through_coerce(self) -> None:
        """回显入口不能把值缩窄成字符串：int() 支持的对象照样能用。"""

        class IntegerLike:
            def __int__(self) -> int:
                return 17

        form = self.EditForm()
        form.channel.initial_choice(IntegerLike(), "CCTV 17")

        self.assertEqual([(17, "CCTV 17")], form.channel.choices)
        self.assertEqual(17, form.channel.data)

    def test_initial_choice_ignores_blank_values_and_submitted_fields(self) -> None:
        empty = self.EditForm()
        empty.channel.initial_choice(None, "CCTV 1")
        empty.channels.initial_choices([("", "CCTV 1")])
        empty.channel_lookup.initial_choice("", "CCTV 1")

        self.assertEqual([], empty.channel.choices)
        self.assertIsNone(empty.channel.data)
        self.assertEqual([], empty.channels.choices)
        self.assertIsNone(empty.channel_lookup.data)

        submitted = self.EditForm(formdata=SanicFormData({"channel": ["9"], "channel_lookup": ["9"]}))
        submitted.channel.initial_choice(7, "CCTV 1")
        submitted.channel_lookup.initial_choice(7, "CCTV 1")

        self.assertEqual(9, submitted.channel.data)
        self.assertEqual([], submitted.channel.choices)
        self.assertEqual("9", submitted.channel_lookup.data)

    def test_clearing_an_optional_remote_select_submits_none_instead_of_failing(self) -> None:
        form = self.EditForm(formdata=SanicFormData({"channel": [""]}))

        self.assertIsNone(form.channel.data)
        self.assertEqual((), tuple(form.channel.errors))


class SelectRegistryContractTest(unittest.TestCase):
    """验证 provider 静态注册表边界。"""

    def test_registry_rejects_duplicate_provider_names(self) -> None:
        """Provider 名称冲突必须在注册时失败。"""
        registry = SelectRegistry()

        @registry.register("channels")
        class ChannelsProvider(DataSelectProvider):
            """测试 provider。"""

        with self.assertRaises(ValueError):

            @registry.register("channels")
            class OtherChannelsProvider(DataSelectProvider):
                """重复名称测试 provider。"""

        self.assertIs(registry.get("channels"), ChannelsProvider)


class SelectSigningContractTest(unittest.TestCase):
    """验证远程选择器签名绑定上下文。"""

    def test_signed_context_round_trips_and_rejects_wrong_secret(self) -> None:
        """签名上下文应该可恢复，并拒绝错误密钥。"""
        context = SelectContext(
            provider="channels",
            field_name="channel_id",
            multiple=False,
            dependent_fields=("country_id",),
            page_size=20,
            value_field="id",
            label_mode="text",
        )

        bind = sign_select_context(context, secret_key="secret-a")

        self.assertEqual(verify_select_context(bind, secret_key="secret-a"), context)
        with self.assertRaises(SelectBindError):
            verify_select_context(bind, secret_key="secret-b")

    def test_signed_context_rejects_unknown_label_mode(self) -> None:
        """签名正确也不能绕过候选显示模式白名单。"""
        context = SelectContext(
            provider="channels",
            field_name="channel_id",
            multiple=False,
            dependent_fields=(),
            page_size=20,
            value_field="id",
            label_mode=cast(Any, "script"),
        )

        with self.assertRaises(SelectBindError):
            verify_select_context(sign_select_context(context, secret_key="secret"), secret_key="secret")


@dataclass(frozen=True)
class Country:
    """测试用结构化候选对象。"""

    code: str
    name: str


class CountryProvider(DataSelectProvider):
    """测试用结构化数据 provider。"""

    page_size = 2

    async def get_choices(self, request, context):
        """返回结构化候选数据。"""
        return [
            ("us", "United States"),
            ("uk", "United Kingdom"),
            Country("cn", "China"),
        ]

    def get_option(self, obj) -> SelectChoice:
        """把 dataclass 或默认 tuple 转换为 SelectChoice。"""
        if isinstance(obj, Country):
            return SelectChoice(id=obj.code, text=obj.name)
        return super().get_option(obj)


class DependentCountryProvider(CountryProvider):
    """记录依赖字段的结构化数据 provider。"""

    def __init__(self) -> None:
        """初始化依赖字段记录。"""
        super().__init__()
        self.last_depends: dict[str, str] = {}

    async def filter_queryset(self, request, context, choices, term, depends):
        """记录通过白名单校验后的依赖字段。"""
        self.last_depends = depends
        return await super().filter_queryset(request, context, choices, term, depends)


class BadTupleProvider(DataSelectProvider):
    """测试 tuple 格式错误的 provider。"""

    async def get_choices(self, request, context):
        """返回非法三元 tuple。"""
        return [("a", "A", "extra")]


class DeniedCountryProvider(CountryProvider):
    """测试权限拒绝的结构化数据 provider。"""

    async def check_auth(self, request, context) -> bool:
        """拒绝当前请求。"""
        return False


class DataSelectProviderContractTest(unittest.TestCase):
    """验证结构化数据 provider 的搜索、分页和初始值协议。"""

    def test_data_provider_supports_search_pagination_and_more(self) -> None:
        """结构化 provider 应该支持搜索、分页和顶层 more。"""
        context = select_context(page_size=1)
        payload = asyncio.run(CountryProvider().handle_request(make_request(args={"q": "United", "page_size": "1"}), context=context))

        self.assertEqual(payload, {"results": [{"id": "us", "text": "United States"}], "more": True})

    def test_data_provider_initial_values_keep_input_order(self) -> None:
        """初始值回显应该保持 values 输入顺序，并固定 more=false。"""
        context = select_context()
        payload = asyncio.run(CountryProvider().handle_request(make_request(args={"values": ["cn", "us"]}), context=context))

        self.assertEqual([item["id"] for item in payload["results"]], ["cn", "us"])
        self.assertFalse(payload["more"])

    def test_data_provider_rejects_non_pair_tuple_choices(self) -> None:
        """默认 tuple 只支持 (value, label)，复杂格式必须重写 get_option。"""
        with self.assertRaises(SelectProviderConfigError):
            asyncio.run(BadTupleProvider().handle_request(make_request(), context=select_context()))

    def test_data_provider_rejects_invalid_page_arguments(self) -> None:
        """page 和 page_size 非法时应该由 provider 转成统一错误 payload。"""
        for args in ({"page": "bad"}, {"page": "0"}, {"page_size": "bad"}, {"page_size": "0"}, {"page_size": "3"}):
            with self.subTest(args=args):
                payload = asyncio.run(CountryProvider().handle_request(make_request(args=args), context=select_context(page_size=2)))

                self.assertEqual(payload["error_code"], ApiErrorCode.INVALID_REQUEST)
                self.assertNotIn("errors", payload)
                self.assertIn("request", payload["data"]["errors"])

    def test_data_provider_only_accepts_signed_dependent_fields(self) -> None:
        """依赖字段只能使用签名上下文声明的白名单字段。"""
        provider = DependentCountryProvider()
        context = select_context(dependent_fields=("country_id",))

        payload = asyncio.run(provider.handle_request(make_request(args={"depends[country_id]": "uk"}), context=context))

        self.assertEqual(provider.last_depends, {"country_id": "uk"})
        self.assertEqual(payload["results"][0]["id"], "us")

        payload = asyncio.run(provider.handle_request(make_request(args={"depends[tenant_id]": "other"}), context=context))

        self.assertEqual(payload["error_code"], ApiErrorCode.INVALID_REQUEST)
        self.assertNotIn("errors", payload)
        self.assertIn("request", payload["data"]["errors"])

    def test_data_provider_permission_denied_returns_api_error_payload(self) -> None:
        """权限拒绝应该由 provider.handle_request 转成统一错误 payload。"""
        payload = asyncio.run(DeniedCountryProvider().handle_request(make_request(), context=select_context()))

        self.assertEqual(payload["error_code"], ApiErrorCode.PERMISSION_DENIED)
        self.assertNotIn("errors", payload)
        self.assertIn("permission", payload["data"]["errors"])


class FakeReadSessionContext:
    """记录测试读会话上下文的进入和退出次数。"""

    def __init__(self, session: object) -> None:
        """保存要返回给 provider 的测试 session。"""
        self.session = session
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self) -> object:
        """进入读会话并返回固定 session。"""
        self.enter_count += 1
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        """退出读会话并记录退出次数。"""
        self.exit_count += 1


class FakeDbManager:
    """为 ModelSelectProvider 生命周期测试提供可观察的 db_manager。"""

    def __init__(self) -> None:
        """初始化固定 session 和上下文对象。"""
        self.session = object()
        self.context = FakeReadSessionContext(self.session)
        self.read_session_calls = 0

    def get_read_session(self) -> FakeReadSessionContext:
        """返回同一个读会话上下文并记录调用次数。"""
        self.read_session_calls += 1
        return self.context


class SessionLifecycleModelProvider(ModelSelectProvider):
    """验证数据库型 provider 两条请求分支共享同一 session。"""

    model = object

    def __init__(self) -> None:
        """初始化生命周期记录。"""
        super().__init__()
        self.lifecycle_sessions: list[tuple[str, object | None]] = []

    def record_session(self, hook_name: str) -> None:
        """记录当前钩子看到的 db_session。"""
        self.lifecycle_sessions.append((hook_name, self.db_session))

    async def check_auth(self, request, context) -> bool:
        """记录权限检查阶段的 session。"""
        self.record_session("check_auth")
        return True

    async def search(self, request, context, *, term: str, depends: dict[str, str], page: int, page_size: int) -> SelectResult:
        """记录搜索分页分支的 session。"""
        self.record_session("search")
        return SelectResult(results=[SelectChoice(id="search", text="Search result")], more=False)

    async def get_initial(self, request, context, values: list[str], depends: dict[str, str]) -> list[SelectChoice]:
        """记录初始值回显分支的 session。"""
        self.record_session("get_initial")
        return [SelectChoice(id=value, text=f"Initial {value}") for value in values]


class ModelSelectProviderSessionLifecycleTest(unittest.TestCase):
    """验证 ModelSelectProvider 的数据库 session 生命周期。"""

    def test_model_provider_defaults_to_framework_database_manager(self) -> None:
        """数据库型 provider 默认复用框架进程级 manager。"""
        self.assertIs(ModelSelectProvider.database_manager, default_db_manager)

    def test_search_branch_uses_one_read_session_for_auth_and_search(self) -> None:
        """搜索分页请求应该只打开一个读 session，并贯穿权限检查和搜索。"""
        manager = FakeDbManager()

        class CustomDatabaseProvider(SessionLifecycleModelProvider):
            """显式绑定测试数据库 manager。"""

            database_manager = cast(DatabaseManager, manager)

        provider = CustomDatabaseProvider()
        payload = asyncio.run(provider.handle_request(make_request(args={"q": "abc"}), context=select_context()))

        self.assertEqual(payload["results"][0]["id"], "search")
        self.assertEqual(manager.read_session_calls, 1)
        self.assertEqual(manager.context.enter_count, 1)
        self.assertEqual(manager.context.exit_count, 1)
        self.assertIsNone(provider.db_session)
        self.assertEqual([name for name, _ in provider.lifecycle_sessions], ["check_auth", "search"])
        self.assertTrue(all(session is manager.session for _, session in provider.lifecycle_sessions))

    def test_initial_branch_uses_one_read_session_for_auth_and_initial_lookup(self) -> None:
        """初始值回显请求应该只打开一个读 session，并贯穿权限检查和回显。"""
        manager = FakeDbManager()

        class CustomDatabaseProvider(SessionLifecycleModelProvider):
            """显式绑定测试数据库 manager。"""

            database_manager = cast(DatabaseManager, manager)

        provider = CustomDatabaseProvider()
        payload = asyncio.run(provider.handle_request(make_request(args={"values": ["b", "a"]}), context=select_context()))

        self.assertEqual([item["id"] for item in payload["results"]], ["b", "a"])
        self.assertFalse(payload["more"])
        self.assertEqual(manager.read_session_calls, 1)
        self.assertEqual(manager.context.enter_count, 1)
        self.assertEqual(manager.context.exit_count, 1)
        self.assertIsNone(provider.db_session)
        self.assertEqual([name for name, _ in provider.lifecycle_sessions], ["check_auth", "get_initial"])
        self.assertTrue(all(session is manager.session for _, session in provider.lifecycle_sessions))

    def test_data_provider_does_not_open_database_session(self) -> None:
        """结构化数据 provider 不应该打开数据库 session。"""
        provider = CountryProvider()

        payload = asyncio.run(provider.handle_request(make_request(args={"q": "China"}), context=select_context()))

        self.assertEqual(payload["results"][0]["id"], "cn")
        self.assertFalse(hasattr(provider, "database_manager"))


class SelectProviderEndpointContractTest(unittest.TestCase):
    """验证中心 provider endpoint 的分发和错误边界。"""

    def test_endpoint_dispatches_registered_provider_with_signed_bind(self) -> None:
        """中心 endpoint 应该验证 bind 后分发到注册 provider。"""
        registry = SelectRegistry()
        registry.register("countries")(CountryProvider)
        context = select_context()
        bind = sign_select_context(context, secret_key="secret")

        payload, status = asyncio.run(
            select_provider_payload(make_request(args={"bind": bind, "q": "China"}), "countries", registry=registry, secret_key="secret")
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"results": [{"id": "cn", "text": "China"}], "more": False})

    def test_endpoint_returns_api_error_for_missing_provider(self) -> None:
        """provider 不存在时必须返回统一 404 schema。"""
        registry = SelectRegistry()
        valid_bind = sign_select_context(select_context(), secret_key="secret")

        missing_payload, missing_status = asyncio.run(
            select_provider_payload(make_request(args={"bind": valid_bind}), "missing", registry=registry, secret_key="secret")
        )

        self.assertEqual(missing_status, 404)
        self.assertEqual(missing_payload["error_code"], ApiErrorCode.NOT_FOUND)

    def test_endpoint_returns_api_error_for_invalid_bind(self) -> None:
        """provider 存在但 bind 无效时必须返回统一 400 schema。"""
        registry = SelectRegistry()
        registry.register("countries")(CountryProvider)

        payload, status = asyncio.run(
            select_provider_payload(make_request(args={"bind": "bad"}), "countries", registry=registry, secret_key="secret")
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error_code"], ApiErrorCode.INVALID_REQUEST)
        self.assertNotIn("errors", payload)
        self.assertIn("bind", payload["data"]["errors"])

    def test_endpoint_rejects_bind_provider_mismatch(self) -> None:
        """bind 中的 provider 必须和路径 provider 一致。"""
        registry = SelectRegistry()
        registry.register("countries")(CountryProvider)
        registry.register("cities")(CountryProvider)
        bind = sign_select_context(select_context(), secret_key="secret")

        payload, status = asyncio.run(select_provider_payload(make_request(args={"bind": bind}), "cities", registry=registry, secret_key="secret"))

        self.assertEqual(status, 400)
        self.assertEqual(payload["error_code"], ApiErrorCode.INVALID_REQUEST)

    def test_endpoint_returns_enum_api_error_for_permission_denied(self) -> None:
        """权限拒绝应该返回 DefaultApiResponse 枚举错误码。"""

        class DeniedProvider(CountryProvider):
            """测试权限拒绝 provider。"""

            async def check_auth(self, request, context) -> bool:
                """拒绝当前请求。"""
                return False

        registry = SelectRegistry()
        registry.register("countries")(DeniedProvider)
        bind = sign_select_context(select_context(), secret_key="secret")

        payload, status = asyncio.run(select_provider_payload(make_request(args={"bind": bind}), "countries", registry=registry, secret_key="secret"))

        self.assertEqual(status, 403)
        self.assertEqual(payload["error_code"], ApiErrorCode.PERMISSION_DENIED)
        self.assertNotIn("errors", payload)
        self.assertIn("permission", payload["data"]["errors"])

    def test_endpoint_returns_api_error_for_invalid_provider_request(self) -> None:
        """provider 参数错误应该转换为统一 400 schema。"""
        registry = SelectRegistry()
        registry.register("countries")(CountryProvider)
        bind = sign_select_context(select_context(page_size=2), secret_key="secret")

        payload, status = asyncio.run(
            select_provider_payload(make_request(args={"bind": bind, "page_size": "3"}), "countries", registry=registry, secret_key="secret")
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error_code"], ApiErrorCode.INVALID_REQUEST)
        self.assertNotIn("errors", payload)
        self.assertIn("request", payload["data"]["errors"])


def select_context(*, page_size: int = 20, dependent_fields: tuple[str, ...] = ()) -> SelectContext:
    """构造测试用 SelectContext。"""
    return SelectContext(
        provider="countries",
        field_name="country",
        multiple=False,
        dependent_fields=dependent_fields,
        page_size=page_size,
        value_field="id",
        label_mode="text",
    )


def make_request(*, args: Mapping[str, object] | None = None):
    """构造 provider 单元测试需要的最小 request 对象。"""

    class Args(dict):
        """模拟 Sanic request.args 的 get/getlist 行为。"""

        def get(self, key, default=None):
            """读取单值参数。"""
            value = super().get(key, default)
            return value[0] if isinstance(value, list) and value else value

        def getlist(self, key):
            """读取多值参数。"""
            value = super().get(key, [])
            if value is None:
                return []
            return value if isinstance(value, list) else [value]

    return type("RequestStub", (), {"args": Args(args or {})})()


if __name__ == "__main__":
    unittest.main()


class RemoteSelectAllowedValuesTest(unittest.TestCase):
    """A remote select validates its submitted value against a source the form declares.

    These fields render no local choices, so WTForms has nothing to check and choice
    validation is off: any integer the browser sends is accepted. The source is declared
    on the field rather than taken from the provider, because what a user may *see* and
    what a user may *submit* are different sets - a form that reassigns a record to any
    user while the dropdown shows only the twenty most recent is an ordinary case that
    reusing the display filter would break.
    """

    @staticmethod
    def _request(user_id: int = 7) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(
            ctx=SimpleNamespace(user_id=user_id, session={}),
            app=None,
            args={},
            form={},
            json=None,
            headers={},
            host="example.test",
        )

    def _validate(self, field, submitted: str, *, user_id: int = 7) -> tuple[bool, list[str]]:
        class RemoteForm(TailwindForm):
            value = field

        form = RemoteForm(formdata=SanicFormData({"value": [submitted]}), request=self._request(user_id))
        valid = asyncio.run(form.validate())
        return valid, [str(message) for message in form.errors.get("value", [])]

    def test_without_a_declared_source_nothing_is_validated(self) -> None:
        """The default must stay exactly what it is today: no check, and no query."""
        called: list[Any] = []

        async def never(request: Any, values: list[str]) -> list[str]:
            called.append(values)
            return []

        del never  # declared only to show it is not wired in by default

        valid, _ = self._validate(AjaxSelectField("Doc", provider="p", endpoint="/s"), "999999")
        self.assertTrue(valid)
        self.assertEqual([], called)

    def test_a_declared_source_decides_what_may_be_submitted(self) -> None:
        async def owned(request: Any, values: list[str]) -> list[str]:
            allowed = {"1", "2"} if request.ctx.user_id == 7 else set()
            return [value for value in values if value in allowed]

        field = lambda: AjaxSelectField("Doc", provider="p", endpoint="/s", allowed_values=owned)  # noqa: E731
        self.assertTrue(self._validate(field(), "1")[0])

        refused, errors = self._validate(field(), "999999")
        self.assertFalse(refused)
        self.assertIn("Not a valid choice.", errors)

        other_user, _ = self._validate(field(), "1", user_id=99)
        self.assertFalse(other_user, "the resolver sees the request, so it can scope by user")

    def test_the_source_is_not_limited_to_a_database(self) -> None:
        """Structured data answers the same hook; the resolver is a plain async callable."""

        async def known_countries(request: Any, values: list[str]) -> list[str]:
            return [value for value in values if value in {"CN", "SG"}]

        field = lambda: AjaxAutocompleteField(  # noqa: E731
            "Country", provider="p", endpoint="/s", allowed_values=known_countries
        )
        self.assertTrue(self._validate(field(), "CN")[0])
        self.assertFalse(self._validate(field(), "XX")[0])

    def test_tags_mode_still_accepts_something_that_does_not_exist_yet(self) -> None:
        async def nothing(request: Any, values: list[str]) -> list[str]:
            return []

        valid, _ = self._validate(
            AjaxSelectMultipleField("Doc", provider="p", endpoint="/s", tags=True, allowed_values=nothing),
            "12345",
        )
        self.assertTrue(valid)

    def test_every_variant_validates_including_the_list_backed_one(self) -> None:
        """The multiple variant stores a list; an emptiness test written for a scalar raised."""

        async def only_one(request: Any, values: list[str]) -> list[str]:
            return [value for value in values if value == "1"]

        for field_cls in (AjaxSelectField, AjaxSelectMultipleField, AjaxAutocompleteField):
            with self.subTest(field=field_cls.__name__):
                allowed, _ = self._validate(field_cls("V", provider="p", endpoint="/s", allowed_values=only_one), "1")
                self.assertTrue(allowed)
                refused, _ = self._validate(field_cls("V", provider="p", endpoint="/s", allowed_values=only_one), "999")
                self.assertFalse(refused)

    def test_the_source_is_taken_by_the_mixin_not_by_each_variant(self) -> None:
        """One owner for the shared behavior; the three fields only forward kwargs."""
        import inspect

        from oldman.web.components.forms.fields import RemoteChoiceValidationMixin

        self.assertIn("allowed_values", inspect.signature(RemoteChoiceValidationMixin.__init__).parameters)
        for field_cls in (AjaxSelectField, AjaxSelectMultipleField, AjaxAutocompleteField):
            with self.subTest(field=field_cls.__name__):
                self.assertNotIn(
                    "allowed_values",
                    inspect.signature(field_cls.__init__).parameters,
                    "the variant declares the keyword itself instead of letting the mixin own it",
                )

    def test_all_three_remote_field_variants_accept_a_source(self) -> None:
        """They are siblings on different WTForms bases, so the behavior is a mixin."""
        from oldman.web.components.forms.fields import RemoteChoiceValidationMixin

        for field_cls in (AjaxSelectField, AjaxSelectMultipleField, AjaxAutocompleteField):
            with self.subTest(field=field_cls.__name__):
                self.assertTrue(issubclass(field_cls, RemoteChoiceValidationMixin))
