"""The permissions the auth App declares: managing user accounts.

This is the auth App's permissions module (``AuthAppConfig.permissions_module``), so a
service declares them when it installs ``oldman.auth``. ``oldman.auth`` itself does not
import it: ``oldman.auth.permissions`` holds the declaration machinery every service
imports, and declaring ``auth.*`` there would reach services without the auth App.

Any page that manages users checks these — the built-in Admin's user management and a
project's own user pages alike.
"""

from __future__ import annotations

from oldman.auth.permissions import declare_permission
from oldman.i18n import gettext_lazy as _

VIEW_USERS = declare_permission("auth", "users.view", _("View users"))
ADD_USERS = declare_permission("auth", "users.add", _("Add users"))
CHANGE_USERS = declare_permission("auth", "users.change", _("Change users"))
DELETE_USERS = declare_permission("auth", "users.delete", _("Delete users"))

__all__ = ["ADD_USERS", "CHANGE_USERS", "DELETE_USERS", "VIEW_USERS"]
