"""
@author:alex
@date:2024/10/30
@time:16:37
"""

__author__ = "alex"

import asyncio
import hashlib
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from functools import wraps
from typing import Any, ClassVar, Generic, TypeVar, cast

import orjson
from sqlalchemy import Select, event, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, object_session

from oldman.db.schemas import PageResult
from oldman.db.sqlalchemy.models import DatabaseModel
from oldman.logging import logger
from oldman.providers.redis import redis_client
from oldman.tasks.simple import BackgroundTaskManager

# 使用具体的 DatabaseModel 作为边界,而不是 Protocol
T = TypeVar("T", bound=DatabaseModel)


#: Cache writes waiting for the transaction that produced them to commit.
_PENDING_CACHE_TASKS = "oldman.cache.pending"

CacheTask = tuple[Callable[..., Coroutine[Any, Any, None]], tuple[Any, ...]]


def _run_cache_task(task: CacheTask) -> None:
    """把一次缓存写入交给后台任务管理器执行。

    不用 asyncio.create_task：它不保留引用，CPython 可能在任务跑完之前就把它回收掉，
    而任务里的异常也只会以"从未被取回"的警告形式出现。管理器会持有引用、把失败写进
    日志，并在进程退出时统一取消。

    没有运行中的事件循环、或者管理器正在停机时，这次写入就没有地方可跑。缓存变脏不好，
    但在这里抛异常更糟——它所属的事务已经提交完成了。
    """
    coro_func, args = task
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(f"无事件循环，跳过缓存失效: {getattr(coro_func, '__qualname__', coro_func)}")
        return
    try:
        BackgroundTaskManager().spawn(coro_func, *args)
    except RuntimeError as exc:
        logger.warning(f"后台任务管理器不可用，跳过缓存失效: {type(exc).__name__}")


def _queue_cache_task(target: Any, coro_func: Callable[..., Coroutine[Any, Any, None]], *args: Any) -> None:
    """把缓存写入推迟到产生它的事务真正提交之后。

    mapper 事件是在 flush 时触发的，不是提交时：在那里直接写缓存，会把一次即将回滚的
    改动也写进去；而且 SQLAlchemy 明确要求不要在 mapper 事件里做 I/O。
    """
    session = object_session(target)
    if session is None:
        # 不在 Session 里的实例没有事务可等，只能立即执行。
        _run_cache_task((coro_func, args))
        return
    pending: list[CacheTask] = session.info.setdefault(_PENDING_CACHE_TASKS, [])
    pending.append((coro_func, args))


@event.listens_for(Session, "after_commit")
def _flush_pending_cache_tasks(session: Session) -> None:
    """事务确实落库之后，再执行排队的缓存写入。"""
    for task in session.info.pop(_PENDING_CACHE_TASKS, []):
        _run_cache_task(task)


@event.listens_for(Session, "after_soft_rollback")
def _discard_pending_cache_tasks(session: Session, *_: Any) -> None:
    """回滚掉的事务什么都没改，它排队的缓存写入一并丢弃。"""
    session.info.pop(_PENDING_CACHE_TASKS, None)


def _configured_cache_alias() -> str:
    from oldman.conf import settings

    return settings.cache.client


async def _cache_redis_connection() -> Any:
    return await redis_client.using(_configured_cache_alias()).async_get_bin_conn()


def model_primary_key_value(instance: DatabaseModel) -> Any:
    """Return the value of a model's single mapped primary key."""
    primary_keys = inspect(type(instance)).primary_key
    if len(primary_keys) != 1 or primary_keys[0].key is None:
        raise ValueError("SQLAlchemy cache requires exactly one named primary key column")
    return getattr(instance, primary_keys[0].key)


@dataclass
class CacheConfig:
    """缓存配置"""

    expire_seconds: int = 3600
    prefix: str = "sqlalchemy_cache:"


class AsyncModelCache(Generic[T]):  # noqa: UP046 -- preserve the existing Generic declaration during mechanical migration
    """异步模型缓存"""

    def __init__(self, model: type[T], config: CacheConfig | None = None):
        self.model = model
        self.config = config or CacheConfig()

    def get_cache_key(self, pk: Any) -> str:
        """生成缓存键"""
        model_name = self.model.__name__
        return f"{self.config.prefix}{model_name}:{pk}"

    async def set_cache(self, instance: T) -> None:
        """设置缓存"""
        key = self.get_cache_key(model_primary_key_value(instance))
        data = instance.model_dump_json()
        conn = await _cache_redis_connection()
        await conn.setex(key, self.config.expire_seconds, data)

    async def get_cache(self, pk: Any) -> T | None:
        """获取缓存"""
        key = self.get_cache_key(pk)
        conn = await _cache_redis_connection()
        cached_data = await conn.get(key)

        if cached_data:
            return self.model.model_validate_json(cached_data)  # type: ignore

        return None

    async def delete_cache(self, pk: Any) -> None:
        """删除缓存"""
        key = self.get_cache_key(pk)
        conn = await _cache_redis_connection()
        await conn.delete(key)


