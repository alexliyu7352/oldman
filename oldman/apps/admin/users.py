"""User-management safety rules owned by the built-in Admin app."""

from __future__ import annotations

from typing import Any

from oldman.auth import UserIdentityError, user_identity


class AdminUserManagementError(ValueError):
    """Report a rejected Admin user-management operation."""


def admin_user_identity_matches(user: Any, user_id: int | None) -> bool:
    """Compare one mapped User with the current integer Session identity."""
    if type(user_id) is not int:
        return False
    try:
        identity = user_identity(user)
    except UserIdentityError:
        return False
    return identity == user_id


def change_admin_user_password(user: Any, raw_password: str) -> None:
    """Replace a configured User password through its required model method."""
    user.set_password(raw_password)


def set_admin_user_active(
    user: Any,
    is_active: bool,
    *,
    current_user_id: int | None,
) -> None:
    """Change active state without allowing the current User to self-disable."""
    if not is_active and admin_user_identity_matches(user, current_user_id):
        raise AdminUserManagementError("cannot disable current user")
    user.is_active = bool(is_active)


def validate_admin_user_delete(user: Any, *, current_user_id: int | None) -> None:
    """Reject deleting the current User or any superuser."""
    if admin_user_identity_matches(user, current_user_id):
        raise AdminUserManagementError("cannot delete current user")
    if bool(user.is_superuser):
        raise AdminUserManagementError("cannot delete superuser")


__all__ = [
    "AdminUserManagementError",
    "admin_user_identity_matches",
    "change_admin_user_password",
    "set_admin_user_active",
    "validate_admin_user_delete",
]
