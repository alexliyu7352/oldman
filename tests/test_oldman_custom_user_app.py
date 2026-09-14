"""App Registry selection tests for the sole concrete User mapper."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _run_project(
    files: dict[str, str],
    source: str,
) -> subprocess.CompletedProcess[str]:
    """Run one User selection because its fixed table can be mapped only once."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        for relative_path, file_source in files.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(file_source), encoding="utf-8")

        environment = os.environ.copy()
        python_path = [str(REPOSITORY_ROOT)]
        if existing_path := environment.get("PYTHONPATH"):
            python_path.append(existing_path)
        environment["PYTHONPATH"] = os.pathsep.join(python_path)
        return subprocess.run(
            [sys.executable, "-c", textwrap.dedent(source)],
            cwd=root,
            env=environment,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )


def _accounts_app() -> str:
    """Return metadata for one project App that owns User extensions."""
    return """
        from oldman.apps import AppConfig

        class AccountsConfig(AppConfig):
            label = "accounts"
            display_name = "Accounts"
            icon = "ri-user-line"

        app = AccountsConfig()
    """


class CustomUserAppTest(unittest.TestCase):
    """Keep default and custom User selection deterministic and single-mapped."""

    def test_default_auth_model_is_the_only_user_mapper(self) -> None:
        """Default Auth loads User and records both table and extension ownership."""
        completed = _run_project(
            {},
            """
            import sys

            from oldman.apps import AppRegistry
            from oldman.auth.settings import AuthSettings
            from oldman.db import Base

            registry = AppRegistry()
            registry.register_packages(("oldman.auth",))
            registry.bind_settings("auth", AuthSettings())
            registry.load_models()

            from oldman.auth.models import User

            user_models = [
                item for item in registry.models
                if item.table.name == "oldman_user"
            ]
            assert len(user_models) == 1, user_models
            assert user_models[0].model is User
            assert user_models[0].app_label == "auth"
            table = Base.metadata.tables["oldman_user"]
            assert table.info["oldman_app_label"] == "auth"
            assert table.info["oldman_user_app_label"] == "auth"
            assert table.info["oldman_user_core_fields"][0] == "id"
            assert "oldman.auth.models" in sys.modules
            """,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_custom_user_is_loaded_before_other_models_without_loading_default(self) -> None:
        """A registered project App extends oldman_user with one concrete mapper."""
        completed = _run_project(
            {
                "accounts/__init__.py": "",
                "accounts/apps.py": _accounts_app(),
                "accounts/models.py": """
                    from sqlalchemy import String
                    from sqlalchemy.orm import Mapped, mapped_column

                    from oldman.auth import AbstractUser

                    class ProjectUser(AbstractUser):
                        phone: Mapped[str | None] = mapped_column(
                            String(32),
                            index=True,
                        )
                """,
            },
            """
            import sys

            from oldman.apps import AppRegistry
            from oldman.auth import get_user_model
            from oldman.auth.settings import AuthSettings
            from oldman.db import Base

            auth_settings = AuthSettings(
                user_model="accounts.models.ProjectUser",
            )
            registry = AppRegistry()
            registry.register_packages(("oldman.auth", "accounts"))
            registry.bind_settings("auth", auth_settings)
            registry.load_models()

            from accounts.models import ProjectUser

            assert get_user_model(auth_settings) is ProjectUser
            assert "oldman.auth.models" not in sys.modules
            assert tuple(Base.metadata.tables) == ("oldman_user",)
            user_models = [
                item for item in registry.models
                if item.table.name == "oldman_user"
            ]
            assert len(user_models) == 1, user_models
            assert user_models[0].model is ProjectUser
            assert user_models[0].app_label == "accounts"
            table = Base.metadata.tables["oldman_user"]
            assert "phone" in table.c
            assert table.info["oldman_app_label"] == "auth"
            assert table.info["oldman_user_app_label"] == "accounts"
            assert "phone" not in table.info["oldman_user_core_fields"]
            """,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_custom_user_model_must_belong_to_an_installed_app(self) -> None:
        """A model path cannot silently import an App absent from settings.apps."""
        completed = _run_project(
            {
                "accounts/__init__.py": "",
                "accounts/apps.py": _accounts_app(),
                "accounts/models.py": """
                    from oldman.auth import AbstractUser

                    class ProjectUser(AbstractUser):
                        pass
                """,
            },
            """
            from oldman.apps import AppNotInstalledError, AppRegistry
            from oldman.auth.settings import AuthSettings

            registry = AppRegistry()
            registry.register_packages(("oldman.auth",))
            registry.bind_settings(
                "auth",
                AuthSettings(user_model="accounts.models.ProjectUser"),
            )
            try:
                registry.load_models()
            except AppNotInstalledError as exc:
                assert "accounts.models.ProjectUser" in str(exc), str(exc)
                assert "settings.apps" in str(exc), str(exc)
            else:
                raise AssertionError("an uninstalled custom User App was imported")
            """,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_package_root_cannot_import_the_default_user_early(self) -> None:
        """Early package imports fail clearly before a second User can be selected."""
        completed = _run_project(
            {
                "accounts/__init__.py": "from oldman.auth.models import User\n",
                "accounts/apps.py": _accounts_app(),
            },
            """
            from oldman.apps import AppRegistry
            from oldman.db import Base

            registry = AppRegistry()
            try:
                registry.register_packages(("oldman.auth", "accounts"))
            except RuntimeError as exc:
                assert "before the Registry model phase" in str(exc), str(exc)
                assert tuple(Base.metadata.tables) == ("oldman_user",)
            else:
                raise AssertionError("package-root model import was accepted")
            """,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