def cached_model_simply(expire_seconds: int = 3600):
    """模型级别的缓存装饰器"""

    def decorator(cls: type[T]) -> type[T]:
        # 创建缓存实例
        cache = AsyncModelCache(model=cls, config=CacheConfig(expire_seconds=expire_seconds))

        # 保存原始方法
        if hasattr(cls, "__init__"):
            original_init = cls.__init__

            @wraps(original_init)
            def new_init(self: Any, *args: Any, **kwargs: Any) -> None:
                original_init(self, *args, **kwargs)
                self._cache = cache

            cls.__init__ = new_init  # type: ignore[method-assign]

        # 添加异步缓存方法到模型类
        async def get_cached(cls_inner: type[T], session: AsyncSession, pk: Any) -> T | None:
            """获取缓存的实例,如果没有则从数据库加载"""
            cached = await cache.get_cache(pk)
            if cached is None:
                instance = await session.get(cls_inner, pk)
                if instance:
                    await cache.set_cache(instance)
                return instance
            return cached

        cls.get_cached = classmethod(get_cached)

        # 设置事件监听器
        @event.listens_for(cls, "after_update")
        def after_update(mapper: Any, connection: Any, target: T) -> None:
            _queue_cache_task(target, cache.set_cache, target)

        @event.listens_for(cls, "after_delete")
        def after_delete(mapper: Any, connection: Any, target: T) -> None:
            _queue_cache_task(target, cache.delete_cache, model_primary_key_value(target))

        return cls

    return decorator


