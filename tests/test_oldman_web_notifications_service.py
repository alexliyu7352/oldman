"""Persistent notification service behavior and failure-path contracts."""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import msgspec
from sqlalchemy import Table, delete, func, select
from sqlalchemy.exc import IntegrityError

from oldman.auth.models import User
from oldman.conf.schemas import DatabaseConfig, DefaultSettings, SSEConfig
from oldman.db import Base, DatabaseManager
from oldman.i18n import LazyTranslation, gettext_lazy, ngettext_lazy
from oldman.serializers import MsgspecModel
from oldman.web.messages import MessageFormat
from oldman.web.messages.notifications import (
    NOTIFICATION_CREATED_EVENT,
    NOTIFICATION_PUSH_EVENT,
    NOTIFICATION_SYNC_EVENT,
    NotificationCreatedPayload,
    NotificationPresentation,
    NotificationPushPayload,
    NotificationState,
    NotificationSyncPayload,
)
from oldman.web.messages.notifications.models import Notification
from oldman.web.messages.notifications.payloads import NotificationPayload
from oldman.web.messages.notifications.service import Notifications
from oldman.web.sse import SSEPublisher
from oldman.web.sse.publisher import SSEMessageTooLargeError


class _InstalledApps:
    """Provide only the Registry operations consumed by the service boundary."""

    @property
    def models(self) -> tuple[object, ...]:
        """Represent a completed Registry model stage."""
        return ()

    def get_by_package(self, package: str) -> object:
        """Accept only the installed notifications package."""
        if package != "oldman.web.messages.notifications":
            raise LookupError(package)
        return object()


