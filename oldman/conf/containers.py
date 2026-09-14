import asyncio
import threading
import time
from io import StringIO
from pathlib import Path
from typing import Any, Protocol, cast

import aiofiles

from oldman.logging import logger
from oldman.serializers import MsgpackSerializer


class AsyncConfigDict:
    """轻量级异步配置缓存"""

    def __init__(
        self,
        config_path: str | Path,
        check_interval: float = 5.0,  # 检查间隔(秒)
        auto_reload: bool = True,  # 是否自动检查更新
    ):
        self.config_path = Path(config_path)
        self.check_interval = check_interval
        self.auto_reload = auto_reload

        self._data: dict[str, Any] = {}
        self._last_modified: float | None = None
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
        """写入配置文件。调用方负责持有 _reload_lock。"""
        from oldman.conf.base import yaml

        self._data = data
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        buffer = StringIO()
        yaml.dump(data, buffer)

        temp_file = self.config_path.with_suffix(".tmp")
        async with aiofiles.open(temp_file, "w", encoding="utf-8") as f:
            await f.write(buffer.getvalue())
        if self.config_path.exists():
            self.config_path.unlink()
        temp_file.replace(self.config_path)

        if self.config_path.exists():
            stat_result = self.config_path.stat()
            self._last_modified = stat_result.st_mtime
        self._loaded = True
        self._last_check_time = time.time()

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
                if self._loaded and self._last_modified == stat_result.st_mtime:
                    self._last_check_time = time.time()
                    return False

                # 文件已修改,重新加载
                from oldman.conf.base import yaml

                file_content = await self._load_file_content()
                new_data = yaml.load(file_content) or {}
                old_data = self._data
                self._data = new_data
                self._last_modified = stat_result.st_mtime
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


SettingsValue = bool | int | float | str | bytes


class RedisSettingsClient(Protocol):
    """Provide the binary Redis connection required by RedisSettings."""

    async def async_get_bin_conn(self) -> Any:
        """Return a binary async Redis connection."""
        ...


class RedisSettings:
    """Store typed dynamic settings in Redis-native data structures."""

    _SUPPORTED_VALUE_TYPES = (bool, int, float, str, bytes)

    def __init__(
        self,
        client: RedisSettingsClient | None = None,
        namespace: str = "settings",
    ) -> None:
        """Bind an optional Redis client without opening its connection."""
        if not isinstance(namespace, str) or not namespace:
            raise ValueError("namespace must be a non-empty string")
        self._client = client
        self.namespace = namespace
        self._serializer = MsgpackSerializer()

    async def _connection(self) -> Any:
        """Resolve the injected client or the global DEFAULT client lazily."""
        client = self._client
        if client is None:
            # Import only on first use so conf bootstrap does not import the provider.
            from oldman.providers.redis import redis_client

            client = self._client = redis_client
        return await client.async_get_bin_conn()

    def _key(self, key: str) -> str:
        """Build one namespace-owned Redis key."""
        if not isinstance(key, str) or not key:
            raise ValueError("key must be a non-empty string")
        return f"{self.namespace}:{key}"

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
