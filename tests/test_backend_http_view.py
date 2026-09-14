"""Oldman HTTPMethodView 认证边界测试。"""

from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace

from sanic.response import text

from oldman.web.session import SessionData


class OldmanHTTPViewTest(unittest.TestCase):
    """验证组件 HTTP 基类的响应模式和权限协议。"""

    def test_response_mode_prefers_query_parameter_then_accept_header(self) -> None:
        """response_mode 参数优先，缺省时才使用 Accept。"""
        from oldman.web.http import resolve_response_mode

        self.assertEqual(resolve_response_mode(make_request(args={"response_mode": "html"}, headers={"accept": "application/json"})), "html")
        self.assertEqual(resolve_response_mode(make_request(args={"response_mode": "json"}, headers={"accept": "text/html"})), "json")
        self.assertEqual(resolve_response_mode(make_request(headers={"accept": "application/json"})), "json")
        self.assertEqual(resolve_response_mode(make_request(headers={"accept": "text/html", "x-requested-with": "XMLHttpRequest"})), "html")

    def test_table_response_type_uses_shared_response_mode_resolution(self) -> None:
        """Table 局部响应也必须和 OldmanHTTPMethodView 使用同一套 response_mode 规则。"""
        from oldman.web.components.tables import BaseTableView

        table = BaseTableView()

        self.assertEqual(table.resolve_response_type(make_request(args={"response_mode": "json"}, headers={"accept": "text/html"})), "json")
        self.assertEqual(table.resolve_response_type(make_request(args={"response_mode": "html"}, headers={"accept": "application/json"})), "html")

    def test_build_login_url_preserves_path_and_query_string(self) -> None:
        """登录跳转 next 必须包含原始 path 和 query string。"""
        from oldman.web.http import build_login_url

        request = make_request(path="/channels-epg", query_string="page=2&q=bbc")

        self.assertEqual(build_login_url(request), "/login?next=%2Fchannels-epg%3Fpage%3D2%26q%3Dbbc")

    def test_json_authentication_required_response_exposes_login_entry_only(self) -> None:
        """JSON 未登录响应由前端补充当前页面 next，不执行响应动作。"""
        from oldman.web.api.enums import ApiErrorCode
        from oldman.web.http import authentication_required_response

        response = authentication_required_response(make_request(headers={"accept": "application/json"}), "json")
        body = response.body
        assert body is not None
        payload = json.loads(body)

        self.assertEqual(response.status, 401)
        self.assertEqual(payload["error_code"], ApiErrorCode.AUTHENTICATION_REQUIRED)
        self.assertEqual(payload["data"], {"login_url": "/login"})
        self.assertEqual(payload["actions"], [])
        self.assertNotIn("action", payload)

    def test_oldman_xhr_html_authentication_response_is_json(self) -> None:
        """局部 HTML 请求不能收到可被误当成片段的登录页面。"""
        from oldman.web.http import authentication_required_response

        response = authentication_required_response(
            make_request(headers={"accept": "text/html", "x-requested-with": "XMLHttpRequest"}),
            "html",
        )
        assert response.body is not None

        self.assertEqual(response.status, 401)
        self.assertEqual(json.loads(response.body)["data"], {"login_url": "/login"})

    def test_html_authentication_required_response_redirects_to_login(self) -> None:
        """HTML 未登录响应必须返回 302 Location。"""
        from oldman.web.http import authentication_required_response

        response = authentication_required_response(make_request(path="/users"), "html")

        self.assertEqual(response.status, 302)
        self.assertEqual(response.headers["Location"], "/login?next=%2Fusers")

    def test_permission_denied_json_preserves_business_error(self) -> None:
        """JSON 权限错误仍为 403，HTML 页面由真实应用专项验证。"""
        from oldman.web.api.enums import ApiErrorCode
        from oldman.web.http import permission_denied_response

        json_response = asyncio.run(permission_denied_response(make_request(headers={"accept": "application/json"}), "json", message="Custom denied"))
        json_body = json_response.body
        assert json_body is not None
        payload = json.loads(json_body)
        self.assertEqual(json_response.status, 403)
        self.assertEqual(payload["error_code"], ApiErrorCode.PERMISSION_DENIED)
        self.assertEqual(payload["message"], "Custom denied")

    def test_view_without_permissions_dispatches_sync_get_and_post(self) -> None:
        """默认不要求登录；同步返回值和 POST 分派必须可用。"""
        from oldman.web.http import OldmanHTTPMethodView

        class DemoView(OldmanHTTPMethodView):
            def get(self, request):
                return text("get-ok")

            def post(self, request):
                return text("post-ok")

        self.assertEqual(asyncio.run(DemoView().dispatch_request(make_request(method="GET"))).body, b"get-ok")
        self.assertEqual(asyncio.run(DemoView().dispatch_request(make_request(method="POST"))).body, b"post-ok")

    def test_head_request_falls_back_to_get(self) -> None:
        """只实现 get 时 HEAD 请求应沿用 Sanic 的 GET fallback。"""
        from oldman.web.http import OldmanHTTPMethodView

        class DemoView(OldmanHTTPMethodView):
            def get(self, request):
                return text("head-ok")

        response = asyncio.run(DemoView().dispatch_request(make_request(method="HEAD")))

        self.assertEqual(response.body, b"head-ok")

    def test_head_without_get_uses_the_standard_unsupported_method_diagnostic(self) -> None:
        """A missing HEAD fallback should not leak an accidental AttributeError."""
        from oldman.web.http import OldmanHTTPMethodView

        class HeadlessView(OldmanHTTPMethodView):
            pass

        with self.assertRaisesRegex(NotImplementedError, "HEAD is not supported"):
            asyncio.run(HeadlessView().dispatch_request(make_request(method="HEAD")))

    def test_other_missing_method_uses_the_same_diagnostic(self) -> None:
        """Unsupported methods share one explicit endpoint-definition error."""
        from oldman.web.http import OldmanHTTPMethodView

        class GetOnlyView(OldmanHTTPMethodView):
            def get(self, request):
                return text("ok")

        with self.assertRaisesRegex(NotImplementedError, "POST is not supported"):
            asyncio.run(GetOnlyView().dispatch_request(make_request(method="POST")))

    def test_authenticated_and_staff_flags_gate_dispatch(self) -> None:
        """require_authenticated/require_staff 控制登录态和 staff 权限检查。"""
        from oldman.web.http import OldmanHTTPMethodView

        class StaffView(OldmanHTTPMethodView):
            require_authenticated = True
            require_staff = True

            async def get(self, request):
                return text("ok")

        unauthenticated = asyncio.run(StaffView().dispatch_request(make_request(headers={"accept": "application/json"})))
        self.assertEqual(unauthenticated.status, 401)

        non_staff = asyncio.run(StaffView().dispatch_request(make_request(session=authenticated_session(), headers={"accept": "application/json"})))
        self.assertEqual(non_staff.status, 403)

        staff = asyncio.run(StaffView().dispatch_request(make_request(session=authenticated_session(is_staff=True))))
        self.assertEqual(staff.body, b"ok")

    def test_check_permission_hook_can_deny_after_staff_passes(self) -> None:
        """check_permission 返回 False 时必须走 on_permission_denied。"""
        from oldman.web.http import OldmanHTTPMethodView

        class DeniedView(OldmanHTTPMethodView):
            require_authenticated = True
            require_staff = True
            response_mode = "json"

            async def check_permission(self, request, *, method_name: str, route_kwargs: dict[str, object]):
                self.seen = (method_name, route_kwargs)
                return False, "Custom denied"

            async def get(self, request, item_id: int):
                return text("never")

        view = DeniedView()
        response = asyncio.run(view.dispatch_request(make_request(session=authenticated_session(is_staff=True)), item_id=12))
        payload = json.loads(response.body)

        self.assertEqual(response.status, 403)
        self.assertEqual(payload["message"], "Custom denied")
        self.assertEqual(view.seen, ("get", {"item_id": 12}))

    def test_table_chart_and_select_endpoints_use_oldman_http_view(self) -> None:
        """Table/Chart/Select endpoint 必须统一经过 OldmanHTTPMethodView。"""
        from oldman.web.components.charts.views import BaseChartView
        from oldman.web.components.selects import SelectProviderView
        from oldman.web.components.tables import BaseTableView
        from oldman.web.http import OldmanHTTPMethodView

        self.assertTrue(issubclass(BaseTableView, OldmanHTTPMethodView))
        self.assertTrue(BaseTableView.require_authenticated)
        self.assertTrue(BaseTableView.require_staff)

        self.assertTrue(issubclass(BaseChartView, OldmanHTTPMethodView))
        self.assertTrue(BaseChartView.require_authenticated)
        self.assertTrue(BaseChartView.require_staff)
        self.assertEqual(BaseChartView.response_mode, "json")

        self.assertTrue(issubclass(SelectProviderView, OldmanHTTPMethodView))
        self.assertTrue(SelectProviderView.require_authenticated)
        self.assertTrue(SelectProviderView.require_staff)
        self.assertEqual(SelectProviderView.response_mode, "json")

    def test_unauthenticated_component_endpoints_return_login_protocol_before_business_logic(self) -> None:
        """未登录请求不能进入组件业务逻辑，应直接返回 401 登录入口。"""
        from oldman.web.components.charts.views import BaseChartView
        from oldman.web.components.selects import SelectProviderView
        from oldman.web.components.tables import BaseTableView

        table_response = asyncio.run(BaseTableView().dispatch_request(make_request(headers={"accept": "application/json"})))
        table_payload = json.loads(table_response.body)
        self.assertEqual(table_response.status, 401)
        self.assertEqual(table_payload["data"], {"login_url": "/login"})
        self.assertEqual(table_payload["actions"], [])

        chart_response = asyncio.run(BaseChartView().dispatch_request(make_request(headers={"accept": "application/json"})))
        chart_payload = json.loads(chart_response.body)
        self.assertEqual(chart_response.status, 401)
        self.assertEqual(chart_payload["data"], {"login_url": "/login"})
        self.assertEqual(chart_payload["actions"], [])

        select_response = asyncio.run(
            SelectProviderView(secret_key="secret").dispatch_request(make_request(headers={"accept": "application/json"}), provider_name="channels")
        )
        select_payload = json.loads(select_response.body)
        self.assertEqual(select_response.status, 401)
        self.assertEqual(select_payload["data"], {"login_url": "/login"})
        self.assertEqual(select_payload["actions"], [])


def authenticated_session(*, is_staff: bool = False) -> SessionData:
    """构造真实的强类型登录 Session。"""
    return SessionData(
        user_id=42,
        username="alex",
        is_active=True,
        is_staff=is_staff,
    )


class Args(dict):
    """Sanic request.args 兼容对象。"""

    def getlist(self, key: str):
        """返回参数列表。"""
        value = self.get(key)
        if value is None:
            return []
        return value if isinstance(value, list) else [value]


def make_request(
    *,
    method: str = "GET",
    args: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    path: str = "/demo",
    query_string: str = "",
    session: SessionData | None = None,
):
    """构造 OldmanHTTPMethodView 测试请求。"""
    return SimpleNamespace(
        method=method,
        args=Args(args or {}),
        headers=headers or {},
        path=path,
        query_string=query_string,
        ctx=SimpleNamespace(session=session),
    )


if __name__ == "__main__":
    unittest.main()
