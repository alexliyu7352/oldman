"""Built-in Admin application."""

from oldman.apps.admin.model_admin import AdminUserModelAdmin, ModelAdmin
from oldman.apps.admin.runtime import install_admin
from oldman.apps.admin.site import AdminSite, site
from oldman.apps.admin.users import AdminUserManagementError

__all__ = [
    "AdminSite",
    "AdminUserManagementError",
    "AdminUserModelAdmin",
    "ModelAdmin",
    "install_admin",
    "site",
]
