import asyncio
import os
import threading
import time
import warnings
from abc import ABC, abstractmethod
from collections.abc import Callable
from io import StringIO
from pathlib import Path
from typing import Any, Protocol, cast

import aiofiles
import msgspec
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from oldman.logging import logger
from oldman.serializers import MsgpackSerializer, MsgspecModel
from oldman.utils.files import atomic_write


def _file_signature(stat_result: os.stat_result) -> tuple[int, int, int]:
    """文件的身份：inode、纳秒级修改时间、大小。

    只比浮点修改时间不够：两次紧挨着的写入可能拿到同一个修改时间，读的一方以为没变，停在旧内容。
    每次原子写都换一个新 inode，加上它最可靠。
    """
    return stat_result.st_ino, stat_result.st_mtime_ns, stat_result.st_size


async def _replace_file_text(
    path: Path,
    text: str,
    *,
    follow_symlinks: bool,
    written: Callable[[os.stat_result], None],
    failed: Callable[[], None],
) -> None:
    """原子替换文件内容，结果交给 written（新文件的 stat）或 failed。调用方负责持锁。

    写在线程里进行，而线程不会因协程被取消而停下：被取消时仍等它写完（锁一直持有），按结果调用回调，
    再把取消抛出去。否则锁一释放，下一次保存可能被这次迟到的改名覆盖。
    """
    write = asyncio.create_task(asyncio.to_thread(atomic_write, path, text, follow_symlinks=follow_symlinks))
    cancelled: asyncio.CancelledError | None = None
    while not write.done():
        try:
            await asyncio.shield(write)
        except asyncio.CancelledError as error:
            cancelled = error
        except Exception:
            pass  # 写入本身的异常在下面取结果时处理
    try:
        result = write.result()
    except Exception as error:
        failed()
        if cancelled is not None:
            logger.warning(f"Failed to write config {path} while the caller was cancelled: {error!r}")
            raise cancelled from error
        raise
    written(result)
    if cancelled is not None:
        raise cancelled


