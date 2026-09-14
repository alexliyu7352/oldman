"""项目级通用枚举。"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class ApiErrorCode(IntEnum):
    """统一 API 响应错误码。"""

    OK = 0
    INVALID_REQUEST = 1000
    FORM_INVALID = 1100
    AUTHENTICATION_REQUIRED = 1401
    NOT_FOUND = 1404
    PERMISSION_DENIED = 1403


class ApiResponseAction(StrEnum):
    """框架内置响应动作。"""

    FEEDBACK = "feedback"
    REPLACE_HTML = "replace_html"
    CLOSE_MODAL = "close_modal"
    RELOAD_TABLE = "reload_table"
    REDIRECT = "redirect"


class FeedbackMode(StrEnum):
    """用户反馈的显示方式。"""

    TOAST = "toast"
    ALERT = "alert"


class HtmlSwap(StrEnum):
    """HTML 替换范围。"""

    INNER = "inner"
    OUTER = "outer"
