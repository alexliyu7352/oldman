"""Persistent notification migration generation and replay contracts."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AUTH_REVISION = "b7c396a46832"
NOTIFICATIONS_REVISION = "4858aab957ee"


def _run_notification_scenario(source: str) -> subprocess.CompletedProcess[str]:
    """Run one migration replay in a fresh interpreter and SQLite database."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        environment = os.environ.copy()
        python_paths = [str(REPOSITORY_ROOT)]
        if existing_path := environment.get("PYTHONPATH"):
            python_paths.append(existing_path)
        environment["PYTHONPATH"] = os.pathsep.join(python_paths)
        environment["OLDMAN_NOTIFICATIONS_TEST_DATABASE"] = str(
            Path(temporary_directory) / "notification-migration.db"
        )
        return subprocess.run(
            [sys.executable, "-c", textwrap.dedent(source)],
            cwd=REPOSITORY_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )


class NotificationMigrationTest(unittest.TestCase):
    """Replay the independent notifications branch through Oldman's wrapper."""

    def test_upgrade_downgrade_and_reupgrade_preserve_notification_contract(
        self,
    ) -> None:
        """The generated branch must create, own and remove only its table."""
        completed = _run_notification_scenario(
            f"""
            import os
            from pathlib import Path
            from uuid import UUID

            from sqlalchemy import create_engine, inspect

            from oldman.apps import AppRegistry
            from oldman.auth.settings import AuthSettings
            from oldman.db.migrations import MigrationProject
            from oldman.db.migrations.alembic import load_migration_graph
            from oldman.db.migrations.commands import downgrade, migrate
            from oldman.db.migrations.state import MigrationState

            database_path = Path(os.environ["OLDMAN_NOTIFICATIONS_TEST_DATABASE"])
            registry = AppRegistry()
            registry.register_packages((
                "oldman.web.messages.notifications",
                "oldman.auth",
            ))
            registry.bind_settings(
                "auth",
                AuthSettings(user_model="oldman.auth.models.User"),
            )
            project = MigrationProject(
                project_root=Path.cwd(),
                project_id=UUID("9714d0a3-3f2b-48aa-88d7-c0869b2a6f25"),
                project_name="oldman-notifications-test",
                database_url=f"sqlite+aiosqlite:///{{database_path}}",
                service_configs=(),
                apps=registry,
                user_model_path="oldman.auth.models.User",
            )

            graph = load_migration_graph(project)
            auth_revision = graph.branches["auth"].revisions[0]
            notification_revision = graph.branches["notifications"].revisions[0]
            assert auth_revision.revision == {AUTH_REVISION!r}
            assert notification_revision.revision == {NOTIFICATIONS_REVISION!r}
            assert notification_revision.down_revision is None
            assert tuple(notification_revision.branch_labels) == ("notifications",)
            assert notification_revision.dependencies == {AUTH_REVISION!r}
            assert tuple(item.revision for item in graph.heads) == ({NOTIFICATIONS_REVISION!r},)

            class FirstMigrateAnswers:
                is_interactive = False

                def choose(self, prompt, choices):
                    assert "internal migration state" in prompt, prompt
                    assert choices == ("first use", "state lost", "cancel")
                    return "first use"

                def confirm(self, prompt, *, default=False):
                    raise AssertionError(prompt)

                def text(self, prompt, *, default):
                    raise AssertionError(prompt)

            first_result = migrate(project, FirstMigrateAnswers())
            assert first_result.applied_revisions == (
                {AUTH_REVISION!r},
                {NOTIFICATIONS_REVISION!r},
            ), first_result

            engine = create_engine(f"sqlite:///{{database_path}}")
            inspector = inspect(engine)
            assert "oldman_user" in inspector.get_table_names()
            assert "oldman_notification" in inspector.get_table_names()
            columns = {{
                item["name"]: item
                for item in inspector.get_columns("oldman_notification")
            }}
            assert tuple(columns) == (
                "id",
                "recipient_id",
                "payload",
                "created_at",
                "read_at",
            )
            assert str(columns["payload"]["type"]).upper() == "BLOB"
            assert inspector.get_pk_constraint("oldman_notification")[
                "constrained_columns"
            ] == ["id"]
            foreign_keys = inspector.get_foreign_keys("oldman_notification")
            assert len(foreign_keys) == 1
            foreign_key = foreign_keys[0]
            assert foreign_key["constrained_columns"] == ["recipient_id"]
            assert foreign_key["referred_table"] == "oldman_user"
            assert foreign_key["referred_columns"] == ["id"]
            assert foreign_key["options"].get("ondelete") == "CASCADE"
            indexes = {{
                item["name"]: tuple(item["column_names"])
                for item in inspector.get_indexes("oldman_notification")
            }}
            assert indexes == {{
                "ix_oldman_notification_recipient_created": (
                    "recipient_id",
                    "created_at",
                    "id",
                ),
                "ix_oldman_notification_recipient_read_created": (
                    "recipient_id",
                    "read_at",
                    "created_at",
                    "id",
                ),
            }}
            with engine.connect() as connection:
                state = MigrationState.inspect(connection)
            ownership = state.schema_registry["oldman_notification"]
            assert ownership.app_label == "notifications"
            assert ownership.managed is True
            assert ownership.ownership_revision == {NOTIFICATIONS_REVISION!r}
            assert graph.revision_closure(state.revisions) == frozenset((
                {AUTH_REVISION!r},
                {NOTIFICATIONS_REVISION!r},
            ))

            class DowngradeAnswers:
                entered = iter(("notifications", "base"))

                def choose(self, prompt, choices):
                    if "applied App" in prompt:
                        assert "notifications" in choices
                        return "notifications"
                    assert "target revision" in prompt, prompt
                    assert choices == ("base",)
                    return "base"

                def confirm(self, prompt, *, default=False):
                    raise AssertionError(prompt)

                def text(self, prompt, *, default):
                    raise AssertionError(prompt)

                def enter(self, prompt):
                    return next(self.entered)

            downgraded = downgrade(project, DowngradeAnswers())
            assert downgraded is not None
            assert downgraded.app_label == "notifications"
            assert downgraded.target_revision == "base"
            assert downgraded.removed_revisions == ({NOTIFICATIONS_REVISION!r},)

            inspector = inspect(engine)
            assert "oldman_notification" not in inspector.get_table_names()
            assert "oldman_user" in inspector.get_table_names()
            with engine.connect() as connection:
                state = MigrationState.inspect(connection)
            assert state.revisions == ({AUTH_REVISION!r},)
            assert "oldman_notification" not in state.schema_registry
            assert state.schema_registry["oldman_user"].app_label == "auth"

            class RepeatMigrateAnswers:
                is_interactive = False

                def choose(self, prompt, choices):
                    raise AssertionError((prompt, choices))

                def confirm(self, prompt, *, default=False):
                    raise AssertionError(prompt)

                def text(self, prompt, *, default):
                    raise AssertionError(prompt)

            repeated = migrate(project, RepeatMigrateAnswers())
            assert repeated.applied_revisions == ({NOTIFICATIONS_REVISION!r},)
            inspector = inspect(engine)
            assert "oldman_notification" in inspector.get_table_names()
            with engine.connect() as connection:
                state = MigrationState.inspect(connection)
            assert graph.revision_closure(state.revisions) == frozenset((
                {AUTH_REVISION!r},
                {NOTIFICATIONS_REVISION!r},
            ))
            assert state.schema_registry[
                "oldman_notification"
            ].ownership_revision == {NOTIFICATIONS_REVISION!r}
            engine.dispose()
            """
        )

        self.assertEqual(
            0,
            completed.returncode,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
