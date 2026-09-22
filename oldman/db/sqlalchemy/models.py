"""
@author:alex
@date:2024/10/30
@time:12:31
"""

__author__ = "alex"

import uuid as uuid_pkg
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Self

from sqlalchemy import TIMESTAMP, Boolean, DateTime, Select, Uuid, func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.orm.strategy_options import _AbstractLoad
from sqlalchemy.sql.functions import FunctionElement
from uuid6 import uuid7

from oldman.db.schemas import PageResult
from oldman.serializers.base import ModelSerializer
from oldman.utils.date import naive_utcnow

# 时间戳的 server_default 必须按方言分发：「取当前时间」在 MySQL、PostgreSQL、SQLite 上
# 写法各不相同，而模型是在导入时定义的，那时还不知道会连到哪个库。以前这里写死成 MySQL，
# 于是 SQLite 上 current_timestamp(0) 连表都建不出来，utc_timestamp() 则在任何绕过 ORM 的
# 写入（裸 SQL、迁移回填、别的服务）上报 unknown function。SQLAlchemy 的 @compiles 正是
# 为此存在：同一个表达式，交给每种方言各自渲染。
#
# 注意 DEFAULT 里的表达式要带括号：MySQL 8.0.13+ 和 SQLite 都要求 DEFAULT (expr)，
# 只有裸关键字 CURRENT_TIMESTAMP 可以不带。


class utcnow(FunctionElement):
    """UTC 当前时间，不带时区信息。"""

    type = TIMESTAMP()
    inherit_cache = True


@compiles(utcnow)
def _utcnow_default(element: Any, compiler: Any, **kw: Any) -> str:
    """SQLite 的 CURRENT_TIMESTAMP 本来就是 UTC；未知方言按标准 SQL 兜底。"""
    return "CURRENT_TIMESTAMP"


@compiles(utcnow, "mysql")
def _utcnow_mysql(element: Any, compiler: Any, **kw: Any) -> str:
    return "(UTC_TIMESTAMP())"


@compiles(utcnow, "postgresql")
def _utcnow_postgresql(element: Any, compiler: Any, **kw: Any) -> str:
    return "(NOW() AT TIME ZONE 'utc')"


class localnow(FunctionElement):
    """数据库服务器本地时区的当前时间，不带时区信息。"""

    type = TIMESTAMP()
    inherit_cache = True


@compiles(localnow)
def _localnow_default(element: Any, compiler: Any, **kw: Any) -> str:
    """MySQL 与 PostgreSQL 的 CURRENT_TIMESTAMP 都取服务器本地时区。"""
    return "CURRENT_TIMESTAMP"


@compiles(localnow, "sqlite")
def _localnow_sqlite(element: Any, compiler: Any, **kw: Any) -> str:
    """SQLite 的 CURRENT_TIMESTAMP 固定是 UTC，要本地时区必须显式转换。"""
    return "(datetime('now', 'localtime'))"


class UUIDMixin:
    """UUIDv7 主键，值由 Python 端生成。

    原来这里还挂着 server_default=gen_random_uuid()，那是 PostgreSQL 专用函数，在 MySQL 和
    SQLite 上不存在；而且它产生的是 v4，和 Python 端的 uuid7 不是一种东西，同一列会混进两种
    UUID。uuid7 时间有序、更适合做主键，所以统一由它生成，不再交给数据库。
    """

    uuid: Mapped[uuid_pkg.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)


class NativeTimestampsMixin:
    """
    Mixin 定义时间戳的类, 使用是数据库服务器当前时区, 不包含时区信息.

    server_default 按方言渲染（见本模块的 localnow），MySQL、PostgreSQL、SQLite 都可用。
    """

    __abstract__ = True

    __created_at_name__ = "created_at"
    __updated_at_name__ = "updated_at"
    __server_default__ = localnow()

    created_at: Mapped[datetime] = mapped_column(
        __created_at_name__, TIMESTAMP(timezone=False), default=datetime.now, server_default=__server_default__, nullable=False
    )

    updated_at: Mapped[datetime | None] = mapped_column(
        __updated_at_name__,
        TIMESTAMP(timezone=False),
        default=datetime.now,
        onupdate=datetime.now,
        server_default=__server_default__,
        nullable=True,
    )


