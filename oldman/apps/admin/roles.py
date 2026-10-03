"""The Admin page for roles, registered when the service installs ``oldman.apps.roles``.

Saving a role rewrites its cached permissions once the transaction commits; deleting one drops
the cache key before the delete and again after it. Permission checks read the cache, not the
database.
"""

from __future__ import annotations

from typing import Any

from redis.exceptions import RedisError
from sanic.exceptions import ServiceUnavailable

from oldman.apps.admin.model_admin import ModelAdmin
from oldman.i18n import gettext
from oldman.logging import get_logger

logger = get_logger(__name__)


class RoleModelAdmin(ModelAdmin):
    """Roles edited with the shared RoleForm; each save or delete refreshes the role's cache key."""

    list_display = ("name", "description")
    search_fields = ("name", "description")
    ordering = ("name",)
    # Beside the users, in the auth group, though the roles have their own App.
    menu_group = "auth"

    def get_form_class(self, *, create: bool = True, dialect: Any = None) -> type[Any]:
        """Every role is edited through the same form: name, description and grouped permission checkboxes."""
        del create, dialect
        from oldman.apps.roles.forms import RoleForm

        return RoleForm

    async def after_save(self, request: Any, instance: Any, *, created: bool) -> None:
        """Write the saved permissions to the role's cache key.

        The role is already saved. If Redis refuses, the response says the permission store is
        unavailable, and saving the role again once it is back repairs the key.
        """
        del request, created
        from oldman.apps.roles.store import publish_role

        try:
            await publish_role(instance)
        except RedisError as exc:
            raise ServiceUnavailable(gettext("The permission store is unavailable")) from exc

    async def delete_model(self, session: Any, instance: Any) -> None:
        """Drop the role's cache key first, inside the transaction, then delete the row.

        If Redis refuses, the error rolls the transaction back and nothing is deleted. The other
        order would leave a key nothing can remove: the role would be gone, and the next delete
        would find no role.
        """
        from oldman.apps.roles.store import forget_role

        try:
            await forget_role(instance.id)
        except RedisError as exc:
            raise ServiceUnavailable(gettext("The permission store is unavailable")) from exc
        await super().delete_model(session, instance)

    async def after_delete(self, request: Any, instance: Any) -> None:
        """Drop the key once more after the commit.

        A request that read the role just before the delete may have written the key back in
        between. The delete already stands, so a refusal here is logged, not reported.
        """
        del request
        from oldman.apps.roles.store import forget_role

        try:
            await forget_role(instance.id)
        except RedisError:
            logger.warning("Could not drop the cache key of deleted role %s", instance.id, exc_info=True)


__all__ = ["RoleModelAdmin"]
