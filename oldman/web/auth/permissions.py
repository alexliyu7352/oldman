"""Checking a permission: does the request's user hold it through their roles?

A superuser holds every permission. Anyone else holds what the roles in their session or
access token grant: the role ids travel with the login, each role's permissions are read
from the roles store (Redis, then the database). A project without ``oldman.apps.roles``
has no roles, so only superusers pass.

Checks take the declared Permission object, never a name, so a misspelling fails on import.
Where a check belongs is the business's call: a view calls ``require_perm``, a table or select
overrides ``check_auth`` and calls ``has_perm``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from redis.exceptions import RedisError
from sanic.exceptions import ServiceUnavailable

from oldman.auth import is_ordinary_user
from oldman.auth.permissions import Permission
from oldman.db import DatabaseManager
from oldman.i18n import gettext
from oldman.web.authentication import request_user
from oldman.web.exceptions import Forbidden

ROLES_APP_LABEL = "roles"


async def _held_permissions(request: Any, db_manager: DatabaseManager | None = None) -> frozenset[str]:
    """The permission names the request's roles grant, read once per request.

    Roles missing from the cache are read through `db_manager`, the process's by default: a
    service whose roles live in another database (an Admin installed on its own manager)
    passes that one.
    """
    held = getattr(request.ctx, "permissions", None)
    if isinstance(held, frozenset):
        return held
    role_ids = request_user(request).role_ids
    # A service without the roles App grants nothing through roles, even to a login that another
    # service sharing the session opened with role ids; it never reads the roles store or tables.
    if role_ids and roles_installed(getattr(request, "app", None)):
        from oldman.apps.roles.store import role_permissions

        try:
            held = await role_permissions(role_ids, db_manager=db_manager)
        except RedisError as exc:
            # A permission that cannot be looked up is not granted, and not silently denied either.
            raise ServiceUnavailable(gettext("The permission store is unavailable", request=request)) from exc
    else:
        held = frozenset()
    request.ctx.permissions = held
    return held


async def has_perm(request: Any, permission: Permission, *, db_manager: DatabaseManager | None = None) -> bool:
    """Whether the request's user holds this permission; `db_manager` holds the roles, the process's by default."""
    if not isinstance(permission, Permission) or not permission.name:
        raise TypeError("has_perm takes a declared Permission, not a name")
    user = request_user(request)
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return permission.name in await _held_permissions(request, db_manager)


async def permissions_not_held(request: Any, names: Iterable[str], *, db_manager: DatabaseManager | None = None) -> list[str]:
    """Which of these permission names the request's user does not hold, sorted; none for a superuser.

    For handing permissions on. Whoever may edit roles, or give users roles, could otherwise
    grant more than they have: to a role they hold themselves, or to an account they control.
    What a role or a user already had is not handed on again, so callers pass only what the
    change adds.
    """
    user = request_user(request)
    if user.is_superuser:
        return []
    held = await _held_permissions(request, db_manager) if user.is_authenticated else frozenset()
    return sorted(set(names) - held)


async def require_perm(request: Any, permission: Permission, *, db_manager: DatabaseManager | None = None) -> None:
    """Refuse the request with 403 unless its user holds this permission."""
    if not await has_perm(request, permission, db_manager=db_manager):
        raise Forbidden(gettext("Permission denied", request=request))


def can_manage_user(request: Any, target: Any = None, *, makes_privileged: bool = False) -> bool:
    """Whether the request's user may change this account.

    A superuser may change any. Anyone else only ordinary accounts (neither staff nor
    superuser), and may not make one staff or superuser. `target` is None when the account
    is being created; `makes_privileged` says whether the change would give it either flag.
    """
    if request_user(request).is_superuser:
        return True
    if target is not None and not is_ordinary_user(target):
        return False
    return not makes_privileged


def roles_installed(app: Any) -> bool:
    """Whether the service installs ``oldman.apps.roles``: without it there are no roles to read or assign."""
    registry = getattr(getattr(app, "ctx", None), "app_registry", None)
    return registry is not None and ROLES_APP_LABEL in registry.labels


async def role_ids_for_login(request: Any, user_id: int, *, db_manager: DatabaseManager | None = None) -> tuple[int, ...]:
    """The role ids to write into a new session or access token: none unless the roles App is installed."""
    if not roles_installed(request.app):
        return ()
    from oldman.apps.roles.store import user_role_ids

    return await user_role_ids(user_id, db_manager=db_manager)


__all__ = ["can_manage_user", "has_perm", "permissions_not_held", "require_perm", "role_ids_for_login", "roles_installed"]
