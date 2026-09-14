"""Behavior tests for App-owned CLI command discovery."""

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
    """Run one isolated Registry command-discovery scenario."""
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


def _app(label: str) -> str:
    """Return minimal App metadata for a command fixture."""
    return f"""
        from oldman.apps import AppConfig

        class Config(AppConfig):
            label = {label!r}
            display_name = {label.title()!r}

        app = Config()
    """


class AppCommandLoadingTests(unittest.TestCase):
    """Protect precise, typed and App-owned command discovery."""

    def test_loads_public_async_commands_after_models_without_views(self) -> None:
        completed = _run_project(
            {
                "reports/__init__.py": "",
                "reports/apps.py": _app("reports"),
                "reports/models.py": "MODEL_READY = True\n",
                "reports/commands.py": """
                    import inspect

                    from oldman.cli import Command
                    from oldman.i18n import gettext_lazy as _
                    from reports.models import MODEL_READY

                    assert MODEL_READY

                    class ImportUsers(Command):
                        name = "import-users"
                        help = _("Import users.")

                        async def handle(self, source: str, dry_run: bool = False) -> None:
                            assert source

                    class RebuildIndex(Command):
                        name = "rebuild-index"
                        help = "Rebuild the report index."

                        async def handle(self) -> str:
                            return "done"

                    class _PrivateCommand(Command):
                        name = "private"
                        help = "Private."

                        async def handle(self) -> None:
                            return None

                    assert inspect.iscoroutinefunction(ImportUsers.handle)
                """,
                "reports/views.py": 'raise RuntimeError("views were imported")\n',
                "empty/__init__.py": "",
                "empty/apps.py": _app("empty"),
            },
            """
            from oldman.apps import AppRegistry

            registry = AppRegistry()
            registry.register_packages(("reports", "empty"))

            try:
                registry.load_commands()
            except RuntimeError as exc:
                assert "models" in str(exc).lower(), str(exc)
            else:
                raise AssertionError("commands loaded before models")

            registry.load_models()
            registry.load_commands()
            registry.load_commands()

            assert [command.name for command in registry.commands] == [
                "import-users",
                "rebuild-index",
            ]
            assert [command.name for command in registry.get_app_commands("reports")] == [
                "import-users",
                "rebuild-index",
            ]
            assert registry.get_app_commands("empty") == ()
            assert registry.get_command("rebuild-index").help == "Rebuild the report index."
            assert "reports.views" not in __import__("sys").modules
            """,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_rejects_invalid_metadata_and_synchronous_handle(self) -> None:
        cases = {
            "invalid_name": ('name = "Import_users"', 'help = "Import users."', "async def handle(self): pass", "name"),
            "empty_help": ('name = "import-users"', 'help = "  "', "async def handle(self): pass", "help"),
            "sync_handle": ('name = "import-users"', 'help = "Import users."', "def handle(self): pass", "async"),
            "raw_stdout": (
                'name = "import-users"; raw_stdout = "yes"',
                'help = "Import users."',
                "async def handle(self): pass",
                "raw_stdout",
            ),
        }
        for package, (name, help_text, handle, expected) in cases.items():
            with self.subTest(package=package):
                completed = _run_project(
                    {
                        f"{package}/__init__.py": "",
                        f"{package}/apps.py": _app(package),
                        f"{package}/commands.py": f"""
                            from oldman.cli import Command

                            class InvalidCommand(Command):
                                {name}
                                {help_text}
                                {handle}
                        """,
                    },
                    f"""
                    from oldman.apps import AppRegistry

                    registry = AppRegistry()
                    registry.register_packages(({package!r},))
                    registry.load_models()
                    try:
                        registry.load_commands()
                    except (TypeError, ValueError) as exc:
                        assert {expected!r} in str(exc).lower(), str(exc)
                        assert {package!r} in str(exc), str(exc)
                    else:
                        raise AssertionError("invalid command was accepted")
                    """,
                )
                self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_rejects_duplicate_names_and_duplicate_public_class_aliases(self) -> None:
        completed = _run_project(
            {
                "first/__init__.py": "",
                "first/apps.py": _app("first"),
                "first/commands.py": """
                    from oldman.cli import Command

                    class Refresh(Command):
                        name = "refresh"
                        help = "Refresh first."

                        async def handle(self):
                            return None
                """,
                "second/__init__.py": "",
                "second/apps.py": _app("second"),
                "second/commands.py": """
                    from oldman.cli import Command

                    class RefreshAgain(Command):
                        name = "refresh"
                        help = "Refresh second."

                        async def handle(self):
                            return None
                """,
            },
            """
            from oldman.apps import AppRegistry

            registry = AppRegistry()
            registry.register_packages(("first", "second"))
            registry.load_models()
            try:
                registry.load_commands()
            except ValueError as exc:
                message = str(exc)
                assert "refresh" in message, message
                assert "first" in message, message
                assert "second" in message, message
            else:
                raise AssertionError("duplicate command name was accepted")
            """,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

        completed = _run_project(
            {
                "aliased/__init__.py": "",
                "aliased/apps.py": _app("aliased"),
                "aliased/commands.py": """
                    from oldman.cli import Command

                    class Refresh(Command):
                        name = "refresh"
                        help = "Refresh."

                        async def handle(self):
                            return None

                    RefreshAlias = Refresh
                """,
            },
            """
            from oldman.apps import AppRegistry

            registry = AppRegistry()
            registry.register_packages(("aliased",))
            registry.load_models()
            try:
                registry.load_commands()
            except ValueError as exc:
                message = str(exc)
                assert "aliased" in message, message
                assert "Refresh" in message, message
                assert "RefreshAlias" in message, message
            else:
                raise AssertionError("duplicate public class alias was accepted")
            """,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_preserves_an_existing_command_module_import_error(self) -> None:
        completed = _run_project(
            {
                "broken/__init__.py": "",
                "broken/apps.py": _app("broken"),
                "broken/commands.py": "import missing_command_dependency\n",
            },
            """
            from oldman.apps import AppRegistry

            registry = AppRegistry()
            registry.register_packages(("broken",))
            registry.load_models()
            try:
                registry.load_commands()
            except ModuleNotFoundError as exc:
                assert exc.name == "missing_command_dependency", exc
            else:
                raise AssertionError("command import error was hidden")
            """,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
