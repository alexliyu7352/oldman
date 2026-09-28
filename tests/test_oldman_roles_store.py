"""Roles store: the database decides, Redis holds a copy of each role's permissions."""

from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from sqlalchemy.schema import Table
from sqlmodel import select

import oldman.conf as conf
from oldman.apps.roles.models import Role, UserRole
from oldman.apps.roles.store import (
    checked_permission_names,
    forget_role,
    publish_role,
    replace_user_roles,
    role_permissions,
    user_role_ids,
)
from oldman.auth import Permission, PermissionSet
from oldman.auth.models import User
from oldman.conf.schemas import DatabaseConfig, DefaultSettings
from oldman.db.session import DatabaseManager
from oldman.providers.redis import RedisClientRegistry
from tests.redis_support import RedisProcess, owned_redis_config, require_redis_server


class StorePermissions(PermissionSet, namespace="roles_store_test"):
    view = Permission("View")
    export = Permission("Export")


class RolesStoreTest(unittest.IsolatedAsyncioTestCase):
    """A test-owned redis-server and an in-memory SQLite database with the user and role tables."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory()
        cls._redis = RedisProcess(require_redis_server(), Path(cls._directory.name), "roles")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._redis.stop()
        cls._directory.cleanup()

    async def asyncSetUp(self) -> None:
        settings = DefaultSettings()
        settings.core.namespace = "svc"
        self.enterContext(patch.dict(conf.__dict__, {"settings": settings}))
        self.registry = RedisClientRegistry(owned_redis_config(self._redis.socket_path, {"SESSION": 5}))
        self.enterContext(patch("oldman.providers.redis.redis_client", self.registry))
        self.connection = await self.registry.using("SESSION").async_get_conn()
        await self.connection.flushdb()

        self.database = DatabaseManager(DatabaseConfig(url="sqlite+aiosqlite:///:memory:"))
        await self.database.initialize()
        async with self.database.engine.begin() as connection:
            for model in (User, Role, UserRole):
                await connection.run_sync(cast(Table, model.__table__).create)
        async with self.database.get_session() as session:
            session.add(User(id=1, username="alice", password_hash="", is_active=True, is_staff=True, is_superuser=False))
            self.viewer = Role(name="viewer", permissions=["roles_store_test.view"])
            self.exporter = Role(name="exporter", permissions=["roles_store_test.export"])
            session.add_all([self.viewer, self.exporter])
            await session.flush()
            self.viewer_id, self.exporter_id = self.viewer.id, self.exporter.id

    async def asyncTearDown(self) -> None:
        await self.database.close()
        await self.registry.close()

    async def permissions(self, *role_ids: int) -> frozenset[str]:
        return await role_permissions(role_ids, db_manager=self.database)

    async def test_only_declared_permission_names_can_be_given_to_a_role(self) -> None:
        self.assertEqual(
            ["roles_store_test.export", "roles_store_test.view"],
            checked_permission_names(["roles_store_test.view", "roles_store_test.export", "roles_store_test.view"]),
        )
        with self.assertRaisesRegex(ValueError, "roles_store_test.delete"):
            checked_permission_names(["roles_store_test.view", "roles_store_test.delete"])

    async def test_a_missing_key_is_read_from_the_database_and_kept(self) -> None:
        self.assertEqual({"roles_store_test.view", "roles_store_test.export"}, await self.permissions(self.viewer_id, self.exporter_id))
        self.assertEqual(["roles_store_test.view"], json.loads(await self.connection.get(f"svc:role:{self.viewer_id}")))

    async def test_a_published_role_is_answered_from_redis(self) -> None:
        self.viewer.permissions = ["roles_store_test.view", "roles_store_test.export"]
        await publish_role(self.viewer)
        # The database still says view only: the cached copy is what a check reads.
        self.assertEqual({"roles_store_test.view", "roles_store_test.export"}, await self.permissions(self.viewer_id))

    async def test_filling_a_missing_key_never_overwrites_a_save_that_landed_meanwhile(self) -> None:
        # A request misses the key and reads the old row; a save writes the new permissions before
        # the request writes the key back. The fill-in must not replace what the save wrote.
        open_read_session = self.database.get_read_session

        @asynccontextmanager
        async def read_then_save() -> AsyncIterator[Any]:
            async with open_read_session() as session:
                yield session
            self.viewer.permissions = ["roles_store_test.export"]
            await publish_role(self.viewer)

        with patch.object(self.database, "get_read_session", read_then_save):
            answered = await self.permissions(self.viewer_id)

        self.assertEqual({"roles_store_test.view"}, answered)
        self.assertEqual(["roles_store_test.export"], json.loads(await self.connection.get(f"svc:role:{self.viewer_id}")))

    async def test_a_deleted_role_grants_nothing(self) -> None:
        await self.permissions(self.viewer_id)
        async with self.database.get_session() as session:
            role = await session.get(Role, self.viewer_id)
            await session.delete(role)
        await forget_role(self.viewer_id)

        self.assertEqual(frozenset(), await self.permissions(self.viewer_id))
        self.assertIsNone(await self.connection.get(f"svc:role:{self.viewer_id}"))
        self.assertEqual(frozenset(), await self.permissions())

    async def test_a_users_roles_are_replaced_and_the_change_is_reported(self) -> None:
        async with self.database.get_session() as session:
            self.assertTrue(await replace_user_roles(session, 1, [self.viewer_id]))
        self.assertEqual((self.viewer_id,), await user_role_ids(1, db_manager=self.database))

        async with self.database.get_session() as session:
            self.assertFalse(await replace_user_roles(session, 1, [self.viewer_id]))
            self.assertTrue(await replace_user_roles(session, 1, [self.exporter_id]))
        self.assertEqual((self.exporter_id,), await user_role_ids(1, db_manager=self.database))

        async with self.database.get_session() as session:
            self.assertTrue(await replace_user_roles(session, 1, []))
            self.assertEqual([], list((await session.exec(select(UserRole))).all()))


if __name__ == "__main__":
    unittest.main()
