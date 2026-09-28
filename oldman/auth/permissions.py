"""Permissions: the things a role can be allowed to do, declared in code by the App that checks them.

A permission exists because some code checks it, so it is declared next to that code and
ships with it; which roles hold it is data, edited at run time. Names are ``<namespace>.<codename>``
and the namespace is the declaring App's label::

    class ReportPermissions(PermissionSet, namespace="reports"):
        view = Permission(_("View reports"))
        export = Permission(_("Export reports"))

Code checks the declared object (``ReportPermissions.export``), never a string, so a
misspelling fails on import. The registry checks at startup that every namespace belongs
to an installed App.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

_NAMESPACE = re.compile(r"[a-z][a-z0-9_]*\Z")
_CODENAME = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*\Z")

_declared: dict[str, Permission] = {}


class Permission:
    """One permission. Declare it as an attribute of a PermissionSet, or through declare_permission()."""

    __slots__ = ("codename", "label", "namespace")

    def __init__(self, label: Any) -> None:
        self.label = label
        self.namespace = ""
        self.codename = ""

    @property
    def name(self) -> str:
        """The stored name, ``<namespace>.<codename>``; empty until the permission is declared."""
        return f"{self.namespace}.{self.codename}" if self.namespace else ""

    def __repr__(self) -> str:
        return f"Permission({self.name or 'undeclared'!r})"


def _register(permission: Permission, namespace: str, codename: str) -> Permission:
    if not _NAMESPACE.match(namespace):
        raise ValueError(f"permission namespace {namespace!r} must look like an App label")
    if not _CODENAME.match(codename):
        raise ValueError(f"permission codename {codename!r} must be lowercase words joined by '_' or '.'")
    if permission.namespace:
        raise ValueError(f"{permission!r} is already declared")
    name = f"{namespace}.{codename}"
    if name in _declared:
        raise ValueError(f"permission {name!r} is declared twice")
    permission.namespace = namespace
    permission.codename = codename
    _declared[name] = permission
    return permission


def declare_permission(namespace: str, codename: str, label: Any) -> Permission:
    """Declare one permission by name, for code that builds them — the Admin does, per model."""
    return _register(Permission(label), namespace, codename)


class PermissionSet:
    """A group of permissions under one namespace: each Permission attribute is declared as ``<namespace>.<attribute>``."""

    namespace: ClassVar[str] = ""

    def __init_subclass__(cls, *, namespace: str, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.namespace = namespace
        for attribute, value in list(vars(cls).items()):
            if isinstance(value, Permission):
                _register(value, namespace, attribute)


def declared_permissions() -> tuple[Permission, ...]:
    """Every declared permission, ordered by name."""
    return tuple(_declared[name] for name in sorted(_declared))


def get_permission(name: str) -> Permission | None:
    """The declared permission with this name, or None."""
    return _declared.get(name)


__all__ = ["Permission", "PermissionSet", "declare_permission", "declared_permissions", "get_permission"]
