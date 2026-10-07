"""The Admin page for roles, registered when the service installs ``oldman.apps.roles``.

Saving a role rewrites its cached permissions once the transaction commits; deleting one drops
the cache key before the delete and again after it (``oldman.apps.roles.management``). Permission
checks read the cache, not the database.
"""

from __future__ import annotations

from typing import Any

from oldman.apps.admin.model_admin import ModelAdmin
from oldman.auth import Permission


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

    def permission(self, action: str) -> Permission:
        """Role management checks the roles App's permissions, not Admin model permissions.

        They are the ones a project's own role pages check too, so a role that may change roles
        may do so wherever roles are managed.
        """
        # Imported here: importing the Admin must declare no roles.* permission.
        from oldman.apps.roles import permissions

        return {
            "view": permissions.VIEW_ROLES,
            "add": permissions.ADD_ROLES,
            "change": permissions.CHANGE_ROLES,
            "delete": permissions.DELETE_ROLES,
        }[action]

    async def after_save(self, request: Any, instance: Any, *, created: bool) -> None:
        """Write the saved permissions to the role's cache key; a 503 if Redis refuses, the role saved."""
        del request, created
        from oldman.apps.roles.management import publish_saved_role

        await publish_saved_role(instance)

    async def delete_model(self, session: Any, instance: Any) -> None:
        """Drop the role's cache key first, inside the transaction, then delete the row; a 503 deletes nothing."""
        from oldman.apps.roles.management import delete_role

        await delete_role(session, instance)

    async def after_delete(self, request: Any, instance: Any) -> None:
        """Drop the key once more after the commit; a refusal is logged, not reported."""
        del request
        from oldman.apps.roles.management import forget_deleted_role

        await forget_deleted_role(instance.id)


__all__ = ["RoleModelAdmin"]
