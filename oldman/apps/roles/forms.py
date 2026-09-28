"""Editing a role: its name, description and the permissions it grants.

The built-in Admin uses this form, and a project's own role pages can use it as well.
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import select
from wtforms import StringField, ValidationError
from wtforms.validators import DataRequired, Length, Optional

from oldman.apps import AppNotInstalledError
from oldman.apps.roles.models import Role
from oldman.apps.roles.store import checked_permission_names
from oldman.auth.permissions import declared_permissions, get_permission
from oldman.i18n import gettext, gettext_lazy
from oldman.web.auth.permissions import permissions_not_held
from oldman.web.components.forms import CheckboxGroupField, FieldLayout, TailwindModelForm


def permission_choices(request: Any) -> dict[Any, list[tuple[str, Any]]]:
    """Every declared permission, grouped under the App that declares it.

    A group is named after its App's display name, or its namespace when the request's
    service has no App registry to ask. Two Apps may share a display name; the second one's
    group then carries its namespace too, so neither loses its permissions to the other.
    """
    registry = getattr(getattr(getattr(request, "app", None), "ctx", None), "app_registry", None)
    groups: dict[str, list[tuple[str, Any]]] = {}
    for permission in declared_permissions():
        groups.setdefault(permission.namespace, []).append((permission.name, permission.label))
    choices: dict[Any, list[tuple[str, Any]]] = {}
    shown: set[str] = set()
    for namespace, permissions in groups.items():
        title: Any = namespace
        if registry is not None:
            try:
                title = registry.get_by_label(namespace).display_name
            except AppNotInstalledError:
                pass
        if str(title) in shown:
            title = f"{title} ({namespace})"
        shown.add(str(title))
        choices[title] = permissions
    return choices


class RoleForm(TailwindModelForm):
    """A role's name, description and permissions; the permissions are the declared ones, grouped by App."""

    name = StringField(
        cast(str, gettext_lazy("Name")),
        validators=[DataRequired(), Length(max=150)],
        render_kw={"required": True, "maxlength": 150},
    )
    description = StringField(
        cast(str, gettext_lazy("Description")),
        validators=[Optional(), Length(max=255)],
        render_kw={"maxlength": 255},
    )
    permissions = CheckboxGroupField(cast(str, gettext_lazy("Permissions")), choices=[])

    field_layout = (
        FieldLayout("name", "md:col-span-6"),
        FieldLayout("description", "md:col-span-6"),
        FieldLayout("permissions"),
    )

    class Meta(TailwindModelForm.Meta):
        """Edit the role's own columns; its id is assigned by the database."""

        model = Role
        fields = ["name", "description", "permissions"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Offer every permission the service declares; a stored name it does not declare is kept on save (see clean_permissions)."""
        super().__init__(*args, **kwargs)
        self.permissions.choices = permission_choices(self.request)

    async def clean_name(self) -> str:
        """Names are unique; say so before the database constraint does."""
        name = str(self.name.data or "").strip()
        if self.session is None or not name:
            return name
        existing = (await self.session.execute(select(Role).where(Role.name == name))).scalar_one_or_none()
        if existing is not None and (self.instance is None or existing.id != self.instance.id):
            raise ValidationError(gettext("A role with this name already exists"))
        return name

    async def clean_permissions(self) -> list[str]:
        """Sorted without repeats. What is checked must be declared here; what this service does not declare is kept.

        Services that share the role table declare different permissions: a site without the
        Admin knows no `admin.*` name. The field offers, and a save changes, only the names this
        service declares; the role's other names stay as they were. A name no service declares
        any more is kept too - from here it cannot be told apart from another service's.
        """
        try:
            checked = checked_permission_names(self.permissions.data or [])
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        stored = self.instance.permissions if self.instance is not None else []
        # Someone who may edit roles but is no superuser adds only what they hold themselves;
        # otherwise they could widen a role they hold. Removing or keeping is not restricted.
        refused = await permissions_not_held(self.request, set(checked) - set(stored))
        if refused:
            raise ValidationError(gettext("You can only grant permissions you hold: %(permissions)s", permissions=", ".join(refused)))
        return sorted({*checked, *(name for name in stored if get_permission(name) is None)})


__all__ = ["RoleForm", "permission_choices"]