class AsyncConfigDict:
    """轻量级异步配置缓存。已废弃：改用 YamlStore，值由 MsgspecModel schema 声明。"""

    def __init__(
        self,
        config_path: str | Path,
        check_interval: float = 5.0,  # 检查间隔(秒)
        auto_reload: bool = True,  # 是否自动检查更新
    ):
        warnings.warn(
            "AsyncConfigDict is deprecated; use YamlStore with a MsgspecModel schema",
            DeprecationWarning,
            stacklevel=2,
        )
        self.config_path = Path(config_path)
        self.check_interval = check_interval
        self.auto_reload = auto_reload

        self._data: dict[str, Any] = {}
        self._last_modified: float | None = None
        # 上次加载或写入时文件的身份（inode、纳秒修改时间、大小），判断文件是否被换过用它，见 _file_signature
        self._last_signature: tuple[int, int, int] | None = None
        self._last_check_time: float = 0  # 上次检查时间戳
        self._loaded: bool = False
        self._reload_lock = asyncio.Lock()
        self._thread_lock = threading.RLock()  # 用于同步方法

    async def _load_file_content(self) -> str:
        """加载文件内容"""
        async with aiofiles.open(self.config_path, encoding="utf-8") as f:
            return await f.read()

    def get_empty_data(self) -> dict[str, Any]:
        """获取一个空的数据结构"""
        return {}

    def _should_check(self, force: bool = False) -> bool:
        """判断是否需要检查文件更新"""
        if force:
            return True

        if not self._loaded:
            return True

        if not self.auto_reload:
            return False
        current_time = time.time()
        return (current_time - self._last_check_time) >= self.check_interval

    async def _write_data_unlocked(self, data: dict[str, Any]) -> None:
        """写入配置文件，全部成功后才更新内存。调用方负责持有 _reload_lock。

        任何一步失败（整理内容、写入、落盘、改名）：文件保持原样，异常照常抛出，并标记为未加载——调用方常就地修改
        get_data() 返回的对象再保存，内存可能在写之前就变了；下次读取按文件重新加载，内存回到文件内容。
        文件在替换过程中始终存在：另一个进程的实例若发现文件不存在，会把空数据写回去（见 _check_and_reload）。
        调用方被取消时的处理见 _replace_file_text。
        """
        from oldman.conf.base import new_yaml

        buffer = StringIO()
        try:
            # 每次新建：共用的 YAML 对象在一次输出失败后，之后的输出都是空字符串（见 new_yaml）
            new_yaml().dump(data, buffer)
        except Exception:
            self._loaded = False
            raise

        def written(result: os.stat_result) -> None:
            self._data = data
            self._last_modified = result.st_mtime
            self._last_signature = _file_signature(result)
            self._loaded = True
            self._last_check_time = time.time()

        def failed() -> None:
            self._loaded = False

        await _replace_file_text(self.config_path, buffer.getvalue(), follow_symlinks=False, written=written, failed=failed)

    async def _check_and_reload(self, force: bool = False) -> bool:
        """检查并重载(带时间间隔控制)

        Args:
            force: 强制检查,忽略时间间隔

        Returns:
            bool: 是否重新加载了数据
        """
        if not self._should_check(force=force):
            return False

        async with self._reload_lock:
            if not self._should_check(force=force):
                return False

            if not self.config_path.exists():
                empty_data = self.get_empty_data()
                await self._write_data_unlocked(empty_data)
                return False

            try:
                stat_result = self.config_path.stat()
                signature = _file_signature(stat_result)
                # 同时比较 _last_modified：有“把它置为 None 再强制检查”来强制重读的写法，要继续有效
                unchanged = self._last_signature == signature and self._last_modified == stat_result.st_mtime
                if self._loaded and unchanged:
                    self._last_check_time = time.time()
                    return False

                # 文件已修改,重新加载
                from oldman.conf.base import yaml

                file_content = await self._load_file_content()
                new_data = yaml.load(file_content) or {}
                old_data = self._data
                self._data = new_data
                self._last_modified = stat_result.st_mtime
                self._last_signature = signature
                self._loaded = True
                self._last_check_time = time.time()
                # 子类可重写此方法感知变化
                self.on_file_changed(old_data, new_data)

                logger.info(f"Config reloaded from {self.config_path}")
                return True

            except Exception as e:
                self._last_check_time = time.time()
                logger.error(f"Failed to reload config: {e}")
                return False

    def on_file_changed(self, old_data: dict, new_data: dict) -> None:
        """子类重写此方法来感知数据变化并更新内部缓存

        Args:
            old_data: 旧数据
            new_data: 新数据
        """
        pass

    async def get_data(self, force_check: bool = False) -> dict[str, Any]:
        """获取配置数据

        Args:
            force_check: 是否强制检查更新(忽略时间间隔)
        """
        await self._check_and_reload(force=force_check)
        return self._data

    def get_data_sync(self) -> dict[str, Any]:
        """同步获取数据(不检查更新)"""
        with self._thread_lock:
            return self._data  # 直接返回引用

    async def save_data(self, data: dict[str, Any]) -> None:
        """保存数据"""
        async with self._reload_lock:
            await self._write_data_unlocked(data)


