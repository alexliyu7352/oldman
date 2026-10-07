"""The permissions the roles App declares: managing roles.

This is the roles App's permissions module (``AppConfig.permissions_module``), so a service
declares them when it installs ``oldman.apps.roles``. The App's other modules import it only
inside the code that checks it: a service without the App must have no ``roles.*`` names, or
its startup refuses them.

Any page that manages roles checks these — the built-in Admin's role page and a project's own
role pages alike.
"""

from __future__ import annotations

from oldman.auth.permissions import declare_permission
from oldman.i18n import gettext_lazy as _

VIEW_ROLES = declare_permission("roles", "view", _("View roles"))
ADD_ROLES = declare_permission("roles", "add", _("Add roles"))
CHANGE_ROLES = declare_permission("roles", "change", _("Change roles"))
DELETE_ROLES = declare_permission("roles", "delete", _("Delete roles"))

__all__ = ["ADD_ROLES", "CHANGE_ROLES", "DELETE_ROLES", "VIEW_ROLES"]