class AsyncQueryCache(Generic[T]):  # noqa: UP046 -- preserve the existing Generic declaration during mechanical migration
    """异步查询缓存管理器"""

    def __init__(self, model: type[T], instance_expire_seconds: int = 3600, query_expire_seconds: int = 300):
        self.model = model
        self.instance_expire_seconds = instance_expire_seconds
        self.query_expire_seconds = query_expire_seconds

    async def get_by_fields(self, session: AsyncSession, use_cache: bool = True, **fields: Any) -> T | None:
        """根据任意字段获取单个对象"""
        if not use_cache:
            return await self.model.get_by_fields(session, **fields)  # type: ignore

        cache_key = self._generate_fields_key(fields)
        conn = await _cache_redis_connection()
        cached_id = await conn.get(cache_key)

        if cached_id:
            # 如果找到了字段映射,尝试获取实例缓存
            if isinstance(cached_id, bytes):
                cached_id = cached_id.decode()
            instance_key = self._get_instance_cache_key(cached_id)
            cached_instance_data = await conn.get(instance_key)

            if cached_instance_data:
                # print(f"cache hit, key: {cache_key}, sql: {fields}")
                return self.model.model_validate_json(cached_instance_data)  # type: ignore

        # 从数据库获取
        instance = await self.model.get_by_fields(session, **fields)
        if instance:
            await self._cache_instance(instance, fields)  # type: ignore
        return instance  # type: ignore

    def _get_instance_cache_key(self, instance_id: Any) -> str:
        return f"i:{self.model.__name__}:{instance_id}"

    async def _cache_instance(self, instance: T, fields: dict[str, Any]) -> None:
        """缓存实例和字段映射"""
        conn = await _cache_redis_connection()
        pipe = conn.pipeline()

        instance_id = model_primary_key_value(instance)
        instance_key = self._get_instance_cache_key(instance_id)
        instance_data = instance.model_dump_json()

        pipe.setex(instance_key, self.instance_expire_seconds, instance_data)

        # 缓存字段映射 - 使用压缩的键格式
        fields_key = self._generate_fields_key(fields)
        pipe.setex(fields_key, self.instance_expire_seconds, str(instance_id))
        # 记录反向映射用于失效处理 - 使用集合存储
        reverse_key = self._get_reverse_cache_key(instance_id)
        pipe.sadd(reverse_key, fields_key)
        pipe.expire(reverse_key, self.instance_expire_seconds)

        await pipe.execute()

    def _get_reverse_cache_key(self, instance_id: Any) -> str:
        """Key of the set listing which field keys point at one instance.

        The model name belongs here for the same reason it is in the instance and query
        keys: without it `User` 5 and `Article` 5 share `rev:5`, so invalidating one
        model deletes the other's cached field keys. It only ever over-deletes, never
        returns another model's row, but a write to one model should not quietly empty
        another model's cache.
        """
        return f"rev:{self.model.__name__}:{instance_id}"

    def _get_query_set_cache_key(self, instance_id: Any) -> str:
        """Key of the set listing which query caches contain one instance."""
        return f"qs:{self.model.__name__}:{instance_id}"

    def _generate_fields_key(self, fields: dict[str, Any]) -> str:
        """生成压缩的字段缓存键"""
        # 对字段名进行编码以节省空间
        encoded_fields = [f"{k[:2]}:{v}" for k, v in sorted(fields.items())]
        fields_str = ",".join(encoded_fields)
        return f"f:{self.model.__name__}:{fields_str}"

    async def get_many(self, session: AsyncSession, ids: list[Any], use_cache: bool = True) -> dict[Any, T]:
        """批量获取多个对象"""
        if not use_cache:
            return await self.model.get_many_by_ids(session, ids)  # type: ignore

        results: dict[Any, T] = {}
        conn = await _cache_redis_connection()
        pipe = conn.pipeline()

        for id_val in ids:
            cache_key = self._get_instance_cache_key(id_val)
            pipe.get(cache_key)

        cached_results = await pipe.execute()

        missing_ids: list[Any] = []
        for id_val, cached in zip(ids, cached_results, strict=False):
            if cached:
                instance = self.model.model_validate_json(cached)
                results[id_val] = instance  # type: ignore
            else:
                missing_ids.append(id_val)

        # 获取缓存未命中的结果
        if missing_ids:
            db_results = await self.model.get_many_by_ids(session, missing_ids)
            results.update(db_results)

            # 批量缓存未命中的结果
            if db_results:
                pipe = conn.pipeline()
                for db_instance in db_results.values():
                    cache_key = self._get_instance_cache_key(model_primary_key_value(db_instance))
                    pipe.setex(cache_key, self.instance_expire_seconds, db_instance.model_dump_json())
                await pipe.execute()

        return results

    async def execute_query(
        self,
        session: AsyncSession,
        query: Select,
        page: int | None = None,
        page_size: int | None = None,
        cache: bool = True,
    ) -> list[T] | PageResult[T]:
        """执行查询并缓存结果"""
        if not cache:
            result = await self.model.execute_query_with_select(session, query, page, page_size)
            return result  # type: ignore

        is_paginated = page is not None and page_size is not None
        cache_key = self._generate_query_key(query, page, page_size)

        conn = await _cache_redis_connection()
        cached = await conn.get(cache_key)

        if cached:
            # print(f"cache hit, key: {cache_key}, sql: {query}")
            return await self._handle_cached_query(cached, is_paginated)

        # 从数据库获取结果
        result = await self.model.execute_query_with_select(session, query, page, page_size)
        await self._cache_query_result(result, cache_key)  # type: ignore

        # 类型守卫
        if isinstance(result, list):
            return cast(list[T], result)
        return result

    def _generate_query_key(self, query: Select, page: int | None = None, page_size: int | None = None) -> str:
        """生成查询缓存键"""
        query_str = str(query.compile(compile_kwargs={"literal_binds": True}))

        # 将分页信息添加到缓存键
        if page is not None and page_size is not None:
            query_str = f"{query_str}:p{page}:s{page_size}"

        hash_key = hashlib.md5(query_str.encode()).hexdigest()
        return f"q:{self.model.__name__}:{hash_key}"

    async def _handle_cached_query(self, cached: str, is_paginated: bool) -> list[T] | PageResult:
        """处理缓存的查询结果"""
        data = orjson.loads(cached)

        if is_paginated and isinstance(data, dict):
            items_data = data.get("items", [])
            items: list[T] = []
            for item_dict in items_data:
                item_json = orjson.dumps(item_dict).decode()
                item_obj = self.model.model_validate_json(item_json)
                items.append(item_obj)  # type: ignore

            return PageResult(
                items=items,
                total=data.get("total", 0),
                page=data.get("page", 1),
                page_size=data.get("page_size", 10),
            )

        result_items: list[T] = []
        if isinstance(data, list):
            for item_dict in data:
                item_json = orjson.dumps(item_dict).decode()
                item_obj = self.model.model_validate_json(item_json)
                result_items.append(item_obj)  # type: ignore

        return result_items

    async def _cache_query_result(self, result: list[T] | PageResult, cache_key: str) -> None:
        """缓存查询结果"""
        conn = await _cache_redis_connection()
        pipe = conn.pipeline()

        instances: list[T]
        cache_data: dict[str, Any] | list[dict[str, Any]]

        if isinstance(result, PageResult):
            cache_data = {
                "items": [item.model_dump_dict() for item in result.items],
                "total": result.total,
                "page": result.page,
                "page_size": result.page_size,
            }
            instances = cast(list[T], result.items)
        else:
            cache_data = [instance.model_dump_dict() for instance in result]
            instances = result

        # 缓存查询结果
        pipe.setex(cache_key, self.query_expire_seconds, orjson.dumps(cache_data))

        # 记录查询缓存与实例的关联
        for instance in instances:
            query_set_key = self._get_query_set_cache_key(model_primary_key_value(instance))
            pipe.sadd(query_set_key, cache_key)
            pipe.expire(query_set_key, self.query_expire_seconds)

        await pipe.execute()

    async def invalidate(self, *instances: T) -> None:
        """使缓存失效"""
        conn = await _cache_redis_connection()
        pipe = conn.pipeline()

        for instance in instances:
            # 获取需要失效的键
            instance_id_str = str(model_primary_key_value(instance))
            # 删除实例缓存
            instance_key = self._get_instance_cache_key(instance_id_str)
            pipe.delete(instance_key)

            reverse_key = self._get_reverse_cache_key(instance_id_str)
            field_keys = await conn.smembers(reverse_key)
            for key in field_keys:
                pipe.delete(key)
            pipe.delete(reverse_key)
            # 删除查询缓存
            query_set_key = self._get_query_set_cache_key(instance_id_str)
            query_keys = await conn.smembers(query_set_key)
            for key in query_keys:
                pipe.delete(key)
            pipe.delete(query_set_key)

        await pipe.execute()