class TypedStore[T: MsgspecModel](ABC):
    """运行期可变的一份配置：schema 声明字段、类型和默认值，整体读、整体写。

    msgspec 的 Struct 在构造和赋值时都不检查类型，所以读取时按 schema 解码，写入前再按 schema 校验一次。
    子类决定存在哪里：实现 get() 与 _write()（调用方已持有 _lock）。
    """

    def __init__(self, schema: type[T]) -> None:
        # 先赋值：下面的 issubclass 会把 schema 收窄成 type[MsgspecModel]，属性就不再是 type[T]
        self.schema: type[T] = schema
        # 写入（以及 YamlStore 的重新加载）
        self._lock = asyncio.Lock()
        # update 的读、改、写：前一个 update 保存完，下一个才读。与 _lock 分开，update 才能经由 save() 写入
        self._update_lock = asyncio.Lock()
        if not (isinstance(schema, type) and issubclass(schema, MsgspecModel)):
            raise TypeError("schema must be a MsgspecModel subclass")
        # 没存过的配置取 schema 的默认值，所以每个字段都要有默认值
        required = [field.name for field in msgspec.structs.fields(schema) if field.required]
        if required:
            raise TypeError(f"every field of {schema.__name__} needs a default; missing: {', '.join(required)}")

    @abstractmethod
    async def get(self) -> T:
        """当前值。"""

    async def save(self, value: T) -> None:
        """按 schema 校验后整体写入；校验不通过抛 msgspec.ValidationError，什么都不写。"""
        async with self._lock:
            await self._store(value)

    async def update(self, **changes: Any) -> T:
        """读出当前值，改几个顶层字段，再交给 save()，返回保存的值（按 schema 校验后的，与之后 get() 读到的一样）。

        子类覆盖 save 也就覆盖了 update。字段名写错抛 TypeError，类型不对抛 msgspec.ValidationError，都不写入。
        同一进程里的 update 排队进行，并发修改不同字段不会互相覆盖；多个进程只有真正同时写时，后写的覆盖先写的。
        """
        async with self._update_lock:
            value = self._validated(msgspec.structs.replace(await self._latest(), **changes))
            await self.save(value)
            return value

    async def _latest(self) -> T:
        """update 的起点：存储里此刻的值。子类可以在这里越过自己的缓存。"""
        return await self.get()

    def _validated(self, value: T) -> T:
        if not isinstance(value, self.schema):
            raise TypeError(f"expected {self.schema.__name__}, got {type(value).__name__}")
        return self.schema.from_dict(value.to_dict())

    async def _store(self, value: T) -> T:
        """校验并写入，返回写入的值。调用方负责持有 _lock。"""
        checked = self._validated(value)
        await self._write(checked)
        return checked

    @abstractmethod
    async def _write(self, value: T) -> None:
        """写入已校验的值。调用方已持有 _lock。"""


