"""Permissions of the {{ app_slug }} App."""

from oldman.auth import Permission, PermissionSet
from oldman.i18n import gettext_lazy as _


class {{ app_class }}Permissions(PermissionSet, namespace="{{ app_slug }}"):
    """What a role may be given in the {{ app_slug }} App."""

    use = Permission(_("Use the {{ app_slug }} MCP tools"))
