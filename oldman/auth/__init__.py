"""Framework authentication models and identity services."""

from oldman.auth.base import AbstractUser
from oldman.auth.contracts import UserModelContractError
from oldman.auth.registry import get_user_model, validate_user_model
from oldman.auth.services import (
    UserIdentityError,
    authenticate_user,
    change_user_password,
    ensure_superuser,
    get_user_by_id,
    get_user_by_username,
    has_staff_access,
    touch_last_login,
    user_identity,
)
from oldman.auth.settings import AuthSettings

__all__ = [
    "AbstractUser",
    "AuthSettings",
    "UserIdentityError",
    "UserModelContractError",
    "authenticate_user",
    "change_user_password",
    "ensure_superuser",
    "get_user_model",
    "get_user_by_id",
    "get_user_by_username",
    "has_staff_access",
    "touch_last_login",
    "user_identity",
    "validate_user_model",
]