class YamlStore[T: MsgspecModel](TypedStore[T]):
    """存在一个 YAML 文件里的类型化配置。

    进程内保存解码好的值：check_interval 秒内不碰磁盘，到期只 stat 一次，文件变了才重新解析。
    文件不存在时把 schema 默认值写成文件。外部修改文件后调用 on_file_changed；自己的 save / update 不调用。
    保存时 YAML 注释不保留。
    """

    def __init__(self, schema: type[T], config_path: str | Path, *, check_interval: float = 5.0) -> None:
        super().__init__(schema)
        self.config_path = Path(config_path)
        self.check_interval = check_interval
        self._value: T | None = None
        self._signature: tuple[int, int, int] | None = None
        self._checked_at = float("-inf")
        # 保存失败后内存可能已被调用方就地改过：下次读取按文件重新加载，这次不算外部修改
        self._resync = False

    async def get(self) -> T:
        """当前值。它是共享对象：改了就 save；只想临时换个值用，先复制一份（msgspec.structs.replace）。

        第一次加载时文件内容不合法，抛出解析或校验的错误；之后外部改坏的内容不采用，保留上次的合法值并记 ERROR。
        """
        value = self._value
        if value is not None and not self._check_due():
            return value
        async with self._lock:
            return await self._read()

    def on_file_changed(self, old: T, new: T) -> None:
        """文件被外部修改（包括删除）并重新加载之后调用；子类在这里重置由配置派生的状态。"""

    async def _latest(self) -> T:
        # 不管 check_interval：另一个进程（多 worker 时每个 worker 各有一个实例）几秒前保存的修改，
        # 若以缓存为起点就会被这次写回冲掉。只多一次 stat，文件没变不重新解析。
        async with self._lock:
            self._checked_at = float("-inf")
            return await self._read()

    def _check_due(self) -> bool:
        return self._resync or time.monotonic() - self._checked_at >= self.check_interval

    async def _read(self) -> T:
        value = self._value
        if value is not None and not self._check_due():
            return value
        self._checked_at = time.monotonic()
        previous, resync = value, self._resync
        try:
            stat_result = self.config_path.stat()
        except FileNotFoundError:
            current = await self._store(self.schema())
            if previous is not None and not resync:
                self._file_changed(previous, current)
            return current

        signature = _file_signature(stat_result)
        if value is not None and signature == self._signature and not resync:
            return value
        try:
            async with aiofiles.open(self.config_path, encoding="utf-8") as file:
                text = await file.read()
            # safe 加载器给出普通类型；round-trip 加载器的 ScalarFloat 这类子类过不了 msgspec 的严格转换
            loaded = self.schema.from_dict(YAML(typ="safe", pure=True).load(text) or {})
        except (OSError, UnicodeDecodeError, YAMLError, msgspec.ValidationError) as error:
            if value is None:
                raise
            # 同一份坏文件只记一次；改好后签名变化，照常重新加载
            self._signature, self._resync = signature, False
            logger.error(f"Config {self.config_path} is invalid, keeping the last valid value: {error}")
            return value

        self._value, self._signature, self._resync = loaded, signature, False
        if previous is not None and not resync:
            logger.info(f"Config reloaded from {self.config_path}")
            self._file_changed(previous, loaded)
        return loaded

    def _file_changed(self, old: T, new: T) -> None:
        try:
            self.on_file_changed(old, new)
        except Exception:
            logger.exception(f"on_file_changed of {type(self).__name__} failed")

    async def _store(self, value: T) -> T:
        try:
            return await super()._store(value)
        except Exception:
            # 调用方常先改 get() 返回的对象再保存：没写成时内存可能已和文件不同
            self._resync = True
            raise

    async def _write(self, value: T) -> None:
        from oldman.conf.base import new_yaml

        buffer = StringIO()
        # 每次新建：共用的 YAML 对象在一次输出失败后，之后的输出都是空字符串（见 new_yaml）
        new_yaml().dump(value.to_dict(), buffer)

        def written(result: os.stat_result) -> None:
            self._value, self._signature, self._resync = value, _file_signature(result), False
            self._checked_at = time.monotonic()

        def failed() -> None:
            # 写失败而调用方又被取消时，抛出的是取消，_store 接不到
            self._resync = True

        await _replace_file_text(self.config_path, buffer.getvalue(), follow_symlinks=True, written=written, failed=failed)


class BinaryRedisClient(Protocol):
    """A client that hands out binary Redis connections: the global ``redis_client`` or one of its aliases."""

    async def async_get_bin_conn(self) -> Any:
        """Return a binary async Redis connection."""
        ...


# 旧名，RedisSettings 的签名一直用它
RedisSettingsClient = BinaryRedisClient


async def _binary_connection(client: BinaryRedisClient | None) -> Any:
    """The given client's binary connection, or the global DEFAULT client's, resolved only now."""
    if client is None:
        # Import only on first use so conf bootstrap does not import the provider.
        from oldman.providers.redis import redis_client

        client = redis_client
    return await client.async_get_bin_conn()


def _store_key_name(name: str) -> str:
    """Validate the part of a store's key below ``<namespace>:store``."""
    if not isinstance(name, str) or not name:
        raise ValueError("name must be a non-empty string")
    return name


class RedisStore[T: MsgspecModel](TypedStore[T]):
    """存在一个 Redis 键里的类型化配置：``<服务命名空间>:store:<name>``，值是整个 schema 的 msgpack。

    不做本地缓存：每次 get() 读一次 Redis，别的进程写入后下一次读取即可见。键不存在时取 schema 的默认值，不写入。
    存的值与 schema 对不上抛 msgspec.ValidationError，不回落默认值；schema 删掉的字段忽略，新加的字段取默认值。
    Redis 的异常原样抛给调用方。构造时不连接 Redis，也不读 settings，可以放在模块级。
    """

    def __init__(self, schema: type[T], name: str, *, client: BinaryRedisClient | None = None) -> None:
        super().__init__(schema)
        self.name = _store_key_name(name)
        self._client = client

    @property
    def key(self) -> str:
        """The Redis key; building it needs the service settings."""
        from oldman.providers.redis import redis_key

        return redis_key("store", self.name)

    async def get(self) -> T:
        """当前值。每次都是新解码的对象，改了再 save 即可。"""
        return await self._read()

    async def _read(self) -> T:
        raw = await (await _binary_connection(self._client)).get(self.key)
        return self.schema() if raw is None else self.schema.from_msgpack(raw)

    async def _write(self, value: T) -> None:
        await (await _binary_connection(self._client)).set(self.key, value.to_msgpack())


