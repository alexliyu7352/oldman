"""Public Web authentication adapters."""

from oldman.web.auth.account import AccountFlow, account_urls
from oldman.web.auth.decorators import (
    api_login_required,
    authenticated_by,
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
    LoginFlow,
    LoginRateLimit,
    authenticate_credentials,
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
from oldman.web.auth.permissions import can_manage_user, has_perm, permissions_not_held, require_perm, role_ids_for_login, roles_installed
from oldman.web.auth.redirects import safe_next_url
from oldman.web.auth.session import end_user_logins, revoke_user_logins, session_data_for_user
from oldman.web.auth.tables import UserTable, user_cell_value, user_row_actions
from oldman.web.auth.tokens import TokenFlow
from oldman.web.auth.user_management import UserManagementFlow, finish_user_change, user_change_text
from oldman.web.auth.user_session import (
    SIGN_IN_AGAIN_DELAY_MS,
    UserSessionProfile,
    authenticated_session,
    render_session_password_modal,
    save_language_preference,
    session_profile,
    update_session_password,
)

__all__ = [
    "INVALID_CREDENTIALS",
    "RATE_LIMITED",
    "SIGN_IN_AGAIN_DELAY_MS",
    "AccountFlow",
    "LoginFlow",
    "LoginForm",
    "LoginRateLimit",
    "account_urls",
    "authenticate_credentials",
    "PasswordResetFlow",
    "PasswordResetForm",
    "PasswordResetRequestForm",
    "RequestOutcome",
    "SessionPasswordForm",
    "TokenFlow",
    "UserFilterForm",
    "UserManagementFlow",
    "UserModelForm",
    "UserPasswordForm",
    "UserSessionProfile",
    "authenticated_session",
    "can_manage_user",
    "UserTable",
    "api_login_required",
    "authenticated_by",
    "finish_user_change",
    "form_value",
    "has_perm",
    "permissions_not_held",
    "login_error_message",
    "login_error_url",
    "login_required",
    "login_settings",
    "login_user",
    "logout_user",
    "remember_me_requested",
    "end_user_logins",
    "revoke_user_logins",
    "render_session_password_modal",
    "require_perm",
    "role_ids_for_login",
    "roles_installed",
    "safe_next_url",
    "save_language_preference",
    "session_data_for_user",
    "session_profile",
    "staff_required",
    "superuser_required",
    "update_session_password",
    "user_cell_value",
    "user_change_text",
    "user_create_form_class",
    "user_delete_modal_response",
    "user_edit_form_class",
    "user_row_actions",
    "user_status_modal_response",
]
