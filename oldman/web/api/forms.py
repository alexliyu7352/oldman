"""Accept-negotiated responses for the browser Form protocol.

One submit endpoint serves three clients: the mounted Form component (JSON with ordered actions), a
fragment consumer such as Turbo (HTML, 422 on errors) and a plain browser (redirect or full page). These
helpers pick the branch from the Accept header so no site spells the negotiation out again.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from markupsafe import Markup, escape

from oldman.i18n import LazyTranslation
from oldman.web.api.actions import CloseModalAction, FeedbackAction, RedirectAction, ReloadTableAction, ResponseAction
from oldman.web.api.enums import ApiErrorCode
from oldman.web.api.responses import DefaultApiFormResponse
from oldman.web.request import request_accepts_json

# oldman.web.response builds on the payload types of this package, so the response constructors are
# imported where they are used to keep the package importable in either order.

Message = str | LazyTranslation
FragmentSource = Markup | str | Callable[[], Awaitable[Any]]


def accepts_json_form_response(request: Any) -> bool:
    """The mounted Form component asks for the JSON protocol through its Accept header."""
    return request_accepts_json(request)


def accepts_html_form_response(request: Any) -> bool:
    """A fragment consumer (Turbo, fetch) asks for HTML and not for JSON."""
    accept = str((getattr(request, "headers", {}) or {}).get("accept", "")).lower()
    return "text/html" in accept and not accepts_json_form_response(request)


def form_response(
    message: Message = "",
    *,
    actions: Sequence[ResponseAction] = (),
    errors: Mapping[str, Message] | None = None,
    error_code: ApiErrorCode = ApiErrorCode.OK,
    status: int = 200,
):
    """One JSON Form payload; the building block the helpers below share."""
    from oldman.web.response import json_response

    payload = DefaultApiFormResponse(error_code=error_code, message=message, errors=dict(errors or {}), actions=list(actions))
    return json_response(payload.to_dict(), status=status)


def form_error_response(
    message: Message,
    *,
    errors: Mapping[str, Message] | None = None,
    error_code: ApiErrorCode = ApiErrorCode.FORM_INVALID,
    status: int = 200,
):
    """A business error the Form shows inline: HTTP 200, a non-zero error code and concrete field errors only."""
    return form_response(message, errors=errors, error_code=error_code, status=status)


def _feedback(message: Message, text: Message | None, target: str | None) -> FeedbackAction:
    """The success toast; `target` renders it inline in that container instead of as a toast."""
    return FeedbackAction(title=message, text=text, icon="success", target=target)


def feedback_response(
    message: Message,
    *,
    text: Message | None = None,
    feedback_target: str | None = None,
    actions: Sequence[ResponseAction] = (),
):
    """Success that keeps the page: a Feedback toast, then `actions` in order."""
    return form_response(message, actions=[_feedback(message, text, feedback_target), *actions])


def form_saved_response(
    message: Message,
    *,
    url: str,
    delay_ms: int = 0,
    feedback_target: str | None = None,
    actions: Sequence[ResponseAction] = (),
):
    """Success that leaves the page: Feedback, then `actions`, then a redirect (after `delay_ms`)."""
    return form_response(message, actions=[_feedback(message, None, feedback_target), *actions, RedirectAction(url=url, delay_ms=delay_ms)])


def modal_success_response(
    message: Message,
    *,
    table_target: str,
    text: Message | None = None,
    feedback_target: str | None = None,
    actions: Sequence[ResponseAction] = (),
):
    """Success inside a row-action modal: Feedback, `actions`, close the modal, reload the table."""
    return form_response(
        message,
        actions=[_feedback(message, text, feedback_target), *actions, CloseModalAction(), ReloadTableAction(target=table_target)],
    )


def modal_close_footer(label: Message):
    """The footer of a read-only modal: one secondary button that closes it."""
    return Markup('<button type="button" class="om-button om-button-light" data-om-modal-close>{}</button>').format(str(label))


def modal_response(
    title: Message,
    *,
    html: Markup | str | None = None,
    body: Markup | str | None = None,
    footer: Markup | str | None = None,
    close_label: Message | None = None,
    status: int = 200,
):
    """The payload a remote modal expects: its title plus the content to put inside it.

    `html` 和 `body` 在协议上是同一件事——Modal 组件把两者写进同一个容器（`parts.body ?? parts.html`），
    所以只能给一个，多给一个只会让"哪个生效"变成猜谜。两个名字都保留是因为调用方的语义不同：整段
    片段用 `html`，一段正文配 `footer`（一排按钮）或 `close_label`（只读弹窗的单个关闭按钮）用 `body`。

    **标题和内容都按 HTML 写入**（组件用 `innerHTML`），这个函数不替调用方转义：拼进去的用户数据由
    调用方自己 `escape()`。它只对自己生成的部分负责，例如 `close_label` 和 `modal_not_found_response`
    里的那句话。
    """
    from oldman.web.response import json_response

    if (html is None) == (body is None):
        raise ValueError("modal_response takes exactly one of html= or body=")
    if footer is not None and close_label is not None:
        raise ValueError("modal_response takes footer= or close_label=, not both")
    payload: dict[str, Any] = {"title": str(title)}
    if html is not None:
        payload["html"] = str(html)
    else:
        payload["body"] = str(body)
    resolved_footer = modal_close_footer(close_label) if close_label is not None else footer
    if resolved_footer is not None:
        payload["footer"] = str(resolved_footer)
    return json_response(payload, status=status)


def modal_not_found_response(title: Message, message: Message, *, status: int = 200):
    """The modal payload for an object that is gone: the modal title and one muted paragraph.

    The row action opened the modal from a list the browser has been holding for a while, so "the
    record was deleted meanwhile" is a normal answer, not a server error page.

    它是 2xx 的：Modal 组件用 axios 取这段片段，非 2xx 会直接 reject，弹窗连打开都不会打开，
    这句话也就永远显示不出来。要让前端把它当失败处理时才显式传 `status=`。
    """
    return modal_response(title, html=f'<p class="text-default-500 mb-0">{escape(str(message))}</p>', status=status)


def form_success_response(request: Any, redirect_url: str, *, status: int = 303):
    """After a save: the JSON client receives a RedirectAction, a plain browser a redirect."""
    from oldman.web.response import redirect_response

    if accepts_json_form_response(request):
        return form_response(actions=[RedirectAction(url=redirect_url)])
    return redirect_response(redirect_url, status=status)


async def form_invalid_response(
    request: Any,
    form: Any,
    *,
    fragment: FragmentSource | None = None,
    page: Callable[[], Awaitable[Any]] | None = None,
    status: int = 422,
):
    """A form that failed validation, in the shape the client asked for.

    JSON clients get `form.to_api_response()` with HTTP 200 (validation is a business outcome). Fragment
    clients, and everyone when no `page` is given, get the rendered form (`fragment`: ready markup, or an
    async callable producing it; default `form.render()`) with `status`. A plain browser gets `page()`
    with its status set to `status`.
    """
    from oldman.web.response import html_response, json_response

    if accepts_json_form_response(request):
        return json_response(form.to_api_response().to_dict(), status=200)
    if page is None or accepts_html_form_response(request):
        if fragment is None:
            rendered = await form.render()
        elif callable(fragment):
            rendered = await fragment()
        else:
            rendered = fragment
        return html_response(str(rendered), status=status)
    response = await page()
    response.status = status
    return response


__all__ = [
    "accepts_html_form_response",
    "accepts_json_form_response",
    "feedback_response",
    "form_error_response",
    "form_invalid_response",
    "form_response",
    "form_saved_response",
    "form_success_response",
    "modal_close_footer",
    "modal_not_found_response",
    "modal_response",
    "modal_success_response",
]
