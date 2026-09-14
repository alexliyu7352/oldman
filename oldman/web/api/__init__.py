"""Public browser response protocol."""

from oldman.web.api.actions import (
    CloseModalAction,
    FeedbackAction,
    RedirectAction,
    ReloadTableAction,
    ReplaceHtmlAction,
    ResponseAction,
)
from oldman.web.api.enums import ApiErrorCode, ApiResponseAction, FeedbackMode, HtmlSwap
from oldman.web.api.responses import DefaultApiFormResponse, DefaultApiResponse

__all__ = [
    "ApiErrorCode",
    "ApiResponseAction",
    "CloseModalAction",
    "DefaultApiFormResponse",
    "DefaultApiResponse",
    "FeedbackAction",
    "FeedbackMode",
    "HtmlSwap",
    "RedirectAction",
    "ReloadTableAction",
    "ReplaceHtmlAction",
    "ResponseAction",
]