class CacheableModel(DatabaseModel):
    """可缓存模型的基类"""

    __abstract__ = True

    _cache_manager: ClassVar[AsyncQueryCache[Any] | None] = None

    @classmethod
    def get_cache_manager(cls) -> AsyncQueryCache[Any]:
        """获取缓存管理器实例"""
        if cls._cache_manager is None:
            raise RuntimeError(f"Cache manager not initialized for {cls.__name__}")
        return cls._cache_manager

    @classmethod
    def set_cache_manager(cls, cache_manager: AsyncQueryCache[Any]) -> None:
        """设置缓存管理器实例"""
        cls._cache_manager = cache_manager

    @classmethod
    async def cached_get(cls, session: AsyncSession, use_cache: bool = True, **fields: Any) -> "CacheableModel | None":
        manager = cls.get_cache_manager()
        return await manager.get_by_fields(session, use_cache, **fields)

    @classmethod
    async def cached_get_many(cls, session: AsyncSession, ids: list[Any], use_cache: bool = True) -> dict[Any, "CacheableModel"]:
        manager = cls.get_cache_manager()
        return await manager.get_many(session, ids, use_cache)

    @classmethod
    async def cached_filter(
        cls, session: AsyncSession, *conditions: Any, page: int | None = None, page_size: int | None = None, cache: bool = True
    ) -> list["CacheableModel"] | PageResult:
        manager = cls.get_cache_manager()
        query = select(cls).filter(*conditions)
        return await manager.execute_query(session, query, page, page_size, cache)


def cached_model(instance_expire_seconds: int = 3600, query_expire_seconds: int = 300):
    """模型缓存装饰器"""

    def decorator(cls: type[T]) -> type[T]:
        # 确保模型继承自 CacheableModel
        if not issubclass(cls, CacheableModel):
            raise TypeError(f"{cls.__name__} must inherit from CacheableModel")

        cache_manager = AsyncQueryCache(cls, instance_expire_seconds, query_expire_seconds)
        cls.set_cache_manager(cache_manager)  # type: ignore

        # 设置事件监听器
        @event.listens_for(cls, "after_update")
        def after_update(mapper: Any, connection: Any, target: T) -> None:
            _queue_cache_task(target, cache_manager.invalidate, target)

        @event.listens_for(cls, "after_delete")
        def after_delete(mapper: Any, connection: Any, target: T) -> None:
            _queue_cache_task(target, cache_manager.invalidate, target)

        return cls

    return decorator


#
# @cached_model()
# class Product(CacheableModel):
#     __tablename__ = "products"
#
#     id: int = Column(Integer, primary_key=True)
#     name: str = Column(String(100))
#     price: float = Column(Float)
#     category: str = Column(String(50))
#
#     @classmethod
#     def invalidation_keys(cls, instance: 'Product') -> List[str]:
#         """自定义缓存失效策略"""
#         return [
#             cls.cache_key(instance.id),
#             cls.query_cache_key(f"category:{instance.category}"),
#             f"{cls.__name__}:query:*"
#         ]
#
#
# # 使用示例
# async def example_usage():
#     async with AsyncSession(engine) as session:
#         # 获取单个产品
#         product = await Product.cached_get(session, 1)
#
#         # 批量获取产品
#         products = await Product.cached_get_many(session, [1, 2, 3])
#
#         # 查询过滤
#         cheap_products = await Product.cached_filter(
#             session,
#             Product.price < 100,
#             Product.category == "electronics"
#         )
#
#         # 更新产品会自动使相关缓存失效
#         if product:
#             product.price += 10
#             await session.commit()