class RedisSet[E: (str, int)]:
    """Redis 原生集合 ``<服务命名空间>:store:<name>``，成员是 str 或 int。

    每个操作直接落到 Redis（SADD、SISMEMBER、SRANDMEMBER…），不把整个集合读出来，适合在请求路径上判断名单。
    成员按类型编码，按精确类型检查：int 集合不收 True 或 "1"。与 RedisStore 共用 ``store`` 下的键名，名字不能重复。
    构造时不连接 Redis，也不读 settings：按 tag 区分的一组集合，用到时再构造。
    """

    def __init__(self, member_type: type[E], name: str, *, client: BinaryRedisClient | None = None) -> None:
        if member_type not in (str, int):
            raise TypeError("RedisSet members must be str or int")
        self.member_type = member_type
        self.name = _store_key_name(name)
        self._client = client

    @property
    def key(self) -> str:
        """The Redis key; building it needs the service settings."""
        from oldman.providers.redis import redis_key

        return redis_key("store", self.name)

    async def add(self, member: E) -> bool:
        """Add one member; True when the set did not have it."""
        payload = self._encode(member)
        return bool(await (await _binary_connection(self._client)).sadd(self.key, payload))

    async def remove(self, member: E) -> bool:
        """Remove one member; True when the set had it."""
        payload = self._encode(member)
        return bool(await (await _binary_connection(self._client)).srem(self.key, payload))

    async def contains(self, member: E) -> bool:
        """Whether the set has this member."""
        payload = self._encode(member)
        return bool(await (await _binary_connection(self._client)).sismember(self.key, payload))

    async def members(self) -> set[E]:
        """Every member. Reads the whole set: for a membership check use contains()."""
        raw = await (await _binary_connection(self._client)).smembers(self.key)
        return {self._decode(member) for member in raw}

    async def random(self) -> E | None:
        """One member picked at random, or None when the set is empty."""
        raw = await (await _binary_connection(self._client)).srandmember(self.key)
        return None if raw is None else self._decode(raw)

    def _encode(self, member: E) -> bytes:
        if type(member) is not self.member_type:
            raise TypeError(f"members of {self.name} must be {self.member_type.__name__}, got {type(member).__name__}")
        return msgspec.msgpack.encode(member)

    def _decode(self, raw: bytes) -> E:
        return msgspec.msgpack.decode(raw, type=self.member_type)


SettingsValue = bool | int | float | str | bytes


