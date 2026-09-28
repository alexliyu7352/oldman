"""The model cache: rows come back as the database gave them, and a committed write is never hidden by a cached entry."""

from __future__ import annotations

import asyncio
import enum
import math
import tempfile
import unittest
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar, cast
from unittest.mock import patch

import orjson
from sqlalchemy import (
    ARRAY,
    JSON,
    Column,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Interval,
    LargeBinary,
    MetaData,
    Numeric,
    PickleType,
    String,
    Table,
    Uuid,
    bindparam,
    create_engine,
    event,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, load_only, mapped_column, relationship, selectinload
from sqlalchemy.orm.attributes import instance_state
from sqlalchemy.orm.exc import DetachedInstanceError

import oldman.conf as conf
import oldman.db.sqlalchemy.cache as model_cache
from oldman.conf.schemas import DatabaseConfig, DefaultSettings
from oldman.db.session import DatabaseManager
from oldman.db.sqlalchemy.cache import AsyncQueryCache, CacheableModel, RowCodec, cached_model
from oldman.db.sqlalchemy.models import DatabaseModel
from oldman.db.sqlalchemy.utils import JSONText
from oldman.providers.redis.client import RedisClientRegistry
from tests.redis_support import RedisProcess, owned_redis_config, require_redis_server


class Shape(enum.Enum):
    ROUND = "r"
    SQUARE = "s"


@cached_model()
class TypedRow(CacheableModel):
    __tablename__ = "mc_typed_row"
    id: Mapped[int] = mapped_column(primary_key=True)
    flag: Mapped[bool]
    ratio: Mapped[float]
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    label: Mapped[str] = mapped_column(String(20))
    at: Mapped[datetime]
    day: Mapped[date]
    clock: Mapped[time]
    span: Mapped[timedelta] = mapped_column(Interval)
    token: Mapped[uuid.UUID] = mapped_column(Uuid)
    blob: Mapped[bytes] = mapped_column(LargeBinary)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    legacy: Mapped[list[int] | None] = mapped_column(JSONText, nullable=True)
    shape: Mapped[Shape] = mapped_column(Enum(Shape))
    kind: Mapped[str] = mapped_column(Enum("a", "b", name="mc_kind"))
    note: Mapped[str | None]


class ChannelRow(DatabaseModel):
    __tablename__ = "mc_channel"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(20))


@cached_model(partition_by=("channel_id",))
class ProgrammeRow(CacheableModel):
    __tablename__ = "mc_programme"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("mc_channel.id"))
    title: Mapped[str] = mapped_column(String(40))
    starts_at: Mapped[datetime]
    channel: Mapped[ChannelRow] = relationship()


@cached_model()
class LookupRow(CacheableModel):
    """Two columns whose names begin with the same two letters (E-10)."""

    __tablename__ = "mc_lookup"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None]
    employee_id: Mapped[str | None]


@cached_model()
class ShapeKeyRow(CacheableModel):
    """An enum primary key: the cached row names it ROUND, str() names it Shape.ROUND (G3-2)."""

    __tablename__ = "mc_shape_key"
    shape: Mapped[Shape] = mapped_column(Enum(Shape), primary_key=True)
    label: Mapped[str] = mapped_column(String(20))


@cached_model()
class SlotKeyRow(CacheableModel):
    """A datetime primary key: the cached row names it in ISO form, str() with a space (G3-2)."""

    __tablename__ = "mc_slot_key"
    starts_at: Mapped[datetime] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(20))


@cached_model(partition_by=("published",))
class NoticeRow(CacheableModel):
    """A boolean partition (G3-10)."""

    __tablename__ = "mc_notice"
    id: Mapped[int] = mapped_column(primary_key=True)
    published: Mapped[bool]
    title: Mapped[str] = mapped_column(String(40))


class CascadeChannelRow(DatabaseModel):
    __tablename__ = "mc_cascade_channel"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(20))


