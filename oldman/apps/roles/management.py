"""Saving and deleting a role so that permission checks see the change: the steps every role page takes.

Permission checks read a role's permissions from its Redis key (``oldman.apps.roles.store``), and
the key never expires, so a page that saves or deletes a role keeps it in step:

- once the save has committed, write the key (`publish_saved_role`);
- inside the delete's transaction, drop the key before the row (`delete_role`), and drop it once
  more after the delete has committed (`forget_deleted_role`).

The built-in Admin's role page calls these.
"""

from __future__ import annotations

from typing import Any

from redis.exceptions import RedisError
from sanic.exceptions import ServiceUnavailable

from oldman.apps.roles import store
from oldman.apps.roles.models import Role
from oldman.i18n import gettext
from oldman.logging import get_logger

logger = get_logger(__name__)


async def publish_saved_role(role: Role) -> None:
    """Write the saved permissions to the role's cache key; call it once the save has committed.

    The role is saved by then. If Redis refuses, this raises a 503 saying the permission store
    is unavailable, and saving the role again once Redis is back repairs the key.
    """
    try:
        await store.publish_role(role)
    except RedisError as exc:
        raise ServiceUnavailable(gettext("The permission store is unavailable")) from exc


async def delete_role(session: Any, role: Role) -> None:
    """Drop the role's cache key, then delete its row, inside the caller's transaction.

    If Redis refuses, the 503 raised rolls the transaction back and nothing is deleted. The other
    order would leave a key nothing can remove: the role would be gone, and the next delete
    would find no role.
    """
    try:
        await store.forget_role(role.id)
    except RedisError as exc:
        raise ServiceUnavailable(gettext("The permission store is unavailable")) from exc
    await session.delete(role)
    await session.flush()


async def forget_deleted_role(role_id: int) -> None:
    """Drop the key once more after the delete has committed.

    A request that read the role just before the delete may have written the key back in
    between. The delete already stands, so a refusal here is logged, not reported.
    """
    try:
        await store.forget_role(role_id)
    except RedisError:
        logger.warning("Could not drop the cache key of deleted role %s", role_id, exc_info=True)


__all__ = ["delete_role", "forget_deleted_role", "publish_saved_role"]