class UtcTimestampsMixin:
    """Mixin 定义时间戳的类, 使用是UTC时区, 不包含时区信息。

    server_default 按方言渲染（见本模块的 utcnow），MySQL、PostgreSQL、SQLite 都可用。
    """

    __abstract__ = True

    __created_at_name__ = "created_at"
    __updated_at_name__ = "updated_at"
    __server_default__ = utcnow()

    created_at: Mapped[datetime] = mapped_column(
        __created_at_name__,
        TIMESTAMP(timezone=False),
        default=naive_utcnow,
        server_default=__server_default__,
        nullable=False,
    )

    updated_at: Mapped[datetime | None] = mapped_column(
        __updated_at_name__,
        TIMESTAMP(timezone=False),
        default=naive_utcnow,
        onupdate=naive_utcnow,
        server_default=__server_default__,
        nullable=True,
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class Base(DeclarativeBase):
    """Base class for all database models"""

    @declared_attr.directive
    @classmethod
    def __tablename__(cls) -> str:
        return cls.__name__.lower()

    # @declared_attr
    # def __table_args__(cls):
    #     return {'extend_existing': True}

    # 通用的创建时间和更新时间字段
    # created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=server_default, nullable=False)
    # updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=server_default, onupdate=server_default, nullable=False)


class DatabaseModel(Base):
    """Abstract base class for all models with common CRUD operations"""

    __abstract__ = True

    def model_dump_json(self) -> str:
        # serialize(..., False) returns orjson bytes; str() on bytes yields its repr
        # ("b'{...}'"), which model_validate_json then cannot parse. Decode to real JSON
        # text so the round trip the ORM cache depends on actually holds.
        payload = ModelSerializer.serialize(self, False)
        if isinstance(payload, bytes):
            return payload.decode("utf-8")
        return str(payload)

    def model_dump_dict(self) -> dict:
        return ModelSerializer.serialize(self, True)  # type: ignore[return-value]

    @classmethod
    def model_validate_json(cls, data: str | bytes | dict) -> Self:
        if isinstance(data, str):
            data = data.encode()
        return ModelSerializer.deserialize(data, cls)

    @classmethod
    async def get_by_id(cls, session: AsyncSession, pk: Any) -> Self | None:
        primary_keys = inspect(cls).primary_key
        if len(primary_keys) != 1:
            raise ValueError("get_by_id only supports models with one primary key column")
        result = await session.execute(select(cls).where(primary_keys[0] == pk))
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_fields(cls, session: AsyncSession, options: Sequence[_AbstractLoad] | None = None, **kwargs) -> Self | None:
        """
        从数据库获取实例

        Args:
            session: 数据库会话
            options: 查询选项，例如 [noload(Users.group)]
            **kwargs: 查询条件
        """
        query = select(cls).filter_by(**kwargs)
        if options:
            query = query.options(*options)
        result = await session.execute(query)
        return result.scalar_one_or_none()

    @classmethod
    async def get_many_by_ids(cls, session: AsyncSession, ids: list[Any]) -> dict[Any, Self]:
        """从数据库批量获取实例"""
        if not ids:
            return {}
        primary_keys = inspect(cls).primary_key
        if len(primary_keys) != 1:
            raise ValueError("get_many_by_ids only supports models with one primary key column")
        primary_key = primary_keys[0]
        if primary_key.key is None:
            raise ValueError("primary key column must have a key")
        result = await session.execute(select(cls).where(primary_key.in_(ids)))
        instances = result.scalars().all()
        return {getattr(instance, primary_key.key): instance for instance in instances}

    @classmethod
    async def get_many(cls, session: AsyncSession, **kwargs) -> Sequence[Self]:
        result = await session.execute(select(cls).filter_by(**kwargs))
        return result.scalars().all()

    @classmethod
    async def execute_query(
        cls,
        session: AsyncSession,
        *conditions,
        page: int | None = None,
        page_size: int | None = None,
    ) -> list[Self] | PageResult:
        """从数据库执行查询"""
        query = select(cls).filter(*conditions)
        return await cls.execute_query_with_select(session, query, page, page_size)

    @classmethod
    async def execute_query_with_select(
        cls,
        session: AsyncSession,
        query: Select,
        page: int | None = None,
        page_size: int | None = None,
    ) -> list[Self] | PageResult:
        """从数据库执行查询"""
        if page is None or page_size is None:
            result = await session.execute(query)
            return list(result.scalars().all())

        # 计算总数
        count_query = select(func.count()).select_from(query.subquery())
        total = await session.scalar(count_query)
        if total is None:
            total = 0
        # 添加分页
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await session.execute(query)
        items = list(result.scalars().all())

        return PageResult(items=items, total=total, page=page, page_size=page_size)

    async def save(self, session: AsyncSession) -> Self:
        """独立保存操作，自动提交。

        这个方法**会提交传进来的 session**。`db_manager.get_session()` 把 session 包在
        `async with session.begin()` 里交给调用方，在那样一个 session 上调用 `save()` 会提前
        结束外层事务：后续操作落在一个新事务里，失败时也回滚不了前面那部分。要在事务里保存，
        用 `add_to_session()`，由拥有事务的那一方决定何时提交。
        """
        session.add(self)
        await session.commit()
        await session.refresh(self)
        return self

    def add_to_session(self, session: AsyncSession) -> Self:
        """仅添加到会话，不提交，用于事务操作。

        `save()` 的事务内版本：调用方拥有事务，也由调用方提交。
        """
        session.add(self)
        return self

    async def delete(self, session: AsyncSession) -> None:
        """删除这一行并提交。

        和 `save()` 一样会提交调用方的事务，事务内删除请直接用 `session.delete()`。
        """
        await session.delete(self)
        await session.commit()

    async def update(self, session: AsyncSession, **kwargs) -> Self:
        """按关键字更新字段并提交。

        拼错的字段名会直接报错，不会被悄悄忽略：原来的实现用 `if hasattr(self, key)` 跳过不认识的
        名字，于是 `row.update(session, titel="x")` 什么也没改、也什么都没说，调用方还以为成功了。
        同一个仓库的 `OldmanForm.add_error()` 对拼错的字段名就是显式报错的。

        和 `save()` 一样会提交调用方的事务，事务内更新请直接赋值。
        """
        unknown = [key for key in kwargs if not hasattr(self, key)]
        if unknown:
            raise AttributeError(f"{type(self).__name__} has no field(s): {', '.join(sorted(unknown))}")
        for key, value in kwargs.items():
            setattr(self, key, value)
        await session.commit()
        await session.refresh(self)
        return self
