"""Accept-negotiated Form protocol helpers shared by the Admin and project sites."""

from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from typing import Any

from markupsafe import Markup

from oldman.web.api import (
    ApiErrorCode,
    CloseModalAction,
    accepts_html_form_response,
    accepts_json_form_response,
    feedback_response,
    form_error_response,
    form_invalid_response,
    form_response,
    form_saved_response,
    form_success_response,
    modal_close_footer,
    modal_not_found_response,
    modal_response,
    modal_success_response,
)


def request_with(accept: str | None) -> Any:
    return SimpleNamespace(headers={} if accept is None else {"accept": accept})


def body(response: Any) -> dict[str, Any]:
    return json.loads(response.body)


def text(response: Any) -> str:
    return (response.body or b"").decode("utf-8")


class FakeForm:
    def __init__(self) -> None:
        self.render_options: dict[str, Any] | None = None

    def to_api_response(self) -> Any:
        return SimpleNamespace(to_dict=lambda: {"error_code": 1100, "message": "", "errors": {"email": "Required"}, "actions": []})

    async def render(self, **options: Any) -> Markup:
        self.render_options = options
        return Markup("<form>rendered</form>")


class NegotiationTest(unittest.TestCase):
    def test_the_accept_header_selects_json_or_html(self) -> None:
        cases = {
            "application/json, text/plain": (True, False),
            "text/html,application/xhtml+xml": (False, True),
            "text/html, application/json": (True, False),
            "*/*": (False, False),
            None: (False, False),
        }
        for accept, expected in cases.items():
            with self.subTest(accept=accept):
                request = request_with(accept)
                self.assertEqual((accepts_json_form_response(request), accepts_html_form_response(request)), expected)

    def test_form_success_response_redirects_json_clients_through_an_action(self) -> None:
        json_client = form_success_response(request_with("application/json"), "/done")
        self.assertEqual(200, json_client.status)
        self.assertEqual(0, body(json_client)["error_code"])
        self.assertEqual([{"action": "redirect", "url": "/done"}], body(json_client)["actions"])

        browser = form_success_response(request_with("text/html"), "/done")
        self.assertEqual(303, browser.status)
        self.assertEqual("/done", browser.headers["Location"])

    def test_form_invalid_response_serves_json_fragment_or_page(self) -> None:
        form = FakeForm()
        pages: list[str] = []

        async def page() -> Any:
            pages.append("rendered")
            return SimpleNamespace(status=200)

        json_client = asyncio.run(form_invalid_response(request_with("application/json"), form, page=page))
        self.assertEqual(200, json_client.status)
        self.assertEqual({"email": "Required"}, body(json_client)["errors"])

        fragment = asyncio.run(form_invalid_response(request_with("text/html"), form, page=page))
        self.assertEqual(422, fragment.status)
        self.assertEqual("<form>rendered</form>", text(fragment))
        self.assertEqual({}, form.render_options)

        plain = asyncio.run(form_invalid_response(request_with("*/*"), form, page=page))
        self.assertEqual(422, plain.status)
        self.assertEqual(["rendered"], pages)

        # Without a page, everyone but the JSON client gets the fragment; it may be ready markup or a coroutine.
        ready = asyncio.run(form_invalid_response(request_with("*/*"), form, fragment=Markup("<p>ready</p>"), status=400))
        self.assertEqual((400, "<p>ready</p>"), (ready.status, text(ready)))

        async def custom() -> Markup:
            return await form.render(cancel_url="/back")

        lazy = asyncio.run(form_invalid_response(request_with("text/html"), form, fragment=custom))
        self.assertEqual(422, lazy.status)
        self.assertEqual({"cancel_url": "/back"}, form.render_options)


class PayloadTest(unittest.TestCase):
    def test_form_error_response_is_a_business_error_with_field_errors(self) -> None:
        response = form_error_response("Fix the form", errors={"email": "Taken"})
        self.assertEqual(200, response.status)
        self.assertEqual(
            (ApiErrorCode.FORM_INVALID.value, "Fix the form", {"email": "Taken"}, []),
            tuple(body(response)[key] for key in ("error_code", "message", "errors", "actions")),
        )

        invalid = form_error_response("Bad input", error_code=ApiErrorCode.INVALID_REQUEST, status=200)
        self.assertEqual(ApiErrorCode.INVALID_REQUEST.value, body(invalid)["error_code"])

    def test_success_helpers_order_their_actions(self) -> None:
        extra = CloseModalAction(target="#other")
        feedback = body(feedback_response("Saved", text="All good"))
        self.assertEqual([("feedback", "Saved")], [(action["action"], action["title"]) for action in feedback["actions"]])
        self.assertEqual("All good", feedback["actions"][0]["text"])

        saved = body(form_saved_response("Created", url="/items/1", delay_ms=1200, actions=[extra]))
        self.assertEqual(["feedback", "close_modal", "redirect"], [action["action"] for action in saved["actions"]])
        self.assertEqual({"action": "redirect", "url": "/items/1", "delay_ms": 1200}, saved["actions"][-1])

        modal = body(modal_success_response("Deleted", table_target="#items", text="Row gone", feedback_target="#items-feedback", actions=[extra]))
        self.assertEqual(["feedback", "close_modal", "close_modal", "reload_table"], [action["action"] for action in modal["actions"]])
        self.assertEqual({"action": "reload_table", "target": "#items"}, modal["actions"][-1])
        # An inline feedback container replaces the toast when the page has one.
        self.assertEqual("#items-feedback", modal["actions"][0]["target"])

        plain = body(form_response("Ok", status=201))
        self.assertEqual((0, "Ok", []), (plain["error_code"], plain["message"], plain["actions"]))

    def test_modal_response_carries_either_a_full_body_or_body_plus_footer(self) -> None:
        full = modal_response("Edit project", html=Markup("<form></form>"))
        split = modal_response("Raw payload", body=Markup("<pre>{}</pre>"), footer=Markup("<button></button>"), status=206)

        self.assertEqual({"title": "Edit project", "html": "<form></form>"}, body(full))
        self.assertEqual(
            {"title": "Raw payload", "body": "<pre>{}</pre>", "footer": "<button></button>"},
            body(split),
        )
        self.assertEqual((200, 206), (full.status, split.status))

        read_only = body(modal_response("Raw payload", body=Markup("<pre>{}</pre>"), close_label='A "Close" & go'))
        self.assertEqual(str(modal_close_footer('A "Close" & go')), read_only["footer"])
        self.assertIn("A &#34;Close&#34; &amp; go", read_only["footer"])
        with self.assertRaisesRegex(ValueError, "not both"):
            modal_response("Both footers", body="<p></p>", footer="<button></button>", close_label="Close")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            modal_response("Neither")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            modal_response("Both", html="<p></p>", body="<p></p>")

    def test_modal_not_found_response_carries_a_title_and_an_escaped_paragraph(self) -> None:
        response = modal_not_found_response("Delete User", 'User "a&b" not found.')

        # 2xx：Modal 用 axios 取片段，非 2xx 会 reject，弹窗根本不会打开，这句话也就显示不出来。
        self.assertEqual(200, response.status)
        self.assertEqual(
            {"title": "Delete User", "html": '<p class="text-default-500 mb-0">User &#34;a&amp;b&#34; not found.</p>'},
            body(response),
        )
        self.assertEqual(410, modal_not_found_response("Gone", "Gone", status=410).status)


if __name__ == "__main__":
    unittest.main()
