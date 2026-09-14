"""
@author:alex
@date:2024/10/30
@time:12:31
"""

__author__ = "alex"

import uuid as uuid_pkg
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Self

from sqlalchemy import TIMESTAMP, Boolean, DateTime, Select, func, inspect, select, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.orm.strategy_options import _AbstractLoad
from uuid6 import uuid7

from oldman.db.schemas import PageResult
from oldman.serializers.base import ModelSerializer

# PostgreSQL
postgresql_server_default = text("TIMEZONE('UTC', NOW())")

# MySQL
mysql_server_default = func.utc_timestamp()

# SQLite (不推荐用于生产)
sqlite_server_default = func.datetime("now")

# if settings.DATABASES['default'] == 'postgresql':
#     server_default = postgresql_server_default
# elif settings.DATABASE == 'mysql':
#     server_default = mysql_server_default
# elif settings.DATABASE == 'sqlite':
#     server_default = sqlite_server_default
# else:
#     server_default = func.now()
server_default = mysql_server_default


class UUIDMixin:
    uuid: Mapped[uuid_pkg.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7, server_default=text("gen_random_uuid()"))


class NativeTimestampsMixin:
    """
    Mixin 定义时间戳的类, 使用是数据库服务器当前时区, 不包含时区信息.
    注意: 默认使用的是mysql, 如果使用其他数据库, 需要修改 __datetime_func__ 和 __server_default__
    """

    __abstract__ = True

    __created_at_name__ = "created_at"
    __updated_at_name__ = "updated_at"
    __server_default__ = text("current_timestamp(0)")

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
    """Mixin 定义时间戳的类, 使用是UTC时区, 不包含时区信息"""

    __abstract__ = True

    __created_at_name__ = "created_at"
    __updated_at_name__ = "updated_at"
    __server_default__ = mysql_server_default

    created_at: Mapped[datetime] = mapped_column(
        __created_at_name__,
        TIMESTAMP(timezone=False),
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        server_default=__server_default__,
        nullable=False,
    )

    updated_at: Mapped[datetime | None] = mapped_column(
        __updated_at_name__,
        TIMESTAMP(timezone=False),
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
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
        return str(ModelSerializer.serialize(self, False))

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
        """独立保存操作，自动提交"""
        session.add(self)
        await session.commit()
        await session.refresh(self)
        return self

    def add_to_session(self, session: AsyncSession) -> Self:
        """仅添加到会话，不提交，用于事务操作"""
        session.add(self)
        return self

    async def delete(self, session: AsyncSession) -> None:
        await session.delete(self)
        await session.commit()

    async def update(self, session: AsyncSession, **kwargs) -> Self:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        await session.commit()
        await session.refresh(self)
        return self
