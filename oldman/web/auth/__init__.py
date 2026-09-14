"""Public Web authentication adapters."""

from oldman.web.auth.decorators import (
    api_authorized,
    api_key_authorized,
    api_login_required,
    login_required,
    staff_required,
    superuser_required,
)
from oldman.web.auth.forms import UserPasswordForm
from oldman.web.auth.session import session_data_for_user
from oldman.web.auth.user_session import (
    UserSessionProfile,
    render_session_password_modal,
    save_language_preference,
    session_profile,
    update_session_password,
)

__all__ = [
    "api_authorized",
    "api_key_authorized",
    "api_login_required",
    "login_required",
    "render_session_password_modal",
    "save_language_preference",
    "session_data_for_user",
    "session_profile",
    "staff_required",
    "superuser_required",
    "update_session_password",
    "UserPasswordForm",
    "UserSessionProfile",
]