class _RecordingPublisher:
    """Record typed user events while returning configured transport results."""

    def __init__(self, outcomes: list[bool | BaseException] | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.calls: list[dict[str, object]] = []

    async def publish_user(
        self,
        *,
        user_id: int,
        event: str,
        payload: MsgspecModel,
    ) -> bool:
        """Record one call before returning or raising its configured outcome."""
        self.calls.append(
            {
                "user_id": user_id,
                "event": event,
                "payload": payload,
            }
        )
        outcome = self.outcomes.pop(0) if self.outcomes else True
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _UnusedRedisAlias:
    """Prove an oversized envelope fails before a Redis connection is opened."""

    async def async_get_bin_conn(self) -> object:
        """Fail if the publisher reaches transport after its size check."""
        raise AssertionError("oversized SSE envelope opened Redis")


class _PublisherRegistry:
    """Return one inert alias to a real SSEPublisher."""

    def __init__(self) -> None:
        self.alias = _UnusedRedisAlias()

    def using(self, name: str) -> _UnusedRedisAlias:
        """Resolve the sole SSE alias without opening a connection."""
        if name != "SSE":
            raise KeyError(name)
        return self.alias


def _stored_payload(title: str) -> bytes:
    """Encode one valid payload used to seed query behavior directly."""
    return NotificationPayload(title=gettext_lazy(title)).to_msgpack()


class NotificationServiceTest(unittest.IsolatedAsyncioTestCase):
    """Exercise notification persistence through the real SQLite manager."""

    async def asyncSetUp(self) -> None:
        """Create isolated User and Notification tables and bind service globals."""
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "notifications.sqlite3"
        self.manager = DatabaseManager(
            DatabaseConfig(
                url=f"sqlite+aiosqlite:///{database_path.as_posix()}",
                echo=False,
            )
        )
        await self.manager.initialize()
        async with self.manager.engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: Base.metadata.create_all(
                    sync_connection,
                    tables=[
                        cast(Table, User.__table__),
                        cast(Table, Notification.__table__),
                    ],
                )
            )

        async with self.manager.get_session() as session:
            first = User(username="first", password_hash="unused")
            second = User(username="second", password_hash="unused")
            session.add_all((first, second))
            await session.flush()
            self.first_user_id = first.id
            self.second_user_id = second.id

        self.settings = self._settings(sse_enabled=True)
        self.context = SimpleNamespace(
            apps=_InstalledApps(),
            settings=self.settings,
        )
        self.database_patch = patch(
            "oldman.web.messages.notifications.service.db_manager",
            self.manager,
        )
        self.bootstrap_patch = patch(
            "oldman.web.messages.notifications.service._get_bootstrap_context",
            side_effect=lambda: self.context,
        )
        self.database_patch.start()
        self.bootstrap_patch.start()

    async def asyncTearDown(self) -> None:
        """Restore globals and dispose SQLite before removing its directory."""
        self.bootstrap_patch.stop()
        self.database_patch.stop()
        await self.manager.close()
        self.temporary_directory.cleanup()

    def _settings(
        self,
        *,
        sse_enabled: bool,
        max_message_size: int = 65536,
    ) -> DefaultSettings:
        """Build one process settings object for the service feature switch."""
        sse = {
            "enabled": sse_enabled,
            "redis_alias": "SSE",
            "channel_prefix": "tests:notifications" if sse_enabled else "",
            "max_message_size": max_message_size,
        }
        return DefaultSettings.model_validate({"web": {"sse": sse}})

    async def _notification_count(self) -> int:
        """Count all rows without relying on the service under test."""
        async with self.manager.get_read_session() as session:
            result = await session.scalar(select(func.count()).select_from(Notification))
            return int(result or 0)

    async def test_crud_pagination_stable_order_and_recipient_isolation(self) -> None:
        """Every query and mutation must remain scoped to one integer recipient."""
        shared_time = datetime(2026, 8, 15, 12, 0, 0)
        read_time = datetime(2026, 8, 15, 12, 5, 0)
        async with self.manager.get_session() as session:
            first_rows = [
                Notification(
                    recipient_id=self.first_user_id,
                    payload=_stored_payload(f"first-{index}"),
                    created_at=shared_time,
                    read_at=read_time if index in {2, 4} else None,
                )
                for index in range(1, 6)
            ]
            second_row = Notification(
                recipient_id=self.second_user_id,
                payload=_stored_payload("second"),
                created_at=shared_time,
            )
            session.add_all((*first_rows, second_row))
            await session.flush()
            first_ids = [row.id for row in first_rows]
            second_id = second_row.id

        publisher = _RecordingPublisher()
        service = Notifications(_publisher_factory=lambda: cast(Any, publisher))

        first_page = await service.list_for_user(
            self.first_user_id,
            page=1,
            page_size=2,
        )
        second_page = await service.list_for_user(
            self.first_user_id,
            page=2,
            page_size=2,
        )
        self.assertEqual(5, first_page.total)
        self.assertEqual(list(reversed(first_ids[-2:])), [row.id for row in first_page.items])
        self.assertEqual(list(reversed(first_ids[1:3])), [row.id for row in second_page.items])

        unread = await service.list_for_user(
            self.first_user_id,
            state=NotificationState.UNREAD,
        )
        read = await service.list_for_user(
            self.first_user_id,
            state=NotificationState.READ,
        )
        self.assertEqual(3, unread.total)
        self.assertEqual(2, read.total)
        self.assertEqual(3, await service.unread_count(self.first_user_id))
        self.assertEqual(1, await service.unread_count(self.second_user_id))
        self.assertEqual(
            list(reversed([first_ids[0], first_ids[2], first_ids[4]])),
            [row.id for row in await service.topbar_for_user(self.first_user_id)],
        )
        self.assertIsNone(await service.get_for_user(self.first_user_id, second_id))
        self.assertEqual(second_id, (await service.get_for_user(self.second_user_id, second_id)).id)  # type: ignore[union-attr]

        changed = await service.mark_read(
            self.first_user_id,
            (first_ids[0], first_ids[0], first_ids[2], second_id),
        )
        self.assertEqual(2, changed)
        async with self.manager.get_read_session() as session:
            first_changed = await session.get(Notification, first_ids[0])
            second_changed = await session.get(Notification, first_ids[2])
            other_user = await session.get(Notification, second_id)
        assert first_changed is not None and second_changed is not None
        self.assertEqual(first_changed.read_at, second_changed.read_at)
        assert first_changed.read_at is not None
        self.assertIsNone(first_changed.read_at.tzinfo)
        assert other_user is not None
        self.assertIsNone(other_user.read_at)
        self.assertEqual(0, await service.mark_read(self.first_user_id, (first_ids[0],)))

        self.assertEqual(1, await service.mark_all_read(self.first_user_id))
        self.assertEqual(0, await service.mark_all_read(self.first_user_id))
        self.assertEqual(0, await service.unread_count(self.first_user_id))
        self.assertEqual(1, await service.unread_count(self.second_user_id))

        deleted = await service.delete(
            self.first_user_id,
            (first_ids[0], first_ids[0], second_id),
        )
        self.assertEqual(1, deleted)
        self.assertEqual(0, await service.delete(self.first_user_id, (second_id,)))
        self.assertIsNone(await service.get_for_user(self.first_user_id, first_ids[0]))
        self.assertIsNotNone(await service.get_for_user(self.second_user_id, second_id))

        self.assertEqual(
            [
                NOTIFICATION_SYNC_EVENT,
                NOTIFICATION_SYNC_EVENT,
                NOTIFICATION_SYNC_EVENT,
            ],
            [cast(str, call["event"]) for call in publisher.calls],
        )
        self.assertEqual(
            [2, 1, 1],
            [cast(NotificationSyncPayload, call["payload"]).changed_count for call in publisher.calls],
        )

    async def test_input_bounds_and_empty_id_sequences_fail_before_sql(self) -> None:
        """Strict integer bounds and empty mutation batches stay predictable."""
        service = Notifications(_publisher_factory=lambda: cast(Any, _RecordingPublisher()))

        invalid_list_arguments = (
            {"page": True},
            {"page": 0},
            {"page_size": True},
            {"page_size": 0},
            {"page_size": 101},
            {"state": "all"},
        )
        for arguments in invalid_list_arguments:
            with self.subTest(arguments=arguments), self.assertRaises((TypeError, ValueError)):
                await service.list_for_user(self.first_user_id, **arguments)  # pyright: ignore[reportArgumentType] -- exercise runtime validation

        for limit in (True, 0, 21):
            with self.subTest(limit=limit), self.assertRaises((TypeError, ValueError)):
                await service.topbar_for_user(self.first_user_id, limit=limit)
        for notification_id in (True, 0, -1):
            with self.subTest(notification_id=notification_id), self.assertRaises((TypeError, ValueError)):
                await service.get_for_user(self.first_user_id, notification_id)
        for user_id in (True, "1"):
            with self.subTest(user_id=user_id), self.assertRaises(TypeError):
                await service.unread_count(user_id)  # pyright: ignore[reportArgumentType] -- exercise runtime validation
        self.assertEqual(0, await service.unread_count(-1))

        invalid_ids: tuple[tuple[object, ...], ...] = (
            (True,),
            (0,),
            (-1,),
            ("1",),
        )
        for values in invalid_ids:
            with self.subTest(values=values), self.assertRaises((TypeError, ValueError)):
                await service.mark_read(self.first_user_id, values)  # pyright: ignore[reportArgumentType] -- exercise runtime validation
            with self.subTest(values=values), self.assertRaises((TypeError, ValueError)):
                await service.delete(self.first_user_id, values)  # pyright: ignore[reportArgumentType] -- exercise runtime validation

        with patch.object(
            self.manager,
            "get_session",
            side_effect=AssertionError("empty ids opened a write session"),
        ):
            self.assertEqual(0, await service.mark_read(self.first_user_id, ()))
            self.assertEqual(0, await service.delete(self.first_user_id, ()))

    @patch("oldman.web.messages.notifications.service._logger.error")
    async def test_create_push_and_sync_order_cache_and_false_transport(
        self,
        error_log: Any,
    ) -> None:
        """Database commits precede best-effort events and reuse one publisher."""
        publisher = _RecordingPublisher(outcomes=[False, False, False])
        factory_calls = 0

        def publisher_factory() -> _RecordingPublisher:
            nonlocal factory_calls
            factory_calls += 1
            return publisher

        service = Notifications(_publisher_factory=cast(Callable[[], SSEPublisher], publisher_factory))
        with patch.object(
            NotificationPayload,
            "from_msgpack",
            side_effect=AssertionError("create decoded its freshly encoded payload"),
        ):
            created = await service.create(
                user_id=self.first_user_id,
                title="Saved",
                presentation=NotificationPresentation.TOAST,
            )
        self.assertGreater(created.id, 0)
        self.assertEqual(1, await self._notification_count())
        created_call = publisher.calls[0]
        self.assertEqual(NOTIFICATION_CREATED_EVENT, created_call["event"])
        created_payload = cast(NotificationCreatedPayload, created_call["payload"])
        self.assertEqual(created.id, created_payload.notification_id)
        self.assertIsInstance(created_payload.notification.title, LazyTranslation)
        self.assertEqual("Saved", created_payload.notification.title.singular)
        self.assertIsNotNone(created_payload.created_at.tzinfo)
        created_json = msgspec.json.decode(created_payload.to_json_bytes())
        self.assertTrue(created_json["created_at"].endswith("Z"))

        self.assertFalse(
            await service.push(
                user_id=self.first_user_id,
                title="Temporary",
                presentation=NotificationPresentation.TOAST,
            )
        )
        self.assertEqual(1, await self._notification_count())
        self.assertEqual(NOTIFICATION_PUSH_EVENT, publisher.calls[1]["event"])

        self.assertEqual(1, await service.mark_read(self.first_user_id, (created.id,)))
        self.assertEqual(NOTIFICATION_SYNC_EVENT, publisher.calls[2]["event"])
        self.assertEqual(1, factory_calls)
        error_log.assert_not_called()

    async def test_database_failure_prevents_publish_and_user_delete_cascades(self) -> None:
        """Real foreign keys define create failure and User deletion behavior."""
        publisher = _RecordingPublisher()
        service = Notifications(_publisher_factory=lambda: cast(Any, publisher))

        with self.assertRaises(IntegrityError):
            await service.create(user_id=999999, title="Missing recipient")
        self.assertEqual([], publisher.calls)
        self.assertEqual(0, await self._notification_count())

        created = await service.create(
            user_id=self.first_user_id,
            title="Delete with user",
        )
        self.assertIsNotNone(await service.get_for_user(self.first_user_id, created.id))
        async with self.manager.get_session() as session:
            await session.exec(delete(User).where(User.id == self.first_user_id))
        self.assertIsNone(await service.get_for_user(self.first_user_id, created.id))

    async def test_sse_disabled_keeps_create_database_only_and_rejects_push(self) -> None:
        """Disabled realtime delivery must not construct its lazy publisher."""
        self.context.settings = self._settings(sse_enabled=False)

        def unexpected_factory() -> SSEPublisher:
            raise AssertionError("disabled SSE constructed a publisher")

        service = Notifications(_publisher_factory=unexpected_factory)
        created = await service.create(
            user_id=self.first_user_id,
            title="Database only",
        )
        self.assertIsNotNone(await service.get_for_user(self.first_user_id, created.id))
        with self.assertRaisesRegex(RuntimeError, "SSE.*disabled"):
            await service.push(
                user_id=self.first_user_id,
                title="Cannot deliver",
                presentation=NotificationPresentation.TOAST,
            )

    async def test_envelope_overflow_preserves_commits_but_push_propagates(self) -> None:
        """Only database-backed operations absorb a full-envelope size failure."""
        max_message_size = 220
        self.context.settings = self._settings(
            sse_enabled=True,
            max_message_size=max_message_size,
        )
        publisher = SSEPublisher(
            SSEConfig(
                enabled=True,
                redis_alias="SSE",
                channel_prefix="tests:notifications",
                max_message_size=max_message_size,
            ),
            registry=cast(Any, _PublisherRegistry()),
        )
        service = Notifications(_publisher_factory=lambda: publisher)

        with self.assertLogs("default.web.notifications", level="ERROR") as captured:
            created = await service.create(
                user_id=self.first_user_id,
                title="Persisted",
                body="x" * 400,
                presentation=NotificationPresentation.TOAST,
            )
        self.assertIsNotNone(await service.get_for_user(self.first_user_id, created.id))
        rendered_log = "\n".join(captured.output)
        self.assertIn(str(created.id), rendered_log)
        self.assertIn("business payload", rendered_log)
        self.assertIn(str(max_message_size), rendered_log)

        before_push = await self._notification_count()
        with self.assertRaises(SSEMessageTooLargeError):
            await service.push(
                user_id=self.first_user_id,
                title="Temporary",
                body="x" * 400,
                presentation=NotificationPresentation.TOAST,
            )
        self.assertEqual(before_push, await self._notification_count())

        tiny_limit = 1
        self.context.settings = self._settings(
            sse_enabled=True,
            max_message_size=tiny_limit,
        )
        sync_publisher = SSEPublisher(
            SSEConfig(
                enabled=True,
                redis_alias="SSE",
                channel_prefix="tests:notifications",
                max_message_size=tiny_limit,
            ),
            registry=cast(Any, _PublisherRegistry()),
        )
        sync_service = Notifications(_publisher_factory=lambda: sync_publisher)
        with self.assertLogs("default.web.notifications", level="ERROR"):
            changed = await sync_service.mark_read(
                self.first_user_id,
                (created.id,),
            )
        self.assertEqual(1, changed)

    async def test_payload_normalization_html_safety_and_business_validation(self) -> None:
        """One builder must normalize translations and reject unsafe display input."""
        publisher = _RecordingPublisher()
        service = Notifications(_publisher_factory=lambda: cast(Any, publisher))
        title = gettext_lazy("Imported %(name)s", name="<em>batch</em>")
        html_body = ngettext_lazy(
            "<b>One %(name)s</b>",
            "<b>%(num)s %(name)s</b>",
            2,
            name="<script>alert(1)</script>",
        )
        self.assertTrue(
            await service.push(
                user_id=self.first_user_id,
                title=title,
                body=html_body,
                format=MessageFormat.HTML,
                presentation=NotificationPresentation.MODAL,
                href="/imports/42?tab=errors#latest",
                icon="ri-error-warning-line",
            )
        )
        payload = cast(
            NotificationPushPayload,
            publisher.calls[-1]["payload"],
        ).notification
        self.assertIs(payload.title, title)
        self.assertEqual("<em>batch</em>", payload.title.variables["name"])
        assert payload.body is not None
        self.assertEqual(html_body.singular, payload.body.singular)
        self.assertEqual(html_body.plural, payload.body.plural)
        self.assertEqual(html_body.n, payload.body.n)
        self.assertEqual(
            "&lt;script&gt;alert(1)&lt;/script&gt;",
            payload.body.variables["name"],
        )

        self.assertTrue(
            await service.push(
                user_id=self.first_user_id,
                title="Plain title",
                body="Plain body",
                presentation=NotificationPresentation.TOAST,
            )
        )
        plain_payload = cast(
            NotificationPushPayload,
            publisher.calls[-1]["payload"],
        ).notification
        self.assertIsInstance(plain_payload.title, LazyTranslation)
        self.assertIsInstance(plain_payload.body, LazyTranslation)
        assert plain_payload.body is not None
        self.assertEqual("Plain body", plain_payload.body.singular)

        invalid_calls: tuple[dict[str, Any], ...] = (
            {"title": ""},
            {"title": "   "},
            {"title": "Title", "level": "info"},
            {"title": "Title", "format": "text"},
            {"title": "Title", "body": object()},
            {"title": "Title", "presentation": "toast"},
            {"title": "Title", "presentation": NotificationPresentation.NONE},
            {"title": "Title", "href": "https://example.com/path"},
            {"title": "Title", "href": "//example.com/path"},
            {"title": "Title", "href": "/\\example.com/path"},
            {"title": "Title", "href": "/\texample.com/path"},
            {"title": "Title", "icon": "fa-bell"},
            {"title": "x" * (33 * 1024)},
        )
        for arguments in invalid_calls:
            arguments.setdefault(
                "presentation",
                NotificationPresentation.TOAST,
            )
            with self.subTest(arguments=arguments), self.assertRaises((TypeError, ValueError)):
                await service.push(user_id=self.first_user_id, **arguments)


if __name__ == "__main__":
    unittest.main()
