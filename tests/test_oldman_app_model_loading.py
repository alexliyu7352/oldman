"""Exact App model imports and deterministic table ownership."""

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
    """Run one mapper-affecting model load in a fresh interpreter."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        for relative_path, file_source in files.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(file_source), encoding="utf-8")

        environment = os.environ.copy()
        existing_path = environment.get("PYTHONPATH")
        paths = [str(REPOSITORY_ROOT)]
        if existing_path:
            paths.append(existing_path)
        environment["PYTHONPATH"] = os.pathsep.join(paths)
        return subprocess.run(
            [sys.executable, "-c", textwrap.dedent(source)],
            cwd=root,
            env=environment,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )


def _app(
    label: str,
    *,
    models_module: str = "models",
    web_module: str = "views",
) -> str:
    """Return minimal App metadata without importing model code."""
    return f"""
        from oldman.apps import AppConfig

        class FixtureConfig(AppConfig):
            label = {label!r}
            display_name = {label.title()!r}
            models_module = {models_module!r}
            web_module = {web_module!r}

        app = FixtureConfig()
    """


class AppModelLoadingTest(unittest.TestCase):
    """Protect precise imports and ownership independent of import order."""

    def test_models_use_their_real_definition_module_and_tables_use_identity(self) -> None:
        completed = _run_project(
            {
                "alpha/__init__.py": "",
                "alpha/apps.py": _app("alpha"),
                "alpha/models.py": """
                    from sqlalchemy import Column, ForeignKey, Integer, Table
                    from sqlalchemy.orm import Mapped, mapped_column

                    from oldman.db import Base, DatabaseModel

                    alpha_tags = Table(
                        "alpha_tags",
                        Base.metadata,
                        Column("alpha_id", ForeignKey("alpha.id"), primary_key=True),
                        Column("tag_id", Integer, primary_key=True),
                    )

                    class Alpha(DatabaseModel):
                        __tablename__ = "alpha"

                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
                "alpha/views.py": 'raise RuntimeError("views were imported")\n',
                "beta/__init__.py": "",
                "beta/apps.py": _app("beta"),
                "beta/models.py": """
                    from sqlalchemy import ForeignKey
                    from sqlalchemy.orm import Mapped, mapped_column

                    from alpha.models import Alpha
                    from oldman.db import DatabaseModel

                    class Beta(DatabaseModel):
                        __tablename__ = "beta"

                        id: Mapped[int] = mapped_column(primary_key=True)
                        alpha_id: Mapped[int] = mapped_column(ForeignKey("alpha.id"))
                """,
                "beta/views.py": 'raise RuntimeError("views were imported")\n',
            },
            """
            import sys

            from oldman.apps import AppRegistry
            from oldman.db import Base

            registry = AppRegistry()
            registry.register_packages(("beta", "alpha"))
            registry.load_models()
            registry.load_models()

            from alpha.models import Alpha

            assert Base.metadata.tables["alpha"].info["oldman_app_label"] == "alpha"
            assert Base.metadata.tables["alpha_tags"].info["oldman_app_label"] == "alpha"
            assert Base.metadata.tables["beta"].info["oldman_app_label"] == "beta"
            assert "alpha.models" in sys.modules
            assert "beta.models" in sys.modules
            assert "alpha.views" not in sys.modules
            assert "beta.views" not in sys.modules
            assert registry.get_model_metadata(Alpha).app_label == "alpha"
            """,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_missing_default_models_module_is_skipped(self) -> None:
        completed = _run_project(
            {
                "empty_app/__init__.py": "",
                "empty_app/apps.py": _app("empty_app"),
            },
            """
            from oldman.apps import AppRegistry

            registry = AppRegistry()
            registry.register_packages(("empty_app",))
            registry.load_models()
            registry.load_views()
            """,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_package_modules_load_all_models_before_any_views(self) -> None:
        completed = _run_project(
            {
                "alpha/__init__.py": "",
                "alpha/apps.py": _app("alpha"),
                "alpha/models/__init__.py": "from alpha.models.record import Alpha\n",
                "alpha/models/record.py": """
                    import builtins

                    from sqlalchemy.orm import Mapped, mapped_column

                    from oldman.db import DatabaseModel

                    builtins.app_stage_events.append("alpha:model")

                    class Alpha(DatabaseModel):
                        __tablename__ = "stage_alpha"

                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
                "alpha/views/__init__.py": "from alpha.views.routes import VIEW_LOADED\n",
                "alpha/views/routes.py": """
                    import builtins

                    assert "beta:model" in builtins.app_stage_events
                    builtins.app_stage_events.append("alpha:view")
                    VIEW_LOADED = True
                """,
                "beta/__init__.py": "",
                "beta/apps.py": _app("beta"),
                "beta/models.py": """
                    import builtins

                    from sqlalchemy.orm import Mapped, mapped_column

                    from oldman.db import DatabaseModel

                    builtins.app_stage_events.append("beta:model")

                    class Beta(DatabaseModel):
                        __tablename__ = "stage_beta"

                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
                "beta/views.py": """
                    import builtins

                    assert "alpha:model" in builtins.app_stage_events
                    builtins.app_stage_events.append("beta:view")
                """,
            },
            """
            import builtins

            from oldman.apps import AppRegistry

            builtins.app_stage_events = []
            registry = AppRegistry()
            registry.register_packages(("alpha", "beta"))

            try:
                registry.load_views()
            except RuntimeError as exc:
                assert "models" in str(exc), str(exc)
            else:
                raise AssertionError("views loaded before the model stage")

            registry.load_models()
            registry.load_views()
            registry.load_views()

            assert builtins.app_stage_events == [
                "alpha:model",
                "beta:model",
                "alpha:view",
                "beta:view",
            ]
            """,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_existing_views_module_preserves_its_internal_import_error(self) -> None:
        completed = _run_project(
            {
                "broken_views/__init__.py": "",
                "broken_views/apps.py": _app("broken_views"),
                "broken_views/views.py": "import missing_view_dependency\n",
            },
            """
            from oldman.apps import AppRegistry

            registry = AppRegistry()
            registry.register_packages(("broken_views",))
            registry.load_models()
            try:
                registry.load_views()
            except ModuleNotFoundError as exc:
                assert exc.name == "missing_view_dependency", exc
            else:
                raise AssertionError("views import error was hidden")
            """,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_views_cannot_register_new_model_state(self) -> None:
        completed = _run_project(
            {
                "bad_views/__init__.py": "",
                "bad_views/apps.py": _app("bad_views"),
                "bad_views/views.py": """
                    from sqlalchemy.orm import Mapped, mapped_column

                    from oldman.db import DatabaseModel

                    class ViewModel(DatabaseModel):
                        __tablename__ = "view_model"

                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
            },
            """
            from oldman.apps import AppRegistry

            registry = AppRegistry()
            registry.register_packages(("bad_views",))
            registry.load_models()
            try:
                registry.load_views()
            except RuntimeError as exc:
                assert "bad_views.views" in str(exc), str(exc)
                assert "model" in str(exc).lower(), str(exc)
            else:
                raise AssertionError("views registered a model")
            """,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_model_meta_is_retained_and_unmanaged_tables_are_not_created(self) -> None:
        completed = _run_project(
            {
                "inventory/__init__.py": "",
                "inventory/apps.py": _app("inventory"),
                "inventory/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column

                    from oldman.db import DatabaseModel
                    from oldman.i18n import gettext_lazy as _

                    class AuditEntry(DatabaseModel):
                        __tablename__ = "audit_entry"

                        id: Mapped[int] = mapped_column(primary_key=True)

                    class ExternalServer(DatabaseModel):
                        __tablename__ = "external_server"

                        id: Mapped[int] = mapped_column(primary_key=True)

                        class Meta:
                            verbose_name = _("Server")
                            verbose_name_plural = _("Servers")
                            managed = False
                """,
            },
            """
            import asyncio
            import sqlite3
            from pathlib import Path

            from oldman.apps import AppRegistry
            from oldman.conf.schemas import DatabaseConfig
            from oldman.db import DatabaseManager
            from oldman.i18n import bind_translations, reset_translations

            class FailingCatalog:
                def gettext(self, message):
                    raise AssertionError(message)

                def ngettext(self, singular, plural, n):
                    raise AssertionError(singular)

                def pgettext(self, context, message):
                    raise AssertionError(message)

            registry = AppRegistry()
            registry.register_packages(("inventory",))
            token = bind_translations(FailingCatalog())
            try:
                registry.load_models()
            finally:
                reset_translations(token)

            metadata = {item.model.__name__: item for item in registry.models}
            audit = metadata["AuditEntry"]
            external = metadata["ExternalServer"]
            assert audit.verbose_name == "Audit Entry"
            assert audit.verbose_name_plural == "Audit Entrys"
            assert audit.managed is True
            assert external.verbose_name.singular == "Server"
            assert external.verbose_name_plural.singular == "Servers"
            assert external.managed is False
            assert external.table.info["oldman_managed"] is False

            database_path = Path.cwd() / "models.sqlite3"
            manager = DatabaseManager(
                DatabaseConfig(
                    url=f"sqlite+aiosqlite:///{database_path}",
                    echo=False,
                )
            )

            async def create_tables():
                await manager.create_db_and_tables()
                await manager.close()

            asyncio.run(create_tables())
            with sqlite3.connect(database_path) as connection:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            assert "audit_entry" in table_names
            assert "external_server" not in table_names
            """,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_error_inside_existing_models_module_is_not_hidden(self) -> None:
        completed = _run_project(
            {
                "broken_app/__init__.py": "",
                "broken_app/apps.py": _app("broken_app"),
                "broken_app/models.py": "import missing_model_dependency\n",
            },
            """
            from oldman.apps import AppRegistry

            registry = AppRegistry()
            registry.register_packages(("broken_app",))
            try:
                registry.load_models()
            except ModuleNotFoundError as exc:
                assert exc.name == "missing_model_dependency", exc
            else:
                raise AssertionError("models import error was hidden")
            """,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_mapper_defined_outside_registered_apps_is_rejected(self) -> None:
        completed = _run_project(
            {
                "reports/__init__.py": "",
                "reports/apps.py": _app("reports"),
                "reports/models.py": "from external_models import ExternalModel\n",
                "external_models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column

                    from oldman.db import DatabaseModel

                    class ExternalModel(DatabaseModel):
                        __tablename__ = "external_model"

                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
            },
            """
            from oldman.apps import AppRegistry

            registry = AppRegistry()
            registry.register_packages(("reports",))
            try:
                registry.load_models()
            except RuntimeError as exc:
                assert "external_models.ExternalModel" in str(exc), str(exc)
                assert "registered App" in str(exc), str(exc)
            else:
                raise AssertionError("unowned mapper was accepted")
            """,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_standalone_table_reexported_by_two_apps_is_rejected(self) -> None:
        completed = _run_project(
            {
                "alpha/__init__.py": "",
                "alpha/apps.py": _app("alpha"),
                "alpha/models.py": """
                    from sqlalchemy import Column, Integer, Table

                    from oldman.db import Base

                    shared_table = Table(
                        "shared_table",
                        Base.metadata,
                        Column("id", Integer, primary_key=True),
                    )
                """,
                "beta/__init__.py": "",
                "beta/apps.py": _app("beta"),
                "beta/models.py": "from alpha.models import shared_table\n",
            },
            """
            from oldman.apps import AppRegistry

            registry = AppRegistry()
            registry.register_packages(("alpha", "beta"))
            try:
                registry.load_models()
            except RuntimeError as exc:
                assert "shared_table" in str(exc), str(exc)
                assert "alpha" in str(exc) and "beta" in str(exc), str(exc)
            else:
                raise AssertionError("ambiguous standalone Table was accepted")
            """,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
