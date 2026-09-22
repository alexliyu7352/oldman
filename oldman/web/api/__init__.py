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
from oldman.web.api.forms import (
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
