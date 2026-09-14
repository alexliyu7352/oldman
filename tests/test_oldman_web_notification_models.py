"""Persistent notification App, payload and ORM contracts."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import msgspec
from sqlalchemy import LargeBinary, Table
from sqlalchemy.dialects import mysql, postgresql, sqlite

from oldman.auth.models import User
from oldman.conf.schemas import DatabaseConfig
from oldman.db import Base, DatabaseManager, resolve_model_display_names
from oldman.i18n import LazyTranslation, gettext_lazy, ngettext_lazy
from oldman.web.messages import MessageFormat, MessageLevel
from oldman.web.messages.notifications import (
    NotificationCreatedPayload,
    NotificationPayload,
    NotificationPresentation,
    NotificationPushPayload,
    NotificationState,
    NotificationSyncPayload,
)
from oldman.web.messages.notifications.apps import app as notifications_app
from oldman.web.messages.notifications.models import Notification

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _run_isolated(source: str) -> subprocess.CompletedProcess[str]:
    """Run import-sensitive Registry checks in a fresh interpreter."""
    environment = os.environ.copy()
    existing_path = environment.get("PYTHONPATH")
    paths = [str(REPOSITORY_ROOT)]
    if existing_path:
        paths.append(existing_path)
    environment["PYTHONPATH"] = os.pathsep.join(paths)
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )


def _notification_payload() -> NotificationPayload:
    """Build one payload containing singular, plural and variable state."""
    return NotificationPayload(
        title=gettext_lazy("Imported %(count)s records", count=3),
        body=ngettext_lazy("One warning", "%(num)s warnings", 2),
        level=MessageLevel.SUCCESS,
        format=MessageFormat.HTML,
        presentation=NotificationPresentation.TOAST,
        href="/imports/42",
        icon="ri-check-line",
    )


class NotificationAppAndPayloadTest(unittest.TestCase):
    """Protect lazy model loading and strong notification wire values."""

    def test_app_metadata_imports_models_only_during_registry_model_stage(self) -> None:
        """The public package and apps.py must not register ORM state early."""
        completed = _run_isolated(
            """
            import sys

            import oldman.web.messages.notifications
            import oldman.web.messages.notifications.apps

            from oldman.apps import AppRegistry

            assert "oldman.web.messages.notifications.models" not in sys.modules

            registry = AppRegistry()
            registry.register_packages((
                "oldman.auth",
                "oldman.web.messages.notifications",
            ))
            assert "oldman.web.messages.notifications.models" not in sys.modules

            registry.load_models(user_model_path="oldman.auth.models.User")
            assert "oldman.web.messages.notifications.models" in sys.modules

            from oldman.web.messages.notifications.models import Notification

            metadata = registry.get_model_metadata(Notification)
            assert metadata.app_label == "notifications"
            """
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual("notifications", notifications_app.label)
        self.assertEqual("ri-notification-3-line", notifications_app.icon)

    def test_model_schema_uses_real_user_foreign_key_and_binary_payload(self) -> None:
        """The table must contain only the frozen fields, indexes and cascade."""
        table = cast(Table, Notification.__table__)

        self.assertEqual("oldman_notification", Notification.__tablename__)
        self.assertEqual(
            ["id", "recipient_id", "payload", "created_at", "read_at"],
            list(table.c.keys()),
        )
        foreign_key = next(iter(table.foreign_keys))
        self.assertEqual("oldman_user.id", foreign_key.target_fullname)
        self.assertEqual("CASCADE", foreign_key.ondelete)
        self.assertIsInstance(table.c.payload.type, LargeBinary)
        payload_type = cast(LargeBinary, table.c.payload.type)
        self.assertEqual(32 * 1024, payload_type.length)
        self.assertEqual(
            {
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
            },
            {
                index.name: tuple(column.name for column in index.columns)
                for index in table.indexes
            },
        )
        singular, plural = resolve_model_display_names(Notification)
        self.assertEqual("Notification", cast(LazyTranslation, singular).singular)
        self.assertEqual("Notifications", cast(LazyTranslation, plural).singular)

    def test_payload_column_compiles_for_supported_database_dialects(self) -> None:
        """Every supported backend must retain a native binary column."""
        table = cast(Table, Notification.__table__)
        payload_type = table.c.payload.type

        self.assertEqual("BLOB", payload_type.compile(dialect=sqlite.dialect()))
        self.assertIn("BLOB", payload_type.compile(dialect=mysql.dialect()).upper())
        self.assertEqual("BYTEA", payload_type.compile(dialect=postgresql.dialect()))

    def test_payload_msgpack_round_trip_preserves_translation_and_enums(self) -> None:
        """Stored bytes must retain untranslated source data and strong enums."""
        payload = _notification_payload()

        decoded = NotificationPayload.from_msgpack(payload.to_msgpack())

        self.assertIsInstance(decoded.title, LazyTranslation)
        self.assertEqual("Imported %(count)s records", decoded.title.singular)
        self.assertEqual({"count": 3}, decoded.title.variables)
        assert decoded.body is not None
        self.assertEqual(
            ("One warning", "%(num)s warnings", 2),
            (decoded.body.singular, decoded.body.plural, decoded.body.n),
        )
        self.assertIs(decoded.level, MessageLevel.SUCCESS)
        self.assertIs(decoded.format, MessageFormat.HTML)
        self.assertIs(decoded.presentation, NotificationPresentation.TOAST)
        self.assertEqual("/imports/42", decoded.href)
        self.assertEqual("ri-check-line", decoded.icon)

        created_at = datetime.now(UTC)
        event = NotificationCreatedPayload(
            notification_id=7,
            notification=payload,
            created_at=created_at,
        )
        decoded_event = NotificationCreatedPayload.from_msgpack(event.to_msgpack())
        self.assertEqual(7, decoded_event.notification_id)
        self.assertEqual(created_at, decoded_event.created_at)
        self.assertIsInstance(decoded_event.notification.title, LazyTranslation)

    def test_direct_construction_rejects_invalid_payload_contracts(self) -> None:
        """Loose msgspec constructors must not bypass the frozen wire contract."""
        title = gettext_lazy("Title")
        invalid_notification_fields: tuple[dict[str, Any], ...] = (
            {"version": True},
            {"version": 2},
            {"level": "info"},
            {"format": "text"},
            {"presentation": "none"},
        )
        for fields in invalid_notification_fields:
            with self.subTest(fields=fields), self.assertRaises(TypeError):
                NotificationPayload(title=title, **fields)  # pyright: ignore[reportArgumentType] -- exercise runtime validation

        payload = _notification_payload()
        invalid_created_fields: tuple[dict[str, Any], ...] = (
            {"notification_id": True},
            {"notification_id": 0},
            {"notification": object()},
            {"created_at": datetime.now()},
        )
        for fields in invalid_created_fields:
            values: dict[str, Any] = {
                "notification_id": 1,
                "notification": payload,
                "created_at": datetime.now(UTC),
            }
            values.update(fields)
            with self.subTest(fields=fields), self.assertRaises(TypeError):
                NotificationCreatedPayload(**values)  # pyright: ignore[reportArgumentType] -- exercise runtime validation

        with self.assertRaises(TypeError):
            NotificationPushPayload(notification=object())  # pyright: ignore[reportArgumentType] -- exercise runtime validation
        for changed_count in (True, -1):
            with self.subTest(changed_count=changed_count), self.assertRaises(TypeError):
                NotificationSyncPayload(changed_count=changed_count)  # pyright: ignore[reportArgumentType] -- exercise runtime validation

        self.assertEqual(0, NotificationSyncPayload(changed_count=0).changed_count)
        self.assertEqual("unread", NotificationState.UNREAD)

    def test_corrupt_binary_is_rejected_by_typed_decoder(self) -> None:
        """Malformed storage must fail instead of producing a partial payload."""
        with self.assertRaises(msgspec.DecodeError):
            NotificationPayload.from_msgpack(b"\xc1")


class NotificationDatabaseCodecTest(unittest.IsolatedAsyncioTestCase):
    """Exercise raw notification bytes through the real SQLite manager."""

    async def asyncSetUp(self) -> None:
        """Create only the User and Notification tables in a temporary database."""
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "notifications.sqlite3"
        self.manager = DatabaseManager(
            DatabaseConfig(
                url=f"sqlite+aiosqlite:///{database_path.as_posix()}",
                echo=False,
            )
        )
        await self.manager.initialize()
        engine = self.manager.engine
        assert engine is not None
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: Base.metadata.create_all(
                    sync_connection,
                    tables=[
                        cast(Table, User.__table__),
                        cast(Table, Notification.__table__),
                    ],
                )
            )

    async def asyncTearDown(self) -> None:
        """Dispose the engine before deleting its SQLite file."""
        await self.manager.close()
        self.temporary_directory.cleanup()

    async def test_sqlite_writes_and_reads_msgpack_bytes_without_text_conversion(
        self,
    ) -> None:
        """The ORM column must preserve MessagePack bytes byte-for-byte."""
        encoded = _notification_payload().to_msgpack()
        async with self.manager.get_session() as session:
            user = User(username="recipient", password_hash="not-used")
            session.add(user)
            await session.flush()
            row = Notification(recipient_id=user.id, payload=encoded)
            session.add(row)
            await session.flush()
            notification_id = row.id

        async with self.manager.get_read_session() as session:
            stored = await session.get(Notification, notification_id)

        assert stored is not None
        self.assertIsInstance(stored.payload, bytes)
        self.assertEqual(encoded, stored.payload)
        decoded = NotificationPayload.from_msgpack(stored.payload)
        self.assertEqual("Imported %(count)s records", decoded.title.singular)


if __name__ == "__main__":
    unittest.main()
