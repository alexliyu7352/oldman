"""模型文件列在数据库事务结束后的最终状态清理测试。"""

from __future__ import annotations

import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from sqlalchemy import Integer, String, Table, event, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import Mapped, defer, mapped_column
from sqlmodel.ext.asyncio.session import AsyncSession

from oldman.conf.schemas import DatabaseConfig
from oldman.db.models import DatabaseModel, ModelMetadata
from oldman.db.session import DatabaseManager
from oldman.storage import InMemoryStorage, file_column
from oldman.storage.lifecycle import OldmanWriteSession, install_model_file_lifecycle
from oldman.storage.models import register_created_file


class LifecycleFileModel(DatabaseModel):
    """提供两个独立 Storage 文件列和一个普通热路径字段。"""

    __tablename__ = "task6_file_lifecycle"  # pyright: ignore[reportAssignmentType]

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    avatar: Mapped[str | None] = file_column(upload_to="avatars", storage="images", nullable=True)
    contract: Mapped[str | None] = file_column(upload_to="contracts", storage="documents", nullable=True)


class LifecyclePlainModel(DatabaseModel):
    """验证普通模型写入不承担文件查询。"""

    __tablename__ = "task6_plain_lifecycle"  # pyright: ignore[reportAssignmentType]

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))


FILE_MODEL_METADATA = ModelMetadata(
    model=LifecycleFileModel,
    table=cast(Table, LifecycleFileModel.__table__),
    app_label="tests",
    verbose_name="Lifecycle file",
    verbose_name_plural="Lifecycle files",
    managed=True,
)
PLAIN_MODEL_METADATA = ModelMetadata(
    model=LifecyclePlainModel,
    table=cast(Table, LifecyclePlainModel.__table__),
    app_label="tests",
    verbose_name="Lifecycle plain",
    verbose_name_plural="Lifecycle plains",
    managed=True,
)


class DeleteFailStorage(InMemoryStorage):
    """模拟单个 Storage 删除故障。"""

    async def _delete(self, name: str) -> None:
        raise PermissionError(name)


class StorageSet:
    """提供生命周期代码使用的最小命名 Storage registry。"""

    def __init__(self, *, fail_images_delete: bool = False) -> None:
        storage_type = DeleteFailStorage if fail_images_delete else InMemoryStorage
        self.images = storage_type(alias="images")
        self.documents = InMemoryStorage(alias="documents")

    def using(self, alias: str) -> InMemoryStorage:
        return {"images": self.images, "documents": self.documents}[alias]


