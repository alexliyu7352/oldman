"""Behavior tests for the native Redis cache backend."""

from __future__ import annotations

import fnmatch
import unittest
from collections.abc import Sequence
from typing import Any
from unittest.mock import Mock, patch

from oldman.cache.backends import redis_cache as exported_redis_cache
from oldman.cache.backends.redis import RedisCache
from oldman.cache.backends.redis import redis_cache as module_redis_cache
from oldman.conf.schemas import RedisCacheConfig


def redis_glob_matches(pattern: str, key: str) -> bool:
    """Match the Redis glob escapes exercised by namespace-scoped scans."""
    translated: list[str] = []
    index = 0
    escaped_literals = {"*": "[*]", "?": "[?]", "[": "[[]"}
    while index < len(pattern):
        character = pattern[index]
        if character != "\\":
            translated.append(character)
            index += 1
            continue
        index += 1
        if index == len(pattern):
            translated.append("\\")
            break
        translated.append(escaped_literals.get(pattern[index], pattern[index]))
        index += 1
    return fnmatch.fnmatchcase(key, "".join(translated))


def require_positive_integer_expiration(value: object) -> None:
    if type(value) is not int or value <= 0:
        raise AssertionError("Redis expiration commands require a positive integer")


class FakeBinaryPipeline:
    def __init__(self, connection: FakeBinaryConnection) -> None:
        self.connection = connection
        self.commands: list[tuple[Any, ...]] = []

    async def __aenter__(self) -> FakeBinaryPipeline:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        return None

    def execute_command(self, command: str, *args: Any) -> FakeBinaryPipeline:
        self.commands.append(("execute_command", command, *args))
        return self

    def pexpire(self, key: str, *, time: int) -> FakeBinaryPipeline:
        require_positive_integer_expiration(time)
        self.commands.append(("pexpire", key, time))
        return self

    def expire(self, key: str, *, time: int) -> FakeBinaryPipeline:
        require_positive_integer_expiration(time)
        self.commands.append(("expire", key, time))
        return self

    async def execute(self) -> list[bool]:
        self.connection.calls.append(("pipeline_execute",))
        for command in self.commands:
            if command[:2] == ("execute_command", "MSET"):
                self.connection.store_pairs(command[2:])
            self.connection.calls.append(command)
        return [True] * len(self.commands)


class FakeBinaryConnection:
    def __init__(
        self,
        *,
        pttl_values: Sequence[int] = (),
        scan_pages: Sequence[tuple[int, list[bytes]]] = (),
        get_error: Exception | None = None,
    ) -> None:
        self.values: dict[Any, Any] = {}
        self.calls: list[tuple[Any, ...]] = []
        self.scan_patterns: list[str] = []
        self.pttl_values = list(pttl_values)
        self.scan_pages = list(scan_pages)
        self.get_error = get_error

    async def get(self, key: str) -> Any | None:
        self.calls.append(("get", key))
        if self.get_error is not None:
            raise self.get_error
        return self.values.get(key)

    async def mget(self, *keys: str) -> list[Any | None]:
        self.calls.append(("mget", *keys))
        return [self.values.get(key) for key in keys]

    async def set(
        self,
        key: str,
        value: Any,
        *,
        nx: bool = False,
        px: int | None = None,
        ex: int | None = None,
    ) -> bool | None:
        if px is not None:
            require_positive_integer_expiration(px)
        if ex is not None:
            require_positive_integer_expiration(ex)
        self.calls.append(("set", key, nx, px, ex))
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    async def psetex(self, key: str, ttl: int, value: Any) -> bool:
        require_positive_integer_expiration(ttl)
        self.calls.append(("psetex", key, ttl))
        self.values[key] = value
        return True

    async def setex(self, key: str, ttl: int, value: Any) -> bool:
        require_positive_integer_expiration(ttl)
        self.calls.append(("setex", key, ttl))
        self.values[key] = value
        return True

    async def execute_command(self, command: str, *args: Any) -> bool:
        self.calls.append(("execute_command", command, *args))
        if command == "MSET":
            self.store_pairs(args)
        return True

    def pipeline(self, *, transaction: bool) -> FakeBinaryPipeline:
        self.calls.append(("pipeline", transaction))
        return FakeBinaryPipeline(self)

    async def exists(self, key: str) -> int:
        self.calls.append(("exists", key))
        return int(key in self.values)

    async def expire(self, key: str, ttl: int) -> bool:
        require_positive_integer_expiration(ttl)
        self.calls.append(("expire", key, ttl))
        return key in self.values

    async def pexpire(self, key: str, ttl: int) -> bool:
        require_positive_integer_expiration(ttl)
        self.calls.append(("pexpire", key, ttl))
        return key in self.values

    async def persist(self, key: str) -> bool:
        self.calls.append(("persist", key))
        return key in self.values

    async def delete(self, *keys: Any) -> int:
        self.calls.append(("delete", *keys))
        deleted = 0
        for key in keys:
            if key in self.values:
                del self.values[key]
                deleted += 1
            elif isinstance(key, bytes) and key.decode() in self.values:
                del self.values[key.decode()]
                deleted += 1
        return deleted

    async def scan(self, *, cursor: int, match: str, count: int) -> tuple[int, list[bytes]]:
        self.calls.append(("scan", cursor, match, count))
        self.scan_patterns.append(match)
        if self.scan_pages:
            return self.scan_pages.pop(0)
        matching_keys = []
        for key in self.values:
            key_text = key.decode() if isinstance(key, bytes) else str(key)
            if redis_glob_matches(match, key_text):
                matching_keys.append(key if isinstance(key, bytes) else key.encode())
        return 0, matching_keys

    async def pttl(self, key: str) -> int:
        self.calls.append(("pttl", key))
        return self.pttl_values.pop(0)

    def store_pairs(self, flattened: Sequence[Any]) -> None:
        for index in range(0, len(flattened), 2):
            self.values[flattened[index]] = flattened[index + 1]


