"""Which roles a user holds, and which permissions a role grants — the latter also kept in Redis.

The database is the only source of truth. Each role's permission names are copied to Redis
under ``<namespace>:role:<id>``, so a permission check costs one Redis round trip, not a query:

- Saving a role writes its key after the commit. If that write fails the save reports it,
  and saving again repairs it.
- Deleting a role deletes its key before the delete, inside the same transaction, and again
  after the commit. If Redis refuses the first time nothing is deleted, so a key can never
  outlive its role for want of Redis. Sessions that still carry the role's id find no
  permissions for it, because the database has no such role any more.
- A missing key is read from the database and written back only if it is still missing, so a
  request holding data from before a save cannot overwrite what the save wrote.

Known limit: a request that read a role from the database just before the role was deleted
can write the key back after the delete removed it; sessions still carrying that id keep the
deleted role's permissions until they end. It needs a missing key and a deletion at the same
moment. Role ids are never handed out again, so no other role is affected.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from sqlmodel import delete, select

from oldman.apps.roles.models import Role, UserRole
from oldman.auth.permissions import get_permission
from oldman.db.session import DatabaseManager
from oldman.db.session import db_manager as default_db_manager
from oldman.providers.redis import redis_key


def _key(role_id: int) -> str:
    return redis_key("role", role_id)


async def _connection() -> Any:
    from oldman.web.security.store import security_redis_connection

    return await security_redis_connection()


def checked_permission_names(names: Iterable[str]) -> list[str]:
    """The names sorted without repeats; a name no App declares is refused."""
    unique = sorted(set(names))
    unknown = [name for name in unique if get_permission(name) is None]
    if unknown:
        raise ValueError(f"undeclared permissions: {', '.join(unknown)}")
    return unique


async def publish_role(role: Role) -> None:
    """Copy a saved role's permissions to its cache key. Call it after the commit."""
    await (await _connection()).set(_key(role.id), json.dumps(role.permissions))


async def forget_role(role_id: int) -> None:
    """Drop a role's cache key: before deleting the row, in its transaction, and again after the commit.

    The first call decides whether the delete may happen at all: if Redis refuses, let the
    error roll the transaction back. The second one removes a key that a request reading the
    row just before the delete wrote back in between.
    """
    await (await _connection()).delete(_key(role_id))


async def role_permissions(role_ids: Iterable[int], *, db_manager: DatabaseManager | None = None) -> frozenset[str]:
    """Every permission name the given roles grant, read from Redis and, for missing keys, the database."""
    ids = sorted(set(role_ids))
    if not ids:
        return frozenset()
    connection = await _connection()
    names: set[str] = set()
    missing: list[int] = []
    for role_id, cached in zip(ids, await connection.mget([_key(role_id) for role_id in ids]), strict=True):
        if cached is None:
            missing.append(role_id)
        else:
            names.update(json.loads(cached))
    if missing:
        manager = db_manager if db_manager is not None else default_db_manager
        async with manager.get_read_session() as session:
            rows = (await session.exec(select(Role.id, Role.permissions).where(Role.id.in_(missing)))).all()
        for role_id, permissions in rows:
            names.update(permissions)
            await connection.set(_key(role_id), json.dumps(permissions), nx=True)
    return frozenset(names)


async def user_role_ids(user_id: int, *, db_manager: DatabaseManager | None = None) -> tuple[int, ...]:
    """The ids of the roles a user holds, ascending."""
    manager = db_manager if db_manager is not None else default_db_manager
    async with manager.get_read_session() as session:
        result = await session.exec(select(UserRole.role_id).where(UserRole.user_id == user_id).order_by(UserRole.role_id))
        return tuple(result.all())


async def replace_user_roles(session: Any, user_id: int, role_ids: Iterable[int]) -> bool:
    """Make a user hold exactly these roles, inside the caller's transaction; report whether anything changed.

    Sessions and access tokens carry the role ids they were opened with, so when this returns
    True the caller ends the user's logins after the commit, as it does for changed access flags.
    """
    wanted = set(role_ids)
    current = set((await session.exec(select(UserRole.role_id).where(UserRole.user_id == user_id))).all())
    if current == wanted:
        return False
    if current - wanted:
        await session.exec(delete(UserRole).where(UserRole.user_id == user_id, UserRole.role_id.in_(current - wanted)))
    for role_id in sorted(wanted - current):
        session.add(UserRole(user_id=user_id, role_id=role_id))
    await session.flush()
    return True


__all__ = [
    "checked_permission_names",
    "forget_role",
    "publish_role",
    "replace_user_roles",
    "role_permissions",
    "user_role_ids",
]
