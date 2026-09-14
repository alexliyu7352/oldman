"""项目级 API 响应模型契约测试。"""

from __future__ import annotations

import json
import unittest
from enum import StrEnum
from pathlib import Path

from oldman.i18n import TranslatableMsgspecModel, gettext_lazy
from oldman.i18n.translations import bind_translations, reset_translations

ROOT = Path(__file__).resolve().parents[1]


class ApiResponseModelTest(unittest.TestCase):
    """验证项目内 DefaultApiResponse 协议。"""

    def test_response_models_use_project_contract_and_msgspec_serialization(self) -> None:
        """项目响应模型必须继承 MsgspecModel，且表单响应继承普通响应。"""
        from oldman.web.api import DefaultApiFormResponse, DefaultApiResponse

        self.assertTrue(issubclass(DefaultApiResponse, TranslatableMsgspecModel))
        self.assertTrue(issubclass(DefaultApiFormResponse, DefaultApiResponse))

    def test_response_to_dict_serializes_ordered_actions_and_lazy_translations(self) -> None:
        """to_dict 输出必须是前端可消费的单层有序动作。"""
        from oldman.web.api import (
            ApiErrorCode,
            CloseModalAction,
            DefaultApiFormResponse,
            DefaultApiResponse,
            FeedbackAction,
            FeedbackMode,
            HtmlSwap,
            RedirectAction,
            ReloadTableAction,
            ReplaceHtmlAction,
        )

        response = DefaultApiResponse(
            error_code=ApiErrorCode.AUTHENTICATION_REQUIRED,
            message=gettext_lazy("Authentication required"),
            data={"detail": gettext_lazy("Sign in first")},
            actions=[
                FeedbackAction(
                    mode=FeedbackMode.ALERT,
                    title=gettext_lazy("Authentication required"),
                    text=gettext_lazy("Sign in first"),
                    icon="warning",
                ),
                ReplaceHtmlAction(target="#content", html="<p>Signed out</p>", swap=HtmlSwap.OUTER),
                CloseModalAction(target="#session-modal"),
                ReloadTableAction(target="#sessions"),
                RedirectAction(url="/login", delay_ms=250),
            ],
        )
        payload = response.to_dict()

        self.assertEqual(payload["error_code"], 1401)
        self.assertEqual(payload["message"], "Authentication required")
        self.assertEqual(payload["data"], {"detail": "Sign in first"})
        self.assertEqual(
            payload["actions"],
            [
                {
                    "action": "feedback",
                    "mode": "alert",
                    "title": "Authentication required",
                    "text": "Sign in first",
                    "icon": "warning",
                },
                {
                    "action": "replace_html",
                    "target": "#content",
                    "html": "<p>Signed out</p>",
                    "swap": "outer",
                },
                {"action": "close_modal", "target": "#session-modal"},
                {"action": "reload_table", "target": "#sessions"},
                {"action": "redirect", "url": "/login", "delay_ms": 250},
            ],
        )
        self.assertNotIn("action", payload)
        self.assertNotIn("html", payload)

        form_response = DefaultApiFormResponse(
            error_code=ApiErrorCode.FORM_INVALID,
            message=gettext_lazy("Form validation failed"),
            errors={"username": gettext_lazy("This field is required.")},
        )
        form_payload = form_response.to_dict()

        self.assertEqual(form_payload["error_code"], 1100)
        self.assertEqual(form_payload["message"], "Form validation failed")
        self.assertEqual(form_payload["errors"], {"username": "This field is required."})

    def test_response_lazy_translation_falls_back_when_catalog_lookup_fails(self) -> None:
        """Response serialization must keep the fixed source-string fallback."""
        from oldman.web.api import DefaultApiResponse

        class MissingCatalog:
            def gettext(self, message: str) -> str:
                raise LookupError(message)

            def ngettext(self, singular: str, plural: str, n: int) -> str:
                raise LookupError(singular)

            def pgettext(self, context: str, message: str) -> str:
                raise LookupError(f"{context}:{message}")

        token = bind_translations(MissingCatalog())
        try:
            payload = DefaultApiResponse(message=gettext_lazy("Source fallback")).to_dict()
        finally:
            reset_translations(token)

        self.assertEqual("Source fallback", payload["message"])

    def test_api_response_action_and_error_code_contract(self) -> None:
        """内置动作名称和辅助枚举必须保持精确协议。"""
        from oldman.web.api import ApiErrorCode, ApiResponseAction, FeedbackMode, HtmlSwap, RedirectAction

        self.assertEqual(ApiErrorCode.AUTHENTICATION_REQUIRED, 1401)
        self.assertEqual(
            [action.value for action in ApiResponseAction],
            ["feedback", "replace_html", "close_modal", "reload_table", "redirect"],
        )
        self.assertTrue(issubclass(ApiResponseAction, StrEnum))
        self.assertTrue(issubclass(FeedbackMode, StrEnum))
        self.assertTrue(issubclass(HtmlSwap, StrEnum))
        with self.assertRaises(ValueError):
            RedirectAction(url="/login", delay_ms=-1)

    def test_web_response_helpers_serialize_framework_and_plain_payloads(self) -> None:
        from oldman.web.api import DefaultApiResponse
        from oldman.web.response import api_response, json_response, replace_html_response

        framework_response = api_response(DefaultApiResponse(message="Saved"), status=201)
        plain_response = json_response({"ok": True}, status=202)
        replace_response = replace_html_response("<p>Updated</p>", target="#result")
        framework_body = framework_response.body
        plain_body = plain_response.body
        assert framework_body is not None
        assert plain_body is not None

        self.assertEqual(framework_response.status, 201)
        self.assertEqual(json.loads(framework_body)["message"], "Saved")
        self.assertEqual(plain_response.status, 202)
        self.assertEqual(json.loads(plain_body), {"ok": True})
        assert replace_response.body is not None
        self.assertEqual(
            json.loads(replace_response.body),
            {
                "error_code": 0,
                "message": "",
                "data": {},
                "actions": [
                    {"action": "replace_html", "target": "#result", "html": "<p>Updated</p>"}
                ],
            },
        )
        with self.assertRaises(ValueError):
            replace_html_response("<p>Invalid</p>", status=422)

    def test_project_code_no_longer_imports_legacy_api_responses(self) -> None:
        """正式项目代码不能继续复用旧包的 DefaultApiResponse/FormResponse。"""
        forbidden = "from " + "ac" + "_base.http.response import DefaultApi"
        scan_roots = [ROOT / "oldman"]
        offenders: list[str] = []
        for scan_root in scan_roots:
            for path in sorted(scan_root.rglob("*.py")):
                source = path.read_text(encoding="utf-8")
                if forbidden in source:
                    offenders.append(path.relative_to(ROOT).as_posix())

        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
