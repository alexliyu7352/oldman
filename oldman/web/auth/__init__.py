"""Public Web authentication adapters."""

from oldman.web.auth.decorators import (
    api_authorized,
    api_key_authorized,
    api_login_required,
    login_required,
    staff_required,
    superuser_required,
)
from oldman.web.auth.forms import (
    LoginForm,
    SessionPasswordForm,
    UserFilterForm,
    UserModelForm,
    UserPasswordForm,
    user_create_form_class,
    user_edit_form_class,
)
from oldman.web.auth.login import (
    INVALID_CREDENTIALS,
    RATE_LIMITED,
    LoginRateLimit,
    form_value,
    login_error_message,
    login_error_url,
    login_settings,
    login_user,
    logout_user,
    remember_me_requested,
)
from oldman.web.auth.modals import user_delete_modal_response, user_status_modal_response
from oldman.web.auth.password_reset import (
    PasswordResetFlow,
    PasswordResetForm,
    PasswordResetRequestForm,
    RequestOutcome,
)
from oldman.web.auth.redirects import safe_next_url
from oldman.web.auth.session import revoke_user_sessions, session_data_for_user
from oldman.web.auth.tables import UserTable, user_cell_value, user_row_actions
from oldman.web.auth.user_session import (
    SIGN_IN_AGAIN_DELAY_MS,
    UserSessionProfile,
    render_session_password_modal,
    save_language_preference,
    session_profile,
    update_session_password,
)

__all__ = [
    "INVALID_CREDENTIALS",
    "RATE_LIMITED",
    "SIGN_IN_AGAIN_DELAY_MS",
    "LoginForm",
    "LoginRateLimit",
    "PasswordResetFlow",
    "PasswordResetForm",
    "PasswordResetRequestForm",
    "RequestOutcome",
    "SessionPasswordForm",
    "UserFilterForm",
    "UserModelForm",
    "UserPasswordForm",
    "UserSessionProfile",
    "UserTable",
    "api_authorized",
    "api_key_authorized",
    "api_login_required",
    "form_value",
    "login_error_message",
    "login_error_url",
    "login_required",
    "login_settings",
    "login_user",
    "logout_user",
    "remember_me_requested",
    "revoke_user_sessions",
    "render_session_password_modal",
    "safe_next_url",
    "save_language_preference",
    "session_data_for_user",
    "session_profile",
    "staff_required",
    "superuser_required",
    "update_session_password",
    "user_cell_value",
    "user_create_form_class",
    "user_delete_modal_response",
    "user_edit_form_class",
    "user_row_actions",
    "user_status_modal_response",
]