class ModelFileLifecycleTest(unittest.IsolatedAsyncioTestCase):
    """以真实异步 SQLite 验证最终数据库状态驱动的清理。"""

    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "files.sqlite3"
        self.manager = DatabaseManager(DatabaseConfig(url=f"sqlite+aiosqlite:///{database_path.as_posix()}", echo=False))
        install_model_file_lifecycle((FILE_MODEL_METADATA, PLAIN_MODEL_METADATA))
        await self.manager.create_db_and_tables()
        self.storages = StorageSet()

    async def asyncTearDown(self) -> None:
        await self.manager.close()
        self.temp_dir.cleanup()

    def lifecycle_patch(self):
        """让最终清理使用当前测试的隔离 Storage。"""
        return patch("oldman.storage.lifecycle.storages", self.storages)

    async def store(self, alias: str, name: str, body: bytes | None = None) -> str:
        """创建一个测试文件并返回 Storage 最终名称。"""
        return await self.storages.using(alias).save(name, body or name.encode())

    async def seed(self, *, avatar: str | None = None, contract: str | None = None, row_id: int = 1) -> LifecycleFileModel:
        """插入一条初始文件记录。"""
        if avatar is not None and not await self.storages.images.exists(avatar):
            await self.store("images", avatar)
        if contract is not None and not await self.storages.documents.exists(contract):
            await self.store("documents", contract)
        instance = LifecycleFileModel(id=row_id, name="before", avatar=avatar, contract=contract)
        with self.lifecycle_patch():
            async with self.manager.get_session() as session:
                session.add(instance)
        return instance

    async def load_row(self, row_id: int = 1) -> LifecycleFileModel | None:
        """从新的只读 Session 获取最终数据库记录。"""
        async with self.manager.get_read_session() as session:
            return await session.get(LifecycleFileModel, row_id)

    async def create_for_session(self, session: Any, instance: Any, field_name: str, alias: str, name: str) -> str:
        """模拟框架上传入口保存并登记一个本次创建文件。"""
        path = await self.store(alias, name)
        register_created_file(session, instance, field_name, alias, path)
        return path

    async def test_replacement_commit_keeps_new_and_deletes_database_original(self) -> None:
        original = "avatars/original.png"
        await self.seed(avatar=original)

        with self.lifecycle_patch():
            async with self.manager.get_session() as session:
                instance = await session.get(LifecycleFileModel, 1)
                assert instance is not None
                created = await self.create_for_session(session, instance, "avatar", "images", "avatars/new.png")
                instance.avatar = created

        row = await self.load_row()
        assert row is not None
        self.assertEqual(created, row.avatar)
        self.assertFalse(await self.storages.images.exists(original))
        self.assertTrue(await self.storages.images.exists(created))

    async def test_replacement_rollback_keeps_original_and_deletes_created(self) -> None:
        original = "avatars/original.png"
        await self.seed(avatar=original)

        class AbortWrite(RuntimeError):
            pass

        with self.lifecycle_patch(), self.assertRaises(AbortWrite):
            async with self.manager.get_session() as session:
                instance = await session.get(LifecycleFileModel, 1)
                assert instance is not None
                created = await self.create_for_session(session, instance, "avatar", "images", "avatars/new.png")
                instance.avatar = created
                raise AbortWrite

        row = await self.load_row()
        assert row is not None
        self.assertEqual(original, row.avatar)
        self.assertTrue(await self.storages.images.exists(original))
        self.assertFalse(await self.storages.images.exists("avatars/new.png"))

    async def test_multiple_flushes_take_one_original_and_one_final_query(self) -> None:
        original = "avatars/original.png"
        await self.seed(avatar=original)
        statements: list[str] = []

        @event.listens_for(self.manager.engine.sync_engine, "before_cursor_execute")
        def record_statement(_connection: Any, _cursor: Any, statement: str, _parameters: Any, _context: Any, _many: bool) -> None:
            if statement.lstrip().upper().startswith("SELECT") and LifecycleFileModel.__tablename__ in statement:
                statements.append(statement)

        try:
            with self.lifecycle_patch():
                async with self.manager.get_session() as session:
                    instance = await session.get(LifecycleFileModel, 1)
                    assert instance is not None
                    statements.clear()
                    first = await self.create_for_session(session, instance, "avatar", "images", "avatars/first.png")
                    instance.avatar = first
                    await session.flush()
                    second = await self.create_for_session(session, instance, "avatar", "images", "avatars/second.png")
                    instance.avatar = second
                    await session.flush()
        finally:
            event.remove(self.manager.engine.sync_engine, "before_cursor_execute", record_statement)

        self.assertEqual(2, len(statements), statements)
        self.assertFalse(await self.storages.images.exists(original))
        self.assertFalse(await self.storages.images.exists(first))
        self.assertTrue(await self.storages.images.exists(second))

    async def test_assigning_back_original_only_cleans_a_file_created_this_time(self) -> None:
        original = "avatars/original.png"
        existing = "avatars/existing.png"
        await self.seed(avatar=original)
        await self.store("images", existing)

        with self.lifecycle_patch():
            async with self.manager.get_session() as session:
                instance = await session.get(LifecycleFileModel, 1)
                assert instance is not None
                created = await self.create_for_session(session, instance, "avatar", "images", "avatars/temporary.png")
                instance.avatar = created
                instance.avatar = original
                instance.avatar = existing
                instance.avatar = original

        self.assertTrue(await self.storages.images.exists(original))
        self.assertTrue(await self.storages.images.exists(existing))
        self.assertFalse(await self.storages.images.exists(created))

    async def test_clear_and_delete_use_database_original_but_rollback_preserves_it(self) -> None:
        clear_path = "avatars/clear.png"
        await self.seed(avatar=clear_path, row_id=1)
        with self.lifecycle_patch():
            async with self.manager.get_session() as session:
                instance = await session.get(LifecycleFileModel, 1)
                assert instance is not None
                instance.avatar = None
        self.assertFalse(await self.storages.images.exists(clear_path))

        delete_path = "avatars/delete.png"
        await self.seed(avatar=delete_path, row_id=2)
        with self.lifecycle_patch():
            async with self.manager.get_session() as session:
                instance = await session.get(LifecycleFileModel, 2)
                assert instance is not None
                await session.delete(instance)
        self.assertFalse(await self.storages.images.exists(delete_path))

        rollback_path = "avatars/rollback-delete.png"
        await self.seed(avatar=rollback_path, row_id=3)
        with self.lifecycle_patch(), self.assertRaisesRegex(RuntimeError, "abort"):
            async with self.manager.get_session() as session:
                instance = await session.get(LifecycleFileModel, 3)
                assert instance is not None
                await session.delete(instance)
                raise RuntimeError("abort")
        self.assertTrue(await self.storages.images.exists(rollback_path))

    async def test_new_instance_rollback_without_identity_deletes_only_created_file(self) -> None:
        created = "avatars/new-row.png"
        existing = "avatars/unowned-existing.png"
        await self.store("images", existing)

        with self.lifecycle_patch(), self.assertRaisesRegex(RuntimeError, "abort"):
            async with self.manager.get_session() as session:
                instance = LifecycleFileModel(name="new", avatar=existing, contract=None)
                instance.avatar = await self.create_for_session(session, instance, "avatar", "images", created)
                session.add(instance)
                raise RuntimeError("abort")

        self.assertFalse(await self.storages.images.exists(created))
        self.assertTrue(await self.storages.images.exists(existing))

    async def test_multiple_fields_and_delete_error_are_isolated(self) -> None:
        self.storages = StorageSet(fail_images_delete=True)
        avatar = "avatars/original.png"
        contract = "contracts/original.pdf"
        await self.seed(avatar=avatar, contract=contract)

        with self.lifecycle_patch(), patch("oldman.storage.lifecycle.logger.error") as log_error:
            async with self.manager.get_session() as session:
                instance = await session.get(LifecycleFileModel, 1)
                assert instance is not None
                instance.avatar = None
                instance.contract = None

        self.assertTrue(await self.storages.images.exists(avatar))
        self.assertFalse(await self.storages.documents.exists(contract))
        self.assertTrue(log_error.called)

    async def test_deferred_expired_and_detached_values_use_database_snapshot(self) -> None:
        original = "avatars/original.png"
        await self.seed(avatar=original)

        with self.lifecycle_patch():
            async with self.manager.get_session() as session:
                statement = select(LifecycleFileModel).options(defer(LifecycleFileModel.avatar))
                result = await session.exec(cast(Any, statement))
                instance = result.scalar_one()
                created = await self.create_for_session(session, instance, "avatar", "images", "avatars/deferred.png")
                instance.avatar = created
        self.assertFalse(await self.storages.images.exists(original))

        with self.lifecycle_patch():
            async with self.manager.get_session() as session:
                instance = await session.get(LifecycleFileModel, 1)
                assert instance is not None
                session.expire(instance, ["avatar"])
                created = await self.create_for_session(session, instance, "avatar", "images", "avatars/expired.png")
                instance.avatar = created
        self.assertFalse(await self.storages.images.exists("avatars/deferred.png"))

        async with self.manager.get_read_session() as session:
            detached = await session.get(LifecycleFileModel, 1)
        assert detached is not None
        detached.avatar = await self.store("images", "avatars/detached.png")
        detached_path = detached.avatar
        assert detached_path is not None
        with self.lifecycle_patch():
            async with self.manager.get_session() as session:
                register_created_file(session, detached, "avatar", "images", detached_path)
                session.add(detached)
        self.assertFalse(await self.storages.images.exists("avatars/expired.png"))
        self.assertTrue(await self.storages.images.exists("avatars/detached.png"))

    async def test_savepoint_rollback_uses_outer_transaction_final_state(self) -> None:
        original = "avatars/original.png"
        await self.seed(avatar=original)

        with self.lifecycle_patch():
            async with self.manager.get_session() as session:
                instance = await session.get(LifecycleFileModel, 1)
                assert instance is not None
                savepoint = await session.begin_nested()
                created = await self.create_for_session(session, instance, "avatar", "images", "avatars/savepoint.png")
                instance.avatar = created
                await session.flush()
                await savepoint.rollback()

        row = await self.load_row()
        assert row is not None
        self.assertEqual(original, row.avatar)
        self.assertTrue(await self.storages.images.exists(original))
        self.assertFalse(await self.storages.images.exists(created))

    async def test_primary_key_change_queries_the_committed_identity(self) -> None:
        original = "avatars/original.png"
        await self.seed(avatar=original)

        with self.lifecycle_patch():
            async with self.manager.get_session() as session:
                instance = await session.get(LifecycleFileModel, 1)
                assert instance is not None
                created = await self.create_for_session(session, instance, "avatar", "images", "avatars/moved.png")
                instance.id = 2
                instance.avatar = created

        self.assertIsNone(await self.load_row(1))
        row = await self.load_row(2)
        assert row is not None
        self.assertEqual(created, row.avatar)
        self.assertFalse(await self.storages.images.exists(original))
        self.assertTrue(await self.storages.images.exists(created))

    async def test_original_snapshot_failure_aborts_flush_with_the_original_error(self) -> None:
        original = "avatars/original.png"
        await self.seed(avatar=original)
        block_snapshot = False
        failed_once = False

        class SnapshotError(RuntimeError):
            pass

        @event.listens_for(self.manager.engine.sync_engine, "before_cursor_execute")
        def reject_snapshot(_connection: Any, _cursor: Any, statement: str, _parameters: Any, _context: Any, _many: bool) -> None:
            nonlocal failed_once
            if block_snapshot and not failed_once and statement.lstrip().upper().startswith("SELECT"):
                failed_once = True
                raise SnapshotError("snapshot unavailable")

        try:
            with self.lifecycle_patch(), self.assertRaises(SnapshotError):
                async with self.manager.get_session() as session:
                    instance = await session.get(LifecycleFileModel, 1)
                    assert instance is not None
                    created = await self.create_for_session(session, instance, "avatar", "images", "avatars/new.png")
                    instance.avatar = created
                    block_snapshot = True
        finally:
            event.remove(self.manager.engine.sync_engine, "before_cursor_execute", reject_snapshot)

        row = await self.load_row()
        assert row is not None
        self.assertEqual(original, row.avatar)
        self.assertTrue(await self.storages.images.exists(original))
        self.assertFalse(await self.storages.images.exists("avatars/new.png"))

    async def test_final_query_failure_preserves_all_files_and_original_error(self) -> None:
        original = "avatars/original.png"
        await self.seed(avatar=original)

        @asynccontextmanager
        async def failing_read_session():
            raise RuntimeError("final query unavailable")
            yield  # pragma: no cover

        class AbortWrite(RuntimeError):
            pass

        with (
            self.lifecycle_patch(),
            patch.object(self.manager, "get_read_session", failing_read_session),
            patch("oldman.storage.lifecycle.logger.error") as log_error,
            self.assertRaises(AbortWrite),
        ):
            async with self.manager.get_session() as session:
                instance = await session.get(LifecycleFileModel, 1)
                assert instance is not None
                created = await self.create_for_session(session, instance, "avatar", "images", "avatars/new.png")
                instance.avatar = created
                raise AbortWrite

        self.assertTrue(await self.storages.images.exists(original))
        self.assertTrue(await self.storages.images.exists("avatars/new.png"))
        self.assertTrue(log_error.called)

    async def test_final_query_failure_does_not_turn_committed_write_into_failure(self) -> None:
        original = "avatars/original.png"
        await self.seed(avatar=original)

        @asynccontextmanager
        async def failing_read_session():
            raise RuntimeError("final query unavailable")
            yield  # pragma: no cover

        with (
            self.lifecycle_patch(),
            patch.object(self.manager, "get_read_session", failing_read_session),
            patch("oldman.storage.lifecycle.logger.error") as log_error,
        ):
            async with self.manager.get_session() as session:
                instance = await session.get(LifecycleFileModel, 1)
                assert instance is not None
                created = await self.create_for_session(session, instance, "avatar", "images", "avatars/new.png")
                instance.avatar = created

        row = await self.load_row()
        assert row is not None
        self.assertEqual("avatars/new.png", row.avatar)
        self.assertTrue(await self.storages.images.exists(original))
        self.assertTrue(await self.storages.images.exists("avatars/new.png"))
        self.assertTrue(log_error.called)

    async def test_plain_and_non_file_updates_do_not_open_final_read_session(self) -> None:
        await self.seed(avatar="avatars/original.png")
        calls = 0
        original_get_read_session = self.manager.get_read_session

        @asynccontextmanager
        async def counted_read_session():
            nonlocal calls
            calls += 1
            async with original_get_read_session() as session:
                yield session

        with self.lifecycle_patch(), patch.object(self.manager, "get_read_session", counted_read_session):
            async with self.manager.get_session() as session:
                session.add(LifecyclePlainModel(id=1, name="plain"))
            async with self.manager.get_session() as session:
                instance = await session.get(LifecycleFileModel, 1)
                assert instance is not None
                instance.name = "after"
            async with self.manager.get_session() as session:
                plain = await session.get(LifecyclePlainModel, 1)
                assert plain is not None
                await session.delete(plain)

        self.assertEqual(0, calls)

    async def test_only_framework_write_session_uses_internal_sync_session(self) -> None:
        async with self.manager.get_session() as write_session:
            self.assertIsInstance(write_session.sync_session, OldmanWriteSession)
        async with self.manager.get_read_session() as read_session:
            self.assertNotIsInstance(read_session.sync_session, OldmanWriteSession)

    async def test_user_created_async_session_does_not_run_file_cleanup(self) -> None:
        original = "avatars/original.png"
        replacement = "avatars/existing.png"
        await self.seed(avatar=original)
        await self.store("images", replacement)
        session_maker = async_sessionmaker(self.manager.engine, class_=AsyncSession, expire_on_commit=False)

        async with session_maker.begin() as session:
            self.assertNotIsInstance(session.sync_session, OldmanWriteSession)
            instance = await session.get(LifecycleFileModel, 1)
            assert instance is not None
            instance.avatar = replacement

        self.assertTrue(await self.storages.images.exists(original))
        self.assertTrue(await self.storages.images.exists(replacement))


if __name__ == "__main__":
    unittest.main()
