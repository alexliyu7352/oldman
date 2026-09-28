"""Permission declarations: named in code, checked at startup against the installed Apps."""

from __future__ import annotations

import unittest

from oldman.auth import Permission, PermissionSet, declare_permission, declared_permissions, get_permission
from tests.test_oldman_app_registry import _run_python, _temporary_packages


class PermissionDeclarationTest(unittest.TestCase):
    def test_a_set_names_each_permission_after_its_namespace_and_attribute(self) -> None:
        class Reports(PermissionSet, namespace="perm_reports"):
            view = Permission("View reports")
            export = Permission("Export reports")

        self.assertEqual("perm_reports.view", Reports.view.name)
        self.assertEqual("Export reports", Reports.export.label)
        self.assertIs(Reports.export, get_permission("perm_reports.export"))
        names = [permission.name for permission in declared_permissions()]
        self.assertEqual(sorted(names), names)
        self.assertIn("perm_reports.view", names)

    def test_code_that_builds_permissions_declares_them_by_name(self) -> None:
        permission = declare_permission("perm_admin", "project.change", "Change projects")
        self.assertEqual("perm_admin.project.change", permission.name)
        self.assertIs(permission, get_permission("perm_admin.project.change"))

    def test_a_name_is_declared_once(self) -> None:
        declare_permission("perm_twice", "view", "View")
        with self.assertRaisesRegex(ValueError, "declared twice"):

            class Again(PermissionSet, namespace="perm_twice"):
                view = Permission("View again")

    def test_one_permission_object_belongs_to_one_set(self) -> None:
        shared = Permission("Shared")

        class First(PermissionSet, namespace="perm_first"):
            item = shared

        with self.assertRaisesRegex(ValueError, "already declared"):

            class Second(PermissionSet, namespace="perm_second"):
                item = shared

    def test_names_must_look_like_app_labels_and_codenames(self) -> None:
        for namespace, codename in (("Reports", "view"), ("perm-x", "view"), ("perm_ok", "View"), ("perm_ok", "a..b"), ("perm_ok", "")):
            with self.subTest(namespace=namespace, codename=codename), self.assertRaises(ValueError):
                declare_permission(namespace, codename, "Label")
        self.assertIsNone(get_permission("Reports.view"))

    def test_an_undeclared_permission_has_no_name(self) -> None:
        self.assertEqual("", Permission("Loose").name)


class PermissionLoadingTest(unittest.TestCase):
    """The registry imports each App's permissions module after models and checks the namespaces."""

    def test_permissions_load_after_models_and_every_namespace_is_an_installed_app(self) -> None:
        with _temporary_packages(
            {
                "perm_app/__init__.py": "",
                "perm_app/apps.py": """
                    from oldman.apps import AppConfig
                    class Config(AppConfig):
                        label = "perm_app"
                        display_name = "Permission app"
                    app = Config()
                """,
                "perm_app/permissions.py": """
                    from oldman.auth import Permission, PermissionSet
                    class Items(PermissionSet, namespace="perm_app"):
                        view = Permission("View items")
                """,
                "stray_app/__init__.py": "",
                "stray_app/apps.py": """
                    from oldman.apps import AppConfig
                    class Config(AppConfig):
                        label = "stray_app"
                        display_name = "Stray app"
                    app = Config()
                """,
                "stray_app/permissions.py": """
                    from oldman.auth import Permission, PermissionSet
                    class Misspelt(PermissionSet, namespace="stray_ap"):
                        view = Permission("View")
                """,
            }
        ) as root:
            result = _run_python(
                root,
                """
                from oldman.apps import AppRegistry
                from oldman.auth import get_permission

                registry = AppRegistry()
                registry.register_packages(("perm_app",))
                try:
                    registry.load_permissions()
                except RuntimeError as error:
                    assert "models must be loaded" in str(error), error
                else:
                    raise AssertionError("permissions loaded before models")
                registry.load_models()
                registry.load_permissions()
                registry.load_permissions()
                assert get_permission("perm_app.view") is not None

                stray = AppRegistry()
                stray.register_packages(("stray_app",))
                stray.load_models()
                try:
                    stray.load_permissions()
                except RuntimeError as error:
                    assert "'stray_ap'" in str(error), error
                else:
                    raise AssertionError("a namespace no App carries was accepted")
                """,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_the_auth_app_declares_user_management_only_where_it_is_installed(self) -> None:
        with _temporary_packages({}) as root:
            result = _run_python(
                root,
                """
                import oldman.auth
                import oldman.web.auth
                from oldman.apps import AppRegistry
                from oldman.auth import get_permission

                # Importing the auth package declares nothing: a service without the App has no auth.* names.
                assert get_permission("auth.users.view") is None

                registry = AppRegistry()
                registry.register_packages(("oldman.auth",))
                registry.load_models(user_model_path="oldman.auth.models.User")
                registry.load_permissions()
                names = [f"auth.users.{action}" for action in ("view", "add", "change", "delete")]
                assert all(get_permission(name) is not None for name in names), names
                """,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