@cached_model(partition_by=("channel_id",), invalidate_on=(CascadeChannelRow,))
class CascadeProgrammeRow(CacheableModel):
    """The database deletes these rows with their channel, without an ORM event on them."""

    __tablename__ = "mc_cascade_programme"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("mc_cascade_channel.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(40))


@cached_model()
class TreeRow(CacheableModel):
    """Deleting a node deletes its subtree in the database; the class cannot name itself in invalidate_on (G3-11)."""

    __tablename__ = "mc_tree"
    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("mc_tree.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(40))


class ChainRootRow(DatabaseModel):
    __tablename__ = "mc_chain_root"
    id: Mapped[int] = mapped_column(primary_key=True)


class ChainMiddleRow(DatabaseModel):
    """Deleted by the database with its root."""

    __tablename__ = "mc_chain_middle"
    id: Mapped[int] = mapped_column(primary_key=True)
    root_id: Mapped[int] = mapped_column(ForeignKey("mc_chain_root.id", ondelete="CASCADE"))


@cached_model(invalidate_on=(ChainMiddleRow, ChainRootRow))
class ChainLeafRow(CacheableModel):
    """Deleted by the database with its middle row - so also when the root goes."""

    __tablename__ = "mc_chain_leaf"
    id: Mapped[int] = mapped_column(primary_key=True)
    middle_id: Mapped[int] = mapped_column(ForeignKey("mc_chain_middle.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(40))


def typed_values(row_id: int = 1) -> dict[str, Any]:
    return {
        "id": row_id,
        "flag": True,
        "ratio": 0.25,
        "price": Decimal("12.30"),
        "label": "news",
        "at": datetime(2026, 9, 26, 19, 30, 15, 123456),
        "day": date(2026, 9, 26),
        "clock": time(19, 30, 15, 500),
        "span": timedelta(days=1, seconds=5, microseconds=7),
        "token": uuid.UUID("0190f3a1-5b7c-7d2e-8f00-0123456789ab"),
        "blob": b"\x00\xffbinary",
        "payload": {"a": [1, 2, {"b": None}]},
        "legacy": [1, 2, 3],
        "shape": Shape.SQUARE,
        "kind": "b",
        "note": None,
    }


def at(hour: int) -> datetime:
    return datetime(2026, 9, 26, hour, 0)


async def settle() -> None:
    """Wait for the invalidations this process started after its commits."""
    await model_cache.wait_for_invalidations()


class RowCodecTest(unittest.TestCase):
    def test_every_supported_column_type_comes_back_as_the_same_value_and_type(self) -> None:
        codec = TypedRow.get_cache_manager().codec
        assert codec is not None
        values = typed_values()

        restored = codec.decode(orjson.loads(orjson.dumps(codec.encode(TypedRow(**values)))))

        for key, expected in values.items():
            with self.subTest(column=key):
                actual = getattr(restored, key)
                self.assertEqual(expected, actual)
                self.assertIs(type(expected), type(actual))

    def test_a_snapshot_is_detached_and_refuses_to_lazy_load_instead_of_reading_empty(self) -> None:
        codec = ProgrammeRow.get_cache_manager().codec
        assert codec is not None

        snapshot = codec.decode(codec.encode(ProgrammeRow(id=3, channel_id=1, title="news", starts_at=at(19))))

        self.assertTrue(inspect(snapshot).detached)
        self.assertEqual(3, snapshot.id)
        with self.assertRaises(DetachedInstanceError):
            _ = snapshot.channel

    def test_a_row_with_an_unloaded_column_is_not_encoded(self) -> None:
        codec = ProgrammeRow.get_cache_manager().codec
        assert codec is not None

        with self.assertRaises(ValueError):
            codec.encode(ProgrammeRow(id=3, title="news"))

    def test_types_that_cannot_round_trip_are_refused_when_the_model_is_declared(self) -> None:
        class Isolated(DeclarativeBase):
            """Keeps these models out of the shared metadata other tests create tables from."""

        class CustomTyped(Isolated):
            __tablename__ = "mc_custom_typed"
            id: Mapped[int] = mapped_column(primary_key=True)
            pickled: Mapped[object] = mapped_column(PickleType)  # a TypeDecorator: its Python values are opaque

        class ArrayTyped(Isolated):
            __tablename__ = "mc_array_typed"
            id: Mapped[int] = mapped_column(primary_key=True)
            numbers: Mapped[list[int]] = mapped_column(ARRAY(Integer))

        class DeferredColumn(Isolated):
            """G3-5: never loaded with the row, so every cached read used to fail on an incomplete row."""

            __tablename__ = "mc_deferred_column"
            id: Mapped[int] = mapped_column(primary_key=True)
            body: Mapped[str] = mapped_column(String(20), deferred=True)

        models: tuple[type[Any], ...] = (CustomTyped, ArrayTyped, DeferredColumn)
        for model in models:
            with self.subTest(model=model.__name__), self.assertRaises(TypeError):
                RowCodec(model)

    def test_declaring_does_not_configure_mappers_before_their_relationships_exist(self) -> None:
        """@cached_model runs while the module is still defining classes; configuring then fails on a relationship to a later one."""

        class Isolated(DeclarativeBase):
            """Keeps these models out of the shared metadata other tests create tables from."""

        class Project(Isolated):
            __tablename__ = "mc_forward_project"
            id: Mapped[int] = mapped_column(primary_key=True)
            tags: Mapped[list[Any]] = relationship("ForwardTag")

        RowCodec(Project)

        class ForwardTag(Isolated):
            __tablename__ = "mc_forward_tag"
            id: Mapped[int] = mapped_column(primary_key=True)
            project_id: Mapped[int] = mapped_column(ForeignKey("mc_forward_project.id"))

        self.assertEqual(["id"], [key for key, _, _ in RowCodec(Project).columns])

    def test_floats_keep_nan_and_infinity(self) -> None:
        """G3-6: JSON has no NaN or infinity; orjson wrote them as null, and they read back as None."""
        codec = TypedRow.get_cache_manager().codec
        assert codec is not None
        for ratio in (math.inf, -math.inf, math.nan, 0.25):
            with self.subTest(ratio=ratio):
                restored = codec.decode(orjson.loads(orjson.dumps(codec.encode(TypedRow(**{**typed_values(), "ratio": ratio})))))
                self.assertIs(float, type(restored.ratio))
                self.assertTrue(math.isnan(restored.ratio) if math.isnan(ratio) else restored.ratio == ratio)

    def test_a_float_column_returning_decimals_keeps_them(self) -> None:
        """G3-5: Float(asdecimal=True) returns Decimal values, which the float codec passed on and JSON refused."""

        class Isolated(DeclarativeBase):
            """Keeps this model out of the shared metadata other tests create tables from."""

        class Measured(Isolated):
            __tablename__ = "mc_measured"
            id: Mapped[int] = mapped_column(primary_key=True)
            exact: Mapped[Decimal] = mapped_column(Float(asdecimal=True))

        codec = RowCodec(Measured)
        restored = codec.decode(orjson.loads(orjson.dumps(codec.encode(Measured(id=1, exact=Decimal("1.5"))))))

        self.assertEqual((Decimal, Decimal("1.5")), (type(restored.exact), restored.exact))

    def test_partition_columns_must_compare_in_the_database_as_in_python(self) -> None:
        for partition_by in (("title",), ("starts_at",), ("no_such_column",)):
            with self.subTest(partition_by=partition_by), self.assertRaises(TypeError):
                AsyncQueryCache(ProgrammeRow, partition_by=partition_by)

    def test_the_fingerprint_names_the_columns_and_their_representation(self) -> None:
        typed, programme = TypedRow.get_cache_manager(), ProgrammeRow.get_cache_manager()
        assert typed.codec is not None and programme.codec is not None

        self.assertNotEqual(typed.codec.fingerprint, programme.codec.fingerprint)
        self.assertEqual(typed.codec.fingerprint, RowCodec(TypedRow).fingerprint)
        self.assertTrue(typed.name.endswith(f"#{typed.codec.fingerprint}"))

        class Plain:
            pass

        self.assertNotIn("#", AsyncQueryCache(cast(Any, Plain)).name)


class DatabaseModelJsonTest(unittest.TestCase):
    """model_dump_json / model_validate_json share the cache's column codec."""

    def test_every_column_reads_back_with_its_own_type(self) -> None:
        values = typed_values()

        restored = TypedRow.model_validate_json(TypedRow(**values).model_dump_json())

        for key, expected in values.items():
            with self.subTest(column=key):
                actual = getattr(restored, key)
                self.assertEqual(expected, actual)
                self.assertIs(type(expected), type(actual))

    def test_relationships_and_unloaded_columns_are_left_out(self) -> None:
        row = ProgrammeRow(id=3, channel_id=1, title="news")
        row.channel = ChannelRow(id=1, name="one")

        self.assertEqual({"id": 3, "channel_id": 1, "title": "news"}, row.model_dump_dict())

    def test_a_key_that_is_not_a_column_is_refused(self) -> None:
        with self.assertRaises(TypeError):
            ProgrammeRow.model_validate_json('{"id": 3, "channel": {"id": 1}}')


class ModelCacheTestCase(unittest.IsolatedAsyncioTestCase):
    """A test-owned redis-server and an SQLite file the process's db_manager points at."""

    tables: tuple[Table, ...] = tuple(
        cast(Table, model.__table__)
        for model in (
            TypedRow,
            ChannelRow,
            ProgrammeRow,
            LookupRow,
            ShapeKeyRow,
            SlotKeyRow,
            NoticeRow,
            CascadeChannelRow,
            CascadeProgrammeRow,
            TreeRow,
            ChainRootRow,
            ChainMiddleRow,
            ChainLeafRow,
        )
    )
    _directory: ClassVar[tempfile.TemporaryDirectory[str]]
    _redis: ClassVar[RedisProcess]

    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory()
        cls._redis = RedisProcess(require_redis_server(), Path(cls._directory.name), "model_cache")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._redis.stop()
        cls._directory.cleanup()

    async def asyncSetUp(self) -> None:
        settings = DefaultSettings()
        settings.core.namespace = "mc_test"
        self.enterContext(patch.dict(conf.__dict__, {"settings": settings}))
        self.registry = RedisClientRegistry(owned_redis_config(self._redis.socket_path, {"CACHE": 0}))
        self.enterContext(patch("oldman.db.sqlalchemy.cache.redis_client", self.registry))
        self.redis = await self.registry.using("CACHE").async_get_conn()
        await self.redis.flushdb()

        path = Path(self._directory.name) / f"{self._testMethodName}.db"
        self.database = DatabaseManager(DatabaseConfig(url=f"sqlite+aiosqlite:///{path.as_posix()}", echo=False))
        await self.database.initialize()
        async with self.database.engine.begin() as connection:
            await connection.run_sync(DatabaseModel.metadata.create_all, tables=list(self.tables))
        self.enterContext(patch("oldman.db.session.db_manager", self.database))

        self.fills = 0
        fill_session = self.database.cache_fill_session

        @asynccontextmanager
        async def counted_fill_session() -> AsyncIterator[AsyncSession]:
            self.fills += 1
            async with fill_session() as session:
                yield session

        self.enterContext(patch.object(self.database, "cache_fill_session", counted_fill_session))

    @asynccontextmanager
    async def sessions(self) -> AsyncIterator[AsyncSession]:
        """An ordinary session on the test database, as a caller would hold."""
        session = AsyncSession(self.database.engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    async def asyncTearDown(self) -> None:
        await settle()
        await self.database.close()
        await self.registry.close()

    async def add(self, *rows: Any) -> None:
        """Commit the rows and wait for their invalidation, so the next read is not the post-commit bypass."""
        async with self.sessions() as session:
            session.add_all(rows)
            await session.commit()
        await settle()

    async def seed_programmes(self) -> None:
        await self.add(ChannelRow(id=5, name="five"), ChannelRow(id=6, name="six"))
        await self.add(
            ProgrammeRow(id=1, channel_id=5, title="news", starts_at=at(19)),
            ProgrammeRow(id=2, channel_id=6, title="film", starts_at=at(20)),
        )

    async def titles(self, *conditions: Any) -> list[str]:
        async with self.sessions() as session:
            rows = await ProgrammeRow.cached_filter(session, *conditions)
        assert isinstance(rows, list)
        return sorted(row.title for row in rows)


class CachedRowTypesTest(ModelCacheTestCase):
    async def test_a_cache_hit_returns_the_types_a_database_read_returns(self) -> None:
        """Datetimes read back from the cache used to arrive as ISO strings."""
        await self.add(TypedRow(**typed_values(1)))
        async with self.sessions() as session:
            from_database = (await session.execute(select(TypedRow))).scalar_one()
            expected = {key: getattr(from_database, key) for key in typed_values()}

        async with self.sessions() as session:
            for call in ("filter", "get", "get_many"):
                for attempt in ("miss", "hit"):
                    row: Any
                    if call == "filter":
                        rows = await TypedRow.cached_filter(session, TypedRow.id == 1)
                        assert isinstance(rows, list)
                        row = rows[0]
                    elif call == "get":
                        row = await TypedRow.cached_get(session, id=1)
                    else:
                        row = (await TypedRow.cached_get_many(session, [1]))[1]
                    with self.subTest(call=call, attempt=attempt):
                        self.assertTrue(instance_state(row).detached)
                        for key, value in expected.items():
                            self.assertEqual(value, getattr(row, key), key)
                            self.assertIs(type(value), type(getattr(row, key)), key)
        self.assertEqual(3, self.fills, "each kind of lookup fills once and then hits")


class QueryInvalidationTest(ModelCacheTestCase):
    async def test_an_inserted_row_reaches_a_cached_query(self) -> None:
        """E-8: an insert used to leave cached queries showing the old result for the whole TTL."""
        await self.seed_programmes()
        self.assertEqual(["news"], await self.titles(ProgrammeRow.channel_id == 5))

        await self.add(ProgrammeRow(id=3, channel_id=5, title="late news", starts_at=at(23)))
        await settle()

        self.assertEqual(["late news", "news"], await self.titles(ProgrammeRow.channel_id == 5))

    async def test_a_row_moved_into_the_condition_reaches_a_cached_query(self) -> None:
        """E-8b: a row that newly matched a cached query was invisible to it."""
        await self.seed_programmes()
        self.assertEqual(["news"], await self.titles(ProgrammeRow.channel_id == 5))
        self.assertEqual(["film"], await self.titles(ProgrammeRow.channel_id == 6))

        async with self.sessions() as session:
            film = await session.get(ProgrammeRow, 2)
            assert film is not None
            film.channel_id = 5
            await session.commit()
        await settle()

        self.assertEqual(["film", "news"], await self.titles(ProgrammeRow.channel_id == 5))
        self.assertEqual([], await self.titles(ProgrammeRow.channel_id == 6))

    async def test_a_write_to_another_partition_leaves_the_cached_query_a_hit(self) -> None:
        await self.seed_programmes()
        in_five = (ProgrammeRow.channel_id == 5, ProgrammeRow.starts_at >= at(18))
        await self.titles(*in_five)
        await self.titles(ProgrammeRow.title == "news")  # no partition: any write to the model
        fills = self.fills

        async with self.sessions() as session:
            film = await session.get(ProgrammeRow, 2)
            assert film is not None
            film.title = "film, restored"
            await session.commit()
        await settle()

        self.assertEqual(["news"], await self.titles(*in_five))
        self.assertEqual(fills, self.fills, "channel 6 changed; the channel 5 query stays a hit")
        self.assertEqual(["news"], await self.titles(ProgrammeRow.title == "news"))
        self.assertEqual(fills + 1, self.fills, "a query without a partition is refilled after any write")

    async def test_boolean_partitions_are_recognised_as_they_are_usually_written(self) -> None:
        """G3-10: only `flag == bindparam(...)` counted, so `flag == True`, `flag.is_(True)` or a bare `flag` was refilled by any write."""
        await self.add(NoticeRow(id=1, published=True, title="live"), NoticeRow(id=2, published=False, title="draft"))
        spellings: dict[bool, dict[str, Any]] = {
            True: {"== True": NoticeRow.published == True, "is_(True)": NoticeRow.published.is_(True), "bare": NoticeRow.published},  # noqa: E712
            False: {"== False": NoticeRow.published == False, "is_(False)": NoticeRow.published.is_(False), "negated": ~NoticeRow.published},  # noqa: E712
        }

        async def titles(condition: Any) -> list[str]:
            async with self.sessions() as session:
                return sorted(row.title for row in cast(list[Any], await NoticeRow.cached_filter(session, condition)))

        for published, conditions in spellings.items():
            before = {spelling: await titles(condition) for spelling, condition in conditions.items()}
            self.assertEqual([1] * len(conditions), [len(found) for found in before.values()], "each spelling finds the one row of its partition")
            fills = self.fills
            async with self.sessions() as session:
                other = await session.get(NoticeRow, 2 if published else 1)
                assert other is not None
                other.title = f"{other.title}, edited"
                await session.commit()
            await settle()
            for spelling, condition in conditions.items():
                with self.subTest(published=published, spelling=spelling):
                    self.assertEqual(before[spelling], await titles(condition))
            self.assertEqual(fills, self.fills, "a write to the other partition leaves these queries hits")

    async def test_a_deleted_row_leaves_cached_queries_and_lookups(self) -> None:
        await self.seed_programmes()
        await self.titles(ProgrammeRow.channel_id == 5)
        async with self.sessions() as session:
            self.assertEqual({1}, set(await ProgrammeRow.cached_get_many(session, [1])))

        async with self.sessions() as session:
            news = await session.get(ProgrammeRow, 1)
            await session.delete(news)
            await session.commit()
        await settle()

        self.assertEqual([], await self.titles(ProgrammeRow.channel_id == 5))
        async with self.sessions() as session:
            self.assertEqual({}, await ProgrammeRow.cached_get_many(session, [1]))

    async def test_a_generation_lost_from_redis_turns_into_a_miss_never_old_data(self) -> None:
        """Eviction or expiry recreates a generation at a new random value, so nothing cached against the old one matches."""
        await self.seed_programmes()
        self.assertEqual(["news"], await self.titles(ProgrammeRow.channel_id == 5))
        async with self.database.engine.begin() as connection:
            await connection.execute(text("UPDATE mc_programme SET title = 'renamed outside' WHERE id = 1"))
        generations = await self.redis.keys("*model_cache:gen:*")
        self.assertTrue(generations)
        await self.redis.delete(*generations)

        self.assertEqual(["renamed outside"], await self.titles(ProgrammeRow.channel_id == 5))


class RowInvalidationTest(ModelCacheTestCase):
    async def test_cached_rows_follow_updates(self) -> None:
        await self.seed_programmes()
        async with self.sessions() as session:
            await ProgrammeRow.cached_get_many(session, [1, 2])
            await ProgrammeRow.cached_get(session, id=1)

        async with self.sessions() as session:
            news = await session.get(ProgrammeRow, 1)
            assert news is not None
            news.title = "evening news"
            await session.commit()
        await settle()

        async with self.sessions() as session:
            many = await ProgrammeRow.cached_get_many(session, [1, 2])
            one = await ProgrammeRow.cached_get(session, id=1)
        assert one is not None
        self.assertEqual(("evening news", "film"), (many[1].title, many[2].title))
        self.assertEqual("evening news", one.title)

    async def test_a_field_lookup_follows_the_row_it_found(self) -> None:
        await self.add(LookupRow(id=10, email="a@example.test"))
        async with self.sessions() as session:
            found = await LookupRow.cached_get(session, email="a@example.test")
        assert found is not None

        async with self.sessions() as session:
            row = await session.get(LookupRow, 10)
            assert row is not None
            row.email = "b@example.test"
            await session.commit()
        await settle()

        async with self.sessions() as session:
            self.assertIsNone(await LookupRow.cached_get(session, email="a@example.test"))
            moved = await LookupRow.cached_get(session, email="b@example.test")
        assert moved is not None
        self.assertEqual(10, moved.id)

    async def test_field_lookups_on_different_columns_return_their_own_rows(self) -> None:
        """E-10: field keys kept two letters of each name, so employee_id=5 was served email=5's row."""
        await self.add(LookupRow(id=10, email="5"), LookupRow(id=11, employee_id="5"))
        async with self.sessions() as session:
            by_email = await LookupRow.cached_get(session, email="5")
            by_employee_id = await LookupRow.cached_get(session, employee_id="5")
        assert by_email is not None and by_employee_id is not None
        self.assertEqual((10, 11), (by_email.id, by_employee_id.id))

    async def test_a_lookup_by_an_enum_member_and_one_by_its_value_answer_as_the_database_does(self) -> None:
        """G3-8: JSON writes a member as its value, so shape="s" was served the row cached for Shape.SQUARE."""
        await self.add(TypedRow(**typed_values(1)))
        async with self.sessions() as session:
            for shape in (Shape.SQUARE, "s", Shape.SQUARE, "s"):
                with self.subTest(shape=shape):
                    cached = await TypedRow.cached_get(session, shape=shape)
                    direct = await TypedRow.cached_get(session, shape=shape, use_cache=False)
                    self.assertEqual(getattr(direct, "id", None), getattr(cached, "id", None))

    async def test_cached_get_many_keys_rows_as_the_caller_asked_on_every_path(self) -> None:
        """G3-14: a hit came back under the caller's "1", a miss under the database's 1."""
        await self.seed_programmes()
        async with self.sessions() as session:
            miss = await ProgrammeRow.cached_get_many(session, ["1"])
            hit = await ProgrammeRow.cached_get_many(session, ["1"])
            news = await session.get(ProgrammeRow, 1)
            assert news is not None
            news.title = "draft"
            bypass = await ProgrammeRow.cached_get_many(session, ["1"])
            await session.rollback()

        for path, rows in (("miss", miss), ("hit", hit), ("bypass", bypass)):
            with self.subTest(path=path):
                self.assertEqual(["1"], list(rows))
        self.assertEqual(["news", "news", "draft"], [rows["1"].title for rows in (miss, hit, bypass)])

    async def assert_writes_reach_the_cached_row(self, model: Any, key: str, pk: Any) -> None:
        await self.add(model(**{key: pk, "label": "old"}))
        async with self.sessions() as session:
            await model.cached_get(session, **{key: pk})
            await model.cached_get_many(session, [pk])

        async with self.sessions() as session:
            row = await session.get(model, pk)
            assert row is not None
            row.label = "new"
            await session.commit()
        await settle()
        async with self.sessions() as session:
            one = await model.cached_get(session, **{key: pk})
            many = await model.cached_get_many(session, [pk])
        self.assertEqual(("new", ["new"]), (getattr(one, "label", None), [row.label for row in many.values()]))

        async with self.sessions() as session:
            await session.delete(await session.get(model, pk))
            await session.commit()
        await settle()
        async with self.sessions() as session:
            self.assertIsNone(await model.cached_get(session, **{key: pk}))
            self.assertEqual({}, await model.cached_get_many(session, [pk]))

    async def test_writes_reach_rows_cached_under_an_enum_primary_key(self) -> None:
        """G3-2: the write advanced row:Shape.ROUND while the lookup's entry depended on row:ROUND."""
        await self.assert_writes_reach_the_cached_row(ShapeKeyRow, "shape", Shape.ROUND)

    async def test_writes_reach_rows_cached_under_a_datetime_primary_key(self) -> None:
        await self.assert_writes_reach_the_cached_row(SlotKeyRow, "starts_at", at(19))


class TransactionTest(ModelCacheTestCase):
    async def test_bulk_statements_invalidate_through_invalidate_cache_on_commit(self) -> None:
        """Bulk update() fires no mapper event; the transaction says so itself."""
        await self.seed_programmes()
        self.assertEqual(["news"], await self.titles(ProgrammeRow.channel_id == 5))

        async with self.sessions() as session:
            await session.execute(update(ProgrammeRow).where(ProgrammeRow.channel_id == 5).values(title="bulk"))
            ProgrammeRow.invalidate_cache_on_commit(session)
            await session.commit()
        await settle()

        self.assertEqual(["bulk"], await self.titles(ProgrammeRow.channel_id == 5))

    async def test_a_rolled_back_transaction_invalidates_nothing(self) -> None:
        await self.seed_programmes()
        await self.titles(ProgrammeRow.channel_id == 5)
        fills = self.fills

        async with self.sessions() as session:
            session.add(ProgrammeRow(id=3, channel_id=5, title="never", starts_at=at(22)))
            await session.flush()
            ProgrammeRow.invalidate_cache_on_commit(session)
            await session.rollback()
        await settle()

        self.assertEqual(["news"], await self.titles(ProgrammeRow.channel_id == 5))
        self.assertEqual(fills, self.fills)

    async def test_a_savepoint_rollback_keeps_the_invalidation_of_the_writes_that_commit(self) -> None:
        """Rolling back a savepoint used to discard every queued invalidation of the transaction."""
        await self.seed_programmes()
        self.assertEqual(["news"], await self.titles(ProgrammeRow.channel_id == 5))

        async with self.sessions() as session:
            session.add(ProgrammeRow(id=3, channel_id=5, title="kept", starts_at=at(22)))
            await session.flush()
            savepoint = await session.begin_nested()
            session.add(ProgrammeRow(id=4, channel_id=5, title="undone", starts_at=at(23)))
            await session.flush()
            await savepoint.rollback()
            await session.commit()
        await settle()

        self.assertEqual(["kept", "news"], await self.titles(ProgrammeRow.channel_id == 5))

    async def test_an_uncommitted_enum_assigned_by_name_reads_back_as_the_member(self) -> None:
        """G3-4: SQLAlchemy takes a member's name for an enum column; the bypass snapshot used to fail on the string."""
        await self.add(TypedRow(**typed_values(1)))
        async with self.sessions() as session:
            row = await session.get(TypedRow, 1)
            assert row is not None
            row.shape = cast(Any, "ROUND")
            seen = await TypedRow.cached_get(session, id=1)
            await session.rollback()

        self.assertIs(Shape.ROUND, getattr(seen, "shape", None))

    async def test_uncommitted_changes_are_read_through_the_callers_session_and_never_stored(self) -> None:
        await self.seed_programmes()
        await self.titles(ProgrammeRow.channel_id == 5)
        fills = self.fills

        async with self.sessions() as session:
            news = await session.get(ProgrammeRow, 1)
            assert news is not None
            news.title = "draft"
            seen = await ProgrammeRow.cached_filter(session, ProgrammeRow.channel_id == 5)
            assert isinstance(seen, list)
            self.assertEqual(["draft"], [row.title for row in seen])
            await session.rollback()

        self.assertEqual(["news"], await self.titles(ProgrammeRow.channel_id == 5))
        self.assertEqual(fills, self.fills, "the draft was never stored, the earlier entry still serves")

    async def test_this_process_reads_its_own_commit_before_the_invalidation_lands(self) -> None:
        await self.seed_programmes()
        self.assertEqual(["news"], await self.titles(ProgrammeRow.channel_id == 5))
        release = asyncio.Event()
        bump = model_cache._bump

        async def held_bump(keys: Any) -> None:
            await release.wait()
            await bump(keys)

        with patch.object(model_cache, "_bump", held_bump):
            async with self.sessions() as session:
                news = await session.get(ProgrammeRow, 1)
                assert news is not None
                news.title = "just committed"
                await session.commit()
            self.assertTrue(model_cache._pending_invalidations)
            self.assertEqual(["just committed"], await self.titles(ProgrammeRow.channel_id == 5))
            release.set()
            await settle()

        self.assertEqual(["just committed"], await self.titles(ProgrammeRow.channel_id == 5))

    async def test_invalidate_cache_drops_everything_of_the_model_now(self) -> None:
        """Raw SQL is invisible to the cache until someone says so."""
        await self.seed_programmes()
        self.assertEqual(["news"], await self.titles(ProgrammeRow.channel_id == 5))
        async with self.database.engine.begin() as connection:
            await connection.execute(text("UPDATE mc_programme SET title = 'raw' WHERE id = 1"))
        self.assertEqual(["news"], await self.titles(ProgrammeRow.channel_id == 5))

        await ProgrammeRow.invalidate_cache()

        self.assertEqual(["raw"], await self.titles(ProgrammeRow.channel_id == 5))

    async def test_closing_a_session_without_commit_or_rollback_forgets_its_writes(self) -> None:
        """close() ends the transaction like a rollback; its records used to stay, and every later read on the session bypassed the cache."""
        await self.seed_programmes()
        self.assertEqual(["news"], await self.titles(ProgrammeRow.channel_id == 5))
        manager = ProgrammeRow.get_cache_manager()

        async with self.sessions() as session:
            news = await session.get(ProgrammeRow, 1)
            assert news is not None
            news.title = "abandoned"
            await session.flush()
            await session.close()
            before = manager.stats
            rows = await ProgrammeRow.cached_filter(session, ProgrammeRow.channel_id == 5)
            after = manager.stats

        self.assertEqual(["news"], [row.title for row in cast(list[Any], rows)])
        self.assertEqual((1, 0), (after.hits - before.hits, after.bypassed - before.bypassed))


class SavepointTest(ModelCacheTestCase):
    """Savepoints as PostgreSQL and MySQL run them.

    pysqlite and aiosqlite emit no BEGIN before a SAVEPOINT, so on SQLite a released savepoint
    commits at once and hid G3-1. These tests apply the SQLAlchemy SQLite dialect recipe to the
    callers' engine: BEGIN is emitted by the engine, and RELEASE commits nothing.
    """

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        engine = self.database.engine.sync_engine

        def connect(dbapi_connection: Any, _record: Any) -> None:
            dbapi_connection.isolation_level = None

        def begin(connection: Any) -> None:
            connection.exec_driver_sql("BEGIN")

        event.listen(engine, "connect", connect)
        event.listen(engine, "begin", begin)
        await self.database.engine.dispose()

    async def rename_in_savepoints(self, depth: int) -> None:
        """Rename programme 1 inside `depth` savepoints; another request reads between their release and the commit."""
        async with self.sessions() as writer:
            news = await writer.get(ProgrammeRow, 1)
            assert news is not None
            async with AsyncExitStack() as savepoints:
                for _ in range(depth):
                    await savepoints.enter_async_context(writer.begin_nested())
                news.title = "renamed"
            # Anything the release started lands first; the reader may then store what the database still holds.
            await settle()
            self.assertEqual(["news"], await self.titles(ProgrammeRow.channel_id == 5))
            await writer.commit()
        await settle()

    async def test_a_released_savepoint_invalidates_when_the_transaction_commits(self) -> None:
        """Releasing a savepoint fires after_commit; the invalidation used to start then, before the data was committed."""
        await self.seed_programmes()
        self.assertEqual(["news"], await self.titles(ProgrammeRow.channel_id == 5))

        await self.rename_in_savepoints(1)

        self.assertEqual(["renamed"], await self.titles(ProgrammeRow.channel_id == 5))
        async with self.sessions() as session:
            row = await ProgrammeRow.cached_get(session, id=1)
        self.assertEqual("renamed", getattr(row, "title", None))

    async def test_nested_savepoints_invalidate_when_the_transaction_commits(self) -> None:
        await self.seed_programmes()
        self.assertEqual(["news"], await self.titles(ProgrammeRow.channel_id == 5))

        await self.rename_in_savepoints(2)

        self.assertEqual(["renamed"], await self.titles(ProgrammeRow.channel_id == 5))

    async def test_the_writer_reads_its_released_savepoint_through_its_own_session(self) -> None:
        await self.seed_programmes()
        self.assertEqual(["news"], await self.titles(ProgrammeRow.channel_id == 5))

        async with self.sessions() as writer:
            news = await writer.get(ProgrammeRow, 1)
            assert news is not None
            async with writer.begin_nested():
                news.title = "renamed"
            await settle()
            seen = await ProgrammeRow.cached_filter(writer, ProgrammeRow.channel_id == 5)
            await writer.rollback()

        self.assertEqual(["renamed"], [row.title for row in cast(list[Any], seen)])

    async def test_a_failed_flush_inside_a_savepoint_keeps_the_invalidation_of_the_outer_writes(self) -> None:
        """The failed flush rolls back its own subtransaction, which is not nested; that used to drop every record of the transaction."""
        await self.seed_programmes()
        self.assertEqual(["news"], await self.titles(ProgrammeRow.channel_id == 5))

        async with self.sessions() as writer:
            news = await writer.get(ProgrammeRow, 1)
            assert news is not None
            news.title = "renamed"
            await writer.flush()
            with self.assertRaises(IntegrityError):
                async with writer.begin_nested():
                    writer.add(ProgrammeRow(id=2, channel_id=5, title="duplicate", starts_at=at(21)))
                    await writer.flush()
            await writer.commit()
        await settle()

        self.assertEqual(["renamed"], await self.titles(ProgrammeRow.channel_id == 5))


class CascadeTest(ModelCacheTestCase):
    def test_a_database_cascade_must_name_its_target(self) -> None:
        class UndeclaredCascade(CacheableModel):
            __tablename__ = "mc_undeclared_cascade"
            id: Mapped[int] = mapped_column(primary_key=True)
            channel_id: Mapped[int] = mapped_column(ForeignKey("mc_cascade_channel.id", ondelete="SET NULL"), nullable=True)

        with self.assertRaises(TypeError):
            cached_model()(UndeclaredCascade)

    def test_every_table_up_a_cascade_chain_must_be_named(self) -> None:
        """Only naming the middle table misses the root: deleting it takes the middle rows, and theirs with them."""

        class HalfDeclaredLeaf(CacheableModel):
            __tablename__ = "mc_half_declared_leaf"
            id: Mapped[int] = mapped_column(primary_key=True)
            middle_id: Mapped[int] = mapped_column(ForeignKey("mc_chain_middle.id", ondelete="CASCADE"))

        with self.assertRaisesRegex(TypeError, "mc_chain_root"):
            cached_model(invalidate_on=(ChainMiddleRow,))(HalfDeclaredLeaf)

    def test_the_cascade_walk_follows_the_chain_and_refuses_what_it_cannot_see(self) -> None:
        metadata = MetaData()
        Table("root", metadata, Column("id", Integer, primary_key=True))
        Table("plain", metadata, Column("id", Integer, primary_key=True))
        Table(
            "middle",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("root_id", ForeignKey("root.id", ondelete="SET NULL")),
            Column("parent_id", ForeignKey("middle.id", ondelete="CASCADE")),  # itself: walked once
        )
        leaf = Table(
            "leaf",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("middle_id", ForeignKey("middle.id", onupdate="CASCADE")),
            Column("plain_id", ForeignKey("plain.id")),  # no database action: not a dependency
        )

        targets = {(source, target) for source, _, _, target in model_cache._database_cascades(leaf)}

        self.assertEqual({("leaf", "middle"), ("middle", "root"), ("middle", "middle")}, targets)
        Table("orphan", metadata, Column("id", Integer, primary_key=True), Column("later_id", ForeignKey("later.id", ondelete="CASCADE")))
        with self.assertRaisesRegex(TypeError, "not defined yet"):
            model_cache._database_cascades(metadata.tables["orphan"])

    async def test_rows_deleted_two_cascades_away_leave_the_cache(self) -> None:
        await self.add(ChainRootRow(id=1))
        await self.add(ChainMiddleRow(id=1, root_id=1))
        await self.add(ChainLeafRow(id=1, middle_id=1, title="leaf"))
        async with self.sessions() as session:
            cached = await ChainLeafRow.cached_filter(session, ChainLeafRow.middle_id == 1)
            self.assertEqual(["leaf"], [row.title for row in cast(list[Any], cached)])

        async with self.sessions() as session:
            await session.delete(await session.get(ChainRootRow, 1))
            await session.commit()
        await settle()

        async with self.sessions() as session:
            self.assertEqual([], await ChainLeafRow.cached_filter(session, ChainLeafRow.middle_id == 1))

    async def test_rows_deleted_by_a_cascade_into_their_own_table_leave_the_cache(self) -> None:
        """G3-11: only the node the ORM deleted was invalidated; its subtree, deleted by the database, stayed cached."""
        await self.add(TreeRow(id=1, parent_id=None, title="root"))
        await self.add(TreeRow(id=2, parent_id=1, title="leaf"))
        async with self.sessions() as session:
            self.assertEqual("leaf", getattr(await TreeRow.cached_get(session, id=2), "title", None))

        async with self.sessions() as session:
            await session.delete(await session.get(TreeRow, 1))
            await session.commit()
        await settle()

        async with self.sessions() as session:
            self.assertIsNone(await TreeRow.cached_get(session, id=2))

    async def test_rows_the_database_deletes_by_cascade_leave_the_cache(self) -> None:
        await self.add(CascadeChannelRow(id=1, name="one"))
        await self.add(CascadeProgrammeRow(id=1, channel_id=1, title="news"))
        async with self.sessions() as session:
            cached = await CascadeProgrammeRow.cached_filter(session, CascadeProgrammeRow.channel_id == 1)
            self.assertEqual(["news"], [row.title for row in cast(list[Any], cached)])

        async with self.sessions() as session:
            channel = await session.get(CascadeChannelRow, 1)
            await session.delete(channel)
            await session.commit()
        await settle()

        async with self.sessions() as session:
            self.assertEqual([], await CascadeProgrammeRow.cached_filter(session, CascadeProgrammeRow.channel_id == 1))


class BoundaryTest(ModelCacheTestCase):
    async def test_statements_the_cache_cannot_serve_are_refused(self) -> None:
        await self.seed_programmes()
        manager = ProgrammeRow.get_cache_manager()
        refused = {
            "reads another table": select(ProgrammeRow).join(ChannelRow).where(ChannelRow.name == "five"),
            "selects columns": select(ProgrammeRow.id),
            "locks": select(ProgrammeRow).with_for_update(),
            "loads a relationship": select(ProgrammeRow).options(selectinload(ProgrammeRow.channel)),
            "loads some columns only": select(ProgrammeRow).options(load_only(ProgrammeRow.id)),
            # G3-7: the statement's cache key has the parameter, not what the callable returns.
            "computes a parameter": select(ProgrammeRow).where(ProgrammeRow.id == bindparam("chosen", callable_=lambda: 1)),
        }
        async with self.sessions() as session:
            for reason, statement in refused.items():
                with self.subTest(reason=reason), self.assertRaises(ValueError):
                    await manager.execute_query(session, cast(Any, statement))

    async def test_use_cache_false_is_an_ordinary_query_and_the_switch_is_keyword_only(self) -> None:
        await self.seed_programmes()
        manager = ProgrammeRow.get_cache_manager()
        async with self.sessions() as session:
            rows = cast(list[ProgrammeRow], await ProgrammeRow.cached_filter(session, ProgrammeRow.channel_id == 5, use_cache=False))
            one = await ProgrammeRow.cached_get(session, id=1, use_cache=False)
            many = await ProgrammeRow.cached_get_many(session, [1], use_cache=False)
            queried = cast(list[ProgrammeRow], await manager.execute_query(session, select(ProgrammeRow), use_cache=False))
            for row in (*rows, one, *many.values(), *queried):
                self.assertIn(row, session, "use_cache=False returns the caller's own session objects")
            # A positional True would otherwise be taken as the lookup's first condition or page;
            # called through Any, since type checkers already refuse these calls.
            untyped_model, untyped_manager = cast(Any, ProgrammeRow), cast(Any, manager)
            for call in (
                lambda: untyped_model.cached_get(session, True),
                lambda: untyped_model.cached_get_many(session, [1], True),
                lambda: untyped_manager.execute_query(session, select(ProgrammeRow), None, None, True),
            ):
                with self.assertRaises(TypeError):
                    await call()
        self.assertEqual(0, self.fills)

    async def test_stats_count_how_each_entry_was_served(self) -> None:
        await self.seed_programmes()
        manager = ProgrammeRow.get_cache_manager()
        before = manager.stats

        await self.titles(ProgrammeRow.channel_id == 5)  # miss
        await self.titles(ProgrammeRow.channel_id == 5)  # hit
        async with self.sessions() as session:
            await ProgrammeRow.cached_get_many(session, [1, 2])  # two misses
            await ProgrammeRow.cached_get_many(session, [1, 2])  # two hits
            await ProgrammeRow.cached_filter(session, ProgrammeRow.channel_id == 5, use_cache=False)  # not counted
            first = await session.get(ProgrammeRow, 1)
            assert first is not None
            first.title = "uncommitted"
            await ProgrammeRow.cached_get(session, id=1)  # bypassed: this session changed the model
            await session.rollback()
        with patch.object(model_cache, "_cache_redis_connection", side_effect=ConnectionError("redis down")):
            await self.titles(ProgrammeRow.channel_id == 5)  # fallback

        after = manager.stats
        self.assertEqual(
            (3, 3, 1, 1),
            (after.hits - before.hits, after.misses - before.misses, after.bypassed - before.bypassed, after.fallbacks - before.fallbacks),
        )

    async def test_a_session_on_another_database_is_refused(self) -> None:
        other = create_async_engine(f"sqlite+aiosqlite:///{self._directory.name}/{self._testMethodName}-other.db")
        session = AsyncSession(other)
        try:
            with self.assertRaises(ValueError):
                await ProgrammeRow.cached_filter(session, ProgrammeRow.channel_id == 5)
        finally:
            await session.close()
            await other.dispose()

    async def test_only_sessions_that_write_a_cached_model_get_a_listener(self) -> None:
        async with self.sessions() as session:
            session.add(ChannelRow(id=7, name="seven"))
            await session.commit()
            self.assertNotIn(model_cache._LISTENING, session.sync_session.info)
            session.add(ProgrammeRow(id=7, channel_id=7, title="x", starts_at=at(1)))
            await session.commit()
            self.assertIn(model_cache._LISTENING, session.sync_session.info)

    async def test_redis_failure_falls_back_to_the_database(self) -> None:
        await self.seed_programmes()
        with patch.object(model_cache, "_cache_redis_connection", side_effect=ConnectionError("redis down")):
            self.assertEqual(["news"], await self.titles(ProgrammeRow.channel_id == 5))
            async with self.sessions() as session:
                self.assertEqual({1}, set(await ProgrammeRow.cached_get_many(session, [1])))
                found = await ProgrammeRow.cached_get(session, id=1)
        assert found is not None

    async def test_without_a_cache_connection_in_time_the_read_goes_to_the_database_unstored(self) -> None:
        await self.seed_programmes()

        @asynccontextmanager
        async def exhausted() -> AsyncIterator[AsyncSession]:
            raise PoolTimeoutError("QueuePool limit reached")
            yield cast(AsyncSession, None)  # pragma: no cover -- makes this an async generator

        with patch.object(self.database, "cache_fill_session", exhausted):
            self.assertEqual(["news"], await self.titles(ProgrammeRow.channel_id == 5))
        fills = self.fills
        self.assertEqual(["news"], await self.titles(ProgrammeRow.channel_id == 5))
        self.assertEqual(fills + 1, self.fills, "nothing was stored while the pool was exhausted")

    async def test_a_commit_outside_the_event_loop_logs_that_it_cannot_invalidate(self) -> None:
        """A synchronous commit in another thread has no loop to invalidate on: logged, and no count left behind."""
        await self.seed_programmes()
        engine = create_engine(f"sqlite:///{self._directory.name}/{self._testMethodName}.db")

        def commit_in_a_thread() -> None:
            with Session(engine) as session:
                session.add(ProgrammeRow(id=3, channel_id=5, title="x", starts_at=at(1)))
                session.commit()

        try:
            with self.assertLogs("default", level="ERROR") as logs:
                await asyncio.to_thread(commit_in_a_thread)
        finally:
            engine.dispose()
        self.assertIn("cannot invalidate", "".join(logs.output))
        self.assertFalse(model_cache._pending_invalidations)
        self.assertFalse(model_cache._invalidation_tasks)

    async def test_wait_for_invalidations_returns_once_the_commit_reached_redis(self) -> None:
        """What a script or a stopping service awaits so that leaving the loop cannot cancel an invalidation."""
        await self.seed_programmes()
        self.assertEqual(["news"], await self.titles(ProgrammeRow.channel_id == 5))
        key = ProgrammeRow.get_cache_manager()._generation_key("any")
        before = await self.redis.get(key)

        async with self.sessions() as session:
            session.add(ProgrammeRow(id=3, channel_id=5, title="late", starts_at=at(1)))
            await session.commit()
        self.assertTrue(model_cache._invalidation_tasks, "the task is held until it ends")
        await model_cache.wait_for_invalidations()

        self.assertFalse(model_cache._invalidation_tasks)
        self.assertNotEqual(before, await self.redis.get(key))
        self.assertEqual(["late", "news"], await self.titles(ProgrammeRow.channel_id == 5))

    async def test_wait_for_invalidations_also_ends_the_post_commit_bypass(self) -> None:
        """A finished invalidation is uncounted by its done callback, one loop turn later; returning before that left reads bypassing."""
        await self.seed_programmes()
        release = asyncio.Event()

        async def held_bump(keys: Any) -> None:
            await release.wait()

        with patch.object(model_cache, "_bump", held_bump):
            async with self.sessions() as session:
                session.add(ProgrammeRow(id=3, channel_id=5, title="late", starts_at=at(1)))
                await session.commit()
            [task] = model_cache._invalidation_tasks
            release.set()
            while not task.done():
                await asyncio.sleep(0)
            self.assertTrue(model_cache._pending_invalidations, "the done callback has not run yet")

            await model_cache.wait_for_invalidations()

        self.assertFalse(model_cache._pending_invalidations)


if __name__ == "__main__":
    unittest.main()
