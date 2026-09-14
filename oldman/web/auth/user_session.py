"""Shared current-user session views and response helpers."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from markupsafe import escape

import oldman.conf as conf
from oldman.auth import change_user_password, get_user_by_id
from oldman.auth.settings import AuthSettings
from oldman.db import DatabaseManager
from oldman.i18n import LanguageRegistry, LazyTranslation, gettext
from oldman.web.api import (
    ApiErrorCode,
    CloseModalAction,
    DefaultApiFormResponse,
    FeedbackAction,
    ResponseAction,
)
from oldman.web.auth.forms import UserPasswordForm
from oldman.web.response import json_response
from oldman.web.session import SessionData
from oldman.web.template import render_component_template


@dataclass(frozen=True, slots=True)
class UserSessionProfile:
    """Template-safe projection of one strongly typed login snapshot."""

    username: str
    display_name: str
    login_ip: str
    login_time: str
    is_active: bool
    is_staff: bool
    is_superuser: bool


def session_profile(session_data: SessionData) -> UserSessionProfile:
    """Build the current-session page data without querying the User table."""
    login_time = "-"
    if session_data.login_time:
        try:
            login_time = dt.datetime.fromtimestamp(
                session_data.login_time,
                tz=dt.UTC,
            ).strftime("%Y-%m-%d %H:%M UTC")
        except (OverflowError, OSError, ValueError):
            login_time = "-"
    return UserSessionProfile(
        username=session_data.username or "-",
        display_name=session_data.display_name or session_data.username or "-",
        login_ip=session_data.login_ip or "-",
        login_time=login_time,
        is_active=session_data.is_active,
        is_staff=session_data.is_staff,
        is_superuser=session_data.is_superuser,
    )


async def render_session_password_modal(
    request: Any,
    *,
    action: str,
    auth_settings: AuthSettings | None = None,
    db_manager: DatabaseManager | None = None,
):
    """Render the password form for the User identified by this request Session."""
    session_data = _request_session(request)
    user_id = _authenticated_user_id(session_data)
    user = await get_user_by_id(
        user_id,
        auth_settings=auth_settings,
        db_manager=db_manager,
    )
    if user is None:
        message = gettext("Current session user not found.", request=request)
        return json_response(
            {
                "title": gettext("Change Password", request=request),
                "html": f'<p class="text-default-500 mb-0">{escape(message)}</p>',
            },
            status=404,
        )

    form = UserPasswordForm(request=request)
    modal_html = await render_component_template(
        form,
        "oldman/auth/partials/password_form.html",
        {"action": action, "form": form, "user": user},
    )
    username = escape(str(getattr(user, "username", session_data.username)))
    return json_response(
        {
            "title": (
                f'{gettext("Change Session Password", request=request)} · '
                f"{username}"
            ),
            "html": str(modal_html),
        }
    )


async def update_session_password(
    request: Any,
    *,
    success_actions: Sequence[ResponseAction] = (),
    auth_settings: AuthSettings | None = None,
    db_manager: DatabaseManager | None = None,
):
    """Change the current User password and include host-owned success actions."""
    form = UserPasswordForm.from_request(request)
    if not await form.validate():
        return json_response(form.to_api_response().to_dict())

    session_data = _request_session(request)
    user_id = _authenticated_user_id(session_data)
    user = await change_user_password(
        user_id,
        str(form.cleaned_data["password"]),
        auth_settings=auth_settings,
        db_manager=db_manager,
    )
    if user is None:
        return _form_error_response(
            gettext("Current session user not found", request=request),
            status=404,
        )

    username = str(getattr(user, "username", session_data.username))
    message = gettext("Session password changed", request=request)
    description = gettext(
        "%(username)s password was updated.",
        request=request,
        username=username,
    )
    actions: list[ResponseAction] = [
        FeedbackAction(
            title=message,
            text=description,
            icon="success",
        ),
        *success_actions,
        CloseModalAction(),
    ]
    payload = DefaultApiFormResponse(
        error_code=ApiErrorCode.OK,
        message=message,
        actions=actions,
    )
    return json_response(payload.to_dict())


def save_language_preference(
    request: Any,
    *,
    registry: LanguageRegistry,
):
    """Normalize and persist one browser language preference in shared cookies."""
    payload = request.json if isinstance(request.json, Mapping) else {}
    language = registry.resolve(str(payload.get("language", "")))
    if not language:
        message = gettext("Unsupported language.", request=request)
        return _form_error_response(
            message,
            errors={"language": message},
        )

    response = json_response(
        DefaultApiFormResponse(
            error_code=ApiErrorCode.OK,
            message=gettext("Language preference saved.", request=request),
            data={"language": language},
        ).to_dict()
    )
    secure = conf.settings.web.session.cookie_secure
    for cookie_name in ("lang", "preferred_language"):
        response.add_cookie(
            cookie_name,
            language,
            httponly=False,
            max_age=365 * 24 * 60 * 60,
            path="/",
            samesite="Lax",
            secure=secure,
        )
    return response


def _request_session(request: Any) -> SessionData:
    """Return the strongly typed request Session or report missing middleware."""
    session_data = getattr(getattr(request, "ctx", None), "session", None)
    if not isinstance(session_data, SessionData):
        raise RuntimeError("Current-user views require Session middleware")
    return session_data


def _authenticated_user_id(session_data: SessionData) -> int:
    """Return the integer identity required by current-user database operations."""
    if not session_data.is_authenticated() or session_data.user_id is None:
        raise RuntimeError("Current-user views require an authenticated Session")
    return session_data.user_id


def _form_error_response(
    message: str,
    *,
    status: int = 200,
    errors: dict[str, str] | None = None,
):
    """Return the Form error protocol consumed by the shared frontend."""
    resolved_errors: dict[str, str | LazyTranslation] = dict(errors or {})
    payload = DefaultApiFormResponse(
        error_code=ApiErrorCode.FORM_INVALID,
        message=message,
        errors=resolved_errors,
    )
    return json_response(payload.to_dict(), status=status)


__all__ = [
    "UserSessionProfile",
    "render_session_password_modal",
    "save_language_preference",
    "session_profile",
    "update_session_password",
]