class RedisSettings:
    """Store typed dynamic settings in Redis-native data structures.

    Deprecated: use RedisStore for values declared by a MsgspecModel schema and RedisSet for sets.
    """

    _SUPPORTED_VALUE_TYPES = (bool, int, float, str, bytes)

    def __init__(
        self,
        client: RedisSettingsClient | None = None,
        namespace: str | None = None,
    ) -> None:
        """Bind an optional Redis client without opening its connection.

        Without a namespace the keys live under ``<service namespace>:settings``, resolved when
        a key is built rather than here, before settings may exist.
        """
        warnings.warn(
            "RedisSettings is deprecated; use RedisStore for values and RedisSet for sets",
            DeprecationWarning,
            stacklevel=2,
        )
        if namespace is not None and (not isinstance(namespace, str) or not namespace):
            raise ValueError("namespace must be a non-empty string")
        self._client = client
        self._namespace = namespace
        self._serializer = MsgpackSerializer()

    async def _connection(self) -> Any:
        """Resolve the injected client or the global DEFAULT client lazily."""
        return await _binary_connection(self._client)

    def _key(self, key: str) -> str:
        """Build one namespace-owned Redis key."""
        if not isinstance(key, str) or not key:
            raise ValueError("key must be a non-empty string")
        return f"{self.namespace}:{key}"

    @property
    def namespace(self) -> str:
        """The key prefix: the one given, or ``<service namespace>:settings``."""
        if self._namespace is not None:
            return self._namespace
        from oldman.providers.redis import redis_key

        return redis_key("settings")

    def _dump(self, value: SettingsValue) -> bytes:
        """Validate and encode one supported setting value."""
        if type(value) not in self._SUPPORTED_VALUE_TYPES:
            raise TypeError("RedisSettings values must be bool, int, float, str, or bytes")
        return cast(bytes, self._serializer.dumps(value))

    def _load(self, value: bytes) -> SettingsValue:
        """Decode one stored setting value."""
        return cast(SettingsValue, self._serializer.loads(value))

    async def get_value(self, key: str, default: Any = None) -> SettingsValue | Any:
        """Return one decoded value or default only when the key is absent."""
        redis_key = self._key(key)
        raw = await (await self._connection()).get(redis_key)
        return default if raw is None else self._load(raw)

    async def set_value(self, key: str, value: SettingsValue, ttl: int | None = None) -> None:
        """Encode and store one value with an optional expiry in seconds."""
        redis_key = self._key(key)
        payload = self._dump(value)
        await (await self._connection()).set(redis_key, payload, ex=ttl)

    async def delete(self, key: str) -> bool:
        """Delete any settings data structure stored at key."""
        redis_key = self._key(key)
        return bool(await (await self._connection()).delete(redis_key))

    async def add_set_member(self, key: str, value: SettingsValue) -> bool:
        """Add one typed member and report whether the set changed."""
        redis_key, payload = self._key(key), self._dump(value)
        return bool(await (await self._connection()).sadd(redis_key, payload))

    async def remove_set_member(self, key: str, value: SettingsValue) -> bool:
        """Remove one typed member and report whether the set changed."""
        redis_key, payload = self._key(key), self._dump(value)
        return bool(await (await self._connection()).srem(redis_key, payload))

    async def get_set_members(self, key: str) -> set[SettingsValue]:
        """Return every decoded member from a settings set."""
        raw = await (await self._connection()).smembers(self._key(key))
        return {self._load(value) for value in raw}

    async def contains_set_member(self, key: str, value: SettingsValue) -> bool:
        """Return whether a typed member exists in a settings set."""
        redis_key, payload = self._key(key), self._dump(value)
        return bool(await (await self._connection()).sismember(redis_key, payload))

    async def get_random_set_member(self, key: str) -> SettingsValue | None:
        """Return one decoded random member or None for an empty set."""
        raw = await (await self._connection()).srandmember(self._key(key))
        return None if raw is None else self._load(raw)

    async def append_list_item(self, key: str, value: SettingsValue) -> int:
        """Append one typed item to the right side of a settings list."""
        redis_key, payload = self._key(key), self._dump(value)
        return int(await (await self._connection()).rpush(redis_key, payload))

    async def prepend_list_item(self, key: str, value: SettingsValue) -> int:
        """Prepend one typed item to the left side of a settings list."""
        redis_key, payload = self._key(key), self._dump(value)
        return int(await (await self._connection()).lpush(redis_key, payload))

    async def pop_first_list_item(self, key: str) -> SettingsValue | None:
        """Remove and decode the first settings-list item."""
        raw = await (await self._connection()).lpop(self._key(key))
        return None if raw is None else self._load(raw)

    async def pop_last_list_item(self, key: str) -> SettingsValue | None:
        """Remove and decode the last settings-list item."""
        raw = await (await self._connection()).rpop(self._key(key))
        return None if raw is None else self._load(raw)

    async def get_list_items(self, key: str, start: int = 0, stop: int = -1) -> list[SettingsValue]:
        """Return an inclusive decoded range from a settings list."""
        raw = await (await self._connection()).lrange(self._key(key), start, stop)
        return [self._load(value) for value in raw]


__all__ = [
    "AsyncConfigDict",
    "RedisSet",
    "RedisSettings",
    "RedisStore",
    "YamlStore",
]
