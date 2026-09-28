"""Framework authentication models and identity services."""

from oldman.auth.base import AbstractUser
from oldman.auth.contracts import UserModelContractError
from oldman.auth.password_reset import (
    PasswordResetTokenGenerator,
    decode_user_id,
    default_token_generator,
    encode_user_id,
    get_user_by_email,
)
from oldman.auth.permissions import (
    Permission,
    PermissionSet,
    declare_permission,
    declared_permissions,
    get_permission,
)
from oldman.auth.registry import get_user_model, validate_user_model
from oldman.auth.services import (
    UserIdentityError,
    UserManagementError,
    authenticate_user,
    change_user_password,
    ensure_superuser,
    get_user_by_id,
    get_user_by_username,
    has_staff_access,
    is_ordinary_user,
    normalize_email,
    set_user_active,
    touch_last_login,
    user_access_flags,
    user_identity,
    user_identity_matches,
    validate_user_delete,
)
from oldman.auth.settings import AuthSettings, LoginSettings, PasswordResetSettings

__all__ = [
    "AbstractUser",
    "AuthSettings",
    "LoginSettings",
    "PasswordResetSettings",
    "PasswordResetTokenGenerator",
    "Permission",
    "PermissionSet",
    "UserIdentityError",
    "UserManagementError",
    "UserModelContractError",
    "authenticate_user",
    "change_user_password",
    "declare_permission",
    "declared_permissions",
    "decode_user_id",
    "default_token_generator",
    "encode_user_id",
    "ensure_superuser",
    "normalize_email",
    "get_permission",
    "get_user_model",
    "get_user_by_email",
    "get_user_by_id",
    "get_user_by_username",
    "has_staff_access",
    "is_ordinary_user",
    "touch_last_login",
    "set_user_active",
    "user_access_flags",
    "user_identity",
    "user_identity_matches",
    "validate_user_delete",
    "validate_user_model",
]