class FakeBinaryAlias:
    def __init__(
        self,
        *,
        pttl_values: Sequence[int] = (),
        scan_pages: Sequence[tuple[int, list[bytes]]] = (),
        get_error: Exception | None = None,
    ) -> None:
        self.connection = FakeBinaryConnection(
            pttl_values=pttl_values,
            scan_pages=scan_pages,
            get_error=get_error,
        )
        self.connection_count = 0
        self.close_count = 0

    async def async_get_bin_conn(self) -> FakeBinaryConnection:
        self.connection_count += 1
        return self.connection


class RedisCacheTest(unittest.IsolatedAsyncioTestCase):
    async def test_set_get_add_and_batch_commands_use_binary_client(self) -> None:
        alias = FakeBinaryAlias()
        cache = RedisCache(client=alias, namespace="main", serializer="pickle")

        await cache.set("answer", {"value": 42}, ttl=1.5)
        self.assertEqual({"value": 42}, await cache.get("answer"))
        self.assertIn(("psetex", "main:answer", 1500), alias.connection.calls)

        await cache.multi_set([("one", 1), ("two", 2)], ttl=2.5)
        self.assertEqual([2, None, 1], await cache.multi_get(["two", "missing", "one"]))
        self.assertIn(("pipeline", True), alias.connection.calls)
        self.assertIn(("pexpire", "main:one", 2500), alias.connection.calls)
        self.assertIn(("pexpire", "main:two", 2500), alias.connection.calls)

        await cache.multi_set([("plain", 3)])
        self.assertTrue(any(call[:2] == ("execute_command", "MSET") for call in alias.connection.calls))

        with self.assertRaises(ValueError):
            await cache.add("answer", 43)
        self.assertIn(("set", "main:answer", True, None, None), alias.connection.calls)

    async def test_set_add_exists_expire_and_delete_preserve_redis_commands(self) -> None:
        alias = FakeBinaryAlias()
        cache = RedisCache(client=alias, namespace="main")

        await cache.set("forever", 1)
        await cache.set("seconds", 2, ttl=3)
        await cache.add("added", 3, ttl=4)
        self.assertTrue(await cache.exists("forever"))
        self.assertTrue(await cache.expire("forever", 5))
        self.assertTrue(await cache.expire("forever", 0))
        self.assertEqual(1, await cache.delete("forever"))

        self.assertIn(("set", "main:forever", False, None, None), alias.connection.calls)
        self.assertIn(("setex", "main:seconds", 3), alias.connection.calls)
        self.assertIn(("set", "main:added", True, None, 4), alias.connection.calls)
        self.assertIn(("exists", "main:forever"), alias.connection.calls)
        self.assertIn(("expire", "main:forever", 5), alias.connection.calls)
        self.assertIn(("persist", "main:forever"), alias.connection.calls)
        self.assertIn(("delete", "main:forever"), alias.connection.calls)

    async def test_zero_ttl_set_and_add_use_plain_set_commands(self) -> None:
        alias = FakeBinaryAlias()
        cache = RedisCache(client=alias, namespace="main")

        await cache.set("set-int", 1, ttl=0)
        await cache.set("set-float", 2, ttl=0.0)
        await cache.add("add-int", 3, ttl=0)
        await cache.add("add-float", 4, ttl=0.0)

        self.assertIn(("set", "main:set-int", False, None, None), alias.connection.calls)
        self.assertIn(("set", "main:set-float", False, None, None), alias.connection.calls)
        self.assertIn(("set", "main:add-int", True, None, None), alias.connection.calls)
        self.assertIn(("set", "main:add-float", True, None, None), alias.connection.calls)

    async def test_expire_preserves_float_milliseconds_and_zero_persists(self) -> None:
        alias = FakeBinaryAlias()
        cache = RedisCache(client=alias, namespace="main")
        await cache.set("key", "value")

        self.assertTrue(await cache.expire("key", 0.2))
        self.assertTrue(await cache.expire("key", 2))
        self.assertTrue(await cache.expire("key", 0))

        self.assertIn(("pexpire", "main:key", 200), alias.connection.calls)
        self.assertIn(("expire", "main:key", 2), alias.connection.calls)
        self.assertIn(("persist", "main:key"), alias.connection.calls)

    async def test_empty_namespace_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-empty namespace"):
            RedisCache(client=FakeBinaryAlias(), namespace="")

    async def test_explicit_namespace_is_immutable_from_construction(self) -> None:
        for replacement in ("other", ""):
            with self.subTest(replacement=replacement):
                alias = FakeBinaryAlias()
                cache = RedisCache(client=alias, namespace="main")
                with self.assertRaisesRegex(AttributeError, "namespace"):
                    cache.namespace = replacement
                self.assertEqual("main:key", cache.build_key("key"))
                await cache.clear()
                self.assertEqual(["main:*"], alias.connection.scan_patterns)

    async def test_settings_namespace_only_binds_on_first_operation(self) -> None:
        settings_source = Mock(
            return_value=RedisCacheConfig(client="CACHE", namespace="main", serializer="pickle")
        )
        registry = Mock()
        registry.using.return_value = FakeBinaryAlias()

        unbound = RedisCache(settings_source=settings_source)
        with self.assertRaisesRegex(AttributeError, "namespace"):
            unbound.namespace = "injected"

        cache = RedisCache(settings_source=settings_source)
        with patch("oldman.cache.backends.redis.redis_client", registry):
            await cache.exists("key")
            for replacement in ("other", ""):
                with self.subTest(replacement=replacement):
                    with self.assertRaisesRegex(AttributeError, "namespace"):
                        cache.namespace = replacement
            await cache.clear()

        self.assertEqual("main:key", cache.build_key("key"))
        self.assertEqual(["main:*"], registry.using.return_value.connection.scan_patterns)

    async def test_delete_match_and_clear_only_scan_current_namespace(self) -> None:
        alias = FakeBinaryAlias()
        cache = RedisCache(client=alias, namespace="main")
        await cache.delete_match("user:*")
        await cache.clear()
        self.assertEqual(["main:user:*", "main:*"], alias.connection.scan_patterns)
        self.assertFalse(any(call[0] in {"keys", "flushdb", "flushall"} for call in alias.connection.calls))

    async def test_clear_escapes_redis_glob_characters_in_namespace(self) -> None:
        namespace = "tenant*?[x]\\"
        owned_key = f"{namespace}:owned"
        foreign_key = "tenantZZqx:foreign"
        alias = FakeBinaryAlias()
        alias.connection.values.update({owned_key: b"owned", foreign_key: b"foreign"})
        cache = RedisCache(client=alias, namespace=namespace)

        await cache.clear()

        self.assertNotIn(owned_key, alias.connection.values)
        self.assertIn(foreign_key, alias.connection.values)
        self.assertEqual([r"tenant\*\?\[x]\\:*"], alias.connection.scan_patterns)

    async def test_delete_match_preserves_user_glob_after_escaped_namespace(self) -> None:
        namespace = "tenant*?[x]\\"
        first_owned = f"{namespace}:user:1"
        second_owned = f"{namespace}:user:2"
        retained_owned = f"{namespace}:job:1"
        foreign_key = "tenantZZqx:user:9"
        alias = FakeBinaryAlias()
        alias.connection.values.update(
            {
                first_owned: b"one",
                second_owned: b"two",
                retained_owned: b"job",
                foreign_key: b"foreign",
            }
        )
        cache = RedisCache(client=alias, namespace=namespace)

        self.assertEqual(2, await cache.delete_match("user:?"))

        self.assertNotIn(first_owned, alias.connection.values)
        self.assertNotIn(second_owned, alias.connection.values)
        self.assertIn(retained_owned, alias.connection.values)
        self.assertIn(foreign_key, alias.connection.values)
        self.assertEqual([r"tenant\*\?\[x]\\:user:?"], alias.connection.scan_patterns)

    async def test_delete_match_scans_to_zero_and_deletes_each_batch(self) -> None:
        alias = FakeBinaryAlias(
            scan_pages=[
                (7, [b"main:user:1", b"main:user:2"]),
                (0, [b"main:user:3"]),
            ]
        )
        alias.connection.values.update(
            {
                "main:user:1": b"one",
                "main:user:2": b"two",
                "main:user:3": b"three",
            }
        )
        cache = RedisCache(client=alias, namespace="main")

        self.assertEqual(3, await cache.delete_match("user:*"))
        self.assertIn(("scan", 0, "main:user:*", 100), alias.connection.calls)
        self.assertIn(("scan", 7, "main:user:*", 100), alias.connection.calls)
        self.assertIn(("delete", b"main:user:1", b"main:user:2"), alias.connection.calls)
        self.assertIn(("delete", b"main:user:3"), alias.connection.calls)

    async def test_ttl_uses_pttl_and_preserves_sentinels(self) -> None:
        alias = FakeBinaryAlias(pttl_values=[1250, -1, -2])
        cache = RedisCache(client=alias, namespace="main")
        self.assertEqual(1.25, await cache.ttl("expiring"))
        self.assertEqual(-1, await cache.ttl("forever"))
        self.assertEqual(-2, await cache.ttl("missing"))
        self.assertEqual(
            [("pttl", "main:expiring"), ("pttl", "main:forever"), ("pttl", "main:missing")],
            [call for call in alias.connection.calls if call[0] == "pttl"],
        )

    async def test_close_does_not_close_alias_or_registry(self) -> None:
        alias = FakeBinaryAlias()
        cache = RedisCache(client=alias, namespace="main")
        await cache.close()
        self.assertEqual(0, alias.close_count)

    async def test_string_alias_is_resolved_only_on_first_operation(self) -> None:
        registry = Mock()
        registry.using.return_value = FakeBinaryAlias()
        with patch("oldman.cache.backends.redis.redis_client", registry):
            cache = RedisCache(client="CACHE", namespace="main")
            registry.using.assert_not_called()
            await cache.exists("key")
        registry.using.assert_called_once_with("CACHE")

    async def test_global_cache_binds_settings_only_on_first_operation(self) -> None:
        settings_source = Mock(
            return_value=RedisCacheConfig(client="CACHE", namespace="main", serializer="pickle")
        )
        cache = RedisCache(settings_source=settings_source)
        registry = Mock()
        registry.using.return_value = FakeBinaryAlias()
        with patch("oldman.cache.backends.redis.redis_client", registry):
            settings_source.assert_not_called()
            registry.using.assert_not_called()
            await cache.exists("key")
        settings_source.assert_called_once_with()
        registry.using.assert_called_once_with("CACHE")
        self.assertEqual("main", cache.namespace)

    async def test_provider_errors_propagate_without_wrapping(self) -> None:
        error = RuntimeError("redis unavailable")
        cache = RedisCache(client=FakeBinaryAlias(get_error=error), namespace="main")
        with self.assertRaises(RuntimeError) as caught:
            await cache.get("key")
        self.assertIs(error, caught.exception)

    def test_backend_package_reexports_the_module_singleton(self) -> None:
        self.assertIs(exported_redis_cache, module_redis_cache)
        self.assertIsInstance(exported_redis_cache, RedisCache)


if __name__ == "__main__":
    unittest.main()
