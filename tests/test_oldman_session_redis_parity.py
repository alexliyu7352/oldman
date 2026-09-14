"""Real Redis integration tests for strongly typed Web sessions."""

from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import msgspec
from sanic import Request, Sanic
from sanic.response import BaseHTTPResponse, empty, text

from oldman.conf.schemas import RedisConfig
from oldman.providers.redis import RedisClientRegistry
from oldman.serializers import MsgspecModel
from oldman.web.session import DefaultSessionInterface, Session, SessionData, get_session_data
from tests.redis_support import RedisProcess, require_redis_server


class SessionProfile(MsgspecModel, kw_only=True):
    """Nested typed data used to exercise complete snapshot detection."""

    roles: list[str] = msgspec.field(default_factory=list)


class AdminSessionData(SessionData, kw_only=True):
    """Representative application session payload."""

    profile: SessionProfile = msgspec.field(default_factory=SessionProfile)


class OtherSessionData(SessionData, kw_only=True):
    """Wrong configured model used by validation tests."""

    label: str = ""


class MissingDefaultSessionData(SessionData, kw_only=True):
    """Invalid application model whose required field blocks anonymous sessions."""

    required_value: str


class WrongDefaultTypeSessionData(SessionData, kw_only=True):
    """Invalid model whose direct constructor bypasses msgspec type checks."""

    count: int = cast(int, "not-an-integer")


class PrivilegedDefaultSessionData(SessionData, kw_only=True):
    """Invalid model whose anonymous defaults contain authorization claims."""

    is_staff: bool = True


class RedisSessionIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """Exercise session semantics against an owned redis-server process."""

    @classmethod
    def setUpClass(cls) -> None:
        """Start one isolated Redis Unix socket for this test class."""
        cls._temporary_directory = tempfile.TemporaryDirectory()
        cls._redis_process = RedisProcess(require_redis_server(), Path(cls._temporary_directory.name), "redis")
        cls._socket_path = cls._redis_process.socket_path

    @classmethod
    def tearDownClass(cls) -> None:
        """Stop the owned Redis process and remove its socket directory."""
        cls._redis_process.stop()
        cls._temporary_directory.cleanup()

    async def asyncSetUp(self) -> None:
        """Create a fresh registry and initialized typed interface per test."""
        redis_url = f"unix://{self._socket_path.as_posix()}?db=0"
        config = RedisConfig.model_validate(
            {
                "SESSION": {"redis_url": redis_url, "health_check_interval": 0},
                "ADMIN_SESSION": {"redis_url": redis_url, "health_check_interval": 0},
            }
        )
        self.registry = RedisClientRegistry(config)
        self.redis_patch = patch("oldman.web.session.base.redis_client", self.registry)
        self.redis_patch.start()
        self.interface = DefaultSessionInterface(
            expiry=60,
            prefix="session-test:",
            user_prefix="user-session-test:",
            cookie_name="session-test-id",
            session_model=AdminSessionData,
        )
        self.connection = await self.registry.using("SESSION").async_get_bin_conn()
        await self.connection.flushdb()

    async def asyncTearDown(self) -> None:
        """Close every per-test Redis client before its event loop is destroyed."""
        try:
            await self.registry.close()
        finally:
            self.redis_patch.stop()

    def request(self, cookies: dict[str, str] | None = None) -> Request:
        """Build the minimum request shape consumed by Session middleware."""
        manager = Session()
        manager.interface = self.interface
        return cast(
            Request,
            SimpleNamespace(
                cookies=cookies or {},
                ctx=SimpleNamespace(),
                app=SimpleNamespace(ctx=SimpleNamespace(session=manager)),
            ),
        )

    @staticmethod
    def response() -> BaseHTTPResponse:
        """Return a real Sanic response so cookie behavior uses production code."""
        return empty()

    def state_sid(self, request: Request) -> str:
        """Read the private SID only for black-box Redis assertions."""
        state = self.interface._request_state(request, required=True)
        assert state is not None
        return state.sid

    async def test_unknown_sid_is_rotated_without_writing_an_unchanged_session(self) -> None:
        """An attacker-provided missing SID is neither reused nor eagerly persisted."""
        request = self.request({self.interface.cookie_name: "attacker-controlled"})
        response = self.response()

        data = await self.interface.open(request)
        await self.interface.save(request, response)

        self.assertIs(type(data), AdminSessionData)
        self.assertNotEqual("attacker-controlled", self.state_sid(request))
        self.assertEqual(0, await self.connection.dbsize())
        self.assertNotIn("set-cookie", response.headers)

    async def test_get_session_id_uses_middleware_state_instead_of_the_cookie(self) -> None:
        """The public SID is the validated transport state captured by open()."""
        request = self.request({self.interface.cookie_name: "attacker-controlled"})

        await self.interface.open(request)
        request.cookies[self.interface.cookie_name] = "changed-after-open"
        manager = Session.get_session_manager(request)

        self.assertEqual(self.state_sid(request), manager.get_session_id(request))
        self.assertNotEqual("attacker-controlled", manager.get_session_id(request))
        self.assertNotEqual("changed-after-open", manager.get_session_id(request))

    async def test_nested_model_change_is_saved_and_restored_as_the_concrete_type(self) -> None:
        """Snapshot comparison detects nested mutations without a dict mutator."""
        request = self.request()
        response = self.response()
        data = cast(AdminSessionData, await self.interface.open(request))
        data.profile.roles.append("staff")

        await self.interface.save(request, response)
        sid = self.state_sid(request)
        restored_request = self.request({self.interface.cookie_name: sid})
        restored = await self.interface.open(restored_request)

        self.assertIs(type(restored), AdminSessionData)
        self.assertEqual(["staff"], cast(AdminSessionData, restored).profile.roles)
        self.assertIn("set-cookie", response.headers)
        self.assertIs(get_session_data(restored_request, AdminSessionData), restored)

    async def test_existing_anonymous_session_cannot_be_restored_by_a_stale_save(self) -> None:
        """An anonymous update succeeds only while its previously loaded SID still exists."""
        create_request = self.request()
        created = cast(AdminSessionData, await self.interface.open(create_request))
        created.username = "persisted"
        await self.interface.save(create_request, self.response())
        sid = self.state_sid(create_request)

        update_request = self.request({self.interface.cookie_name: sid})
        updated = cast(AdminSessionData, await self.interface.open(update_request))
        updated.username = "updated"
        await self.interface.save(update_request, self.response())
        stored_payload = await self.connection.get(self.interface._get_session_key(sid))
        stored = msgspec.msgpack.Decoder(type=AdminSessionData).decode(stored_payload)
        self.assertEqual("updated", stored.username)

        stale_request = self.request({self.interface.cookie_name: sid})
        stale = cast(AdminSessionData, await self.interface.open(stale_request))
        await self.interface.logout(sid)
        stale.username = "must-not-return"
        stale_response = self.response()
        await self.interface.save(stale_request, stale_response)

        self.assertEqual(0, await self.connection.exists(self.interface._get_session_key(sid)))
        self.assertNotIn("set-cookie", stale_response.headers)

    async def test_redis_value_is_the_direct_typed_session_model(self) -> None:
        """Persistence has no Raw or outer record envelope around SessionData."""
        login_data = AdminSessionData(
            expiry=45,
            user_id=101,
            is_active=True,
            username="alice",
            is_staff=True,
            is_superuser=True,
        )

        sid = await self.interface.login(login_data)
        payload = await self.connection.get(self.interface._get_session_key(sid))

        self.assertIsNotNone(payload)
        decoded = msgspec.msgpack.Decoder(type=AdminSessionData).decode(payload)
        self.assertIs(type(decoded), AdminSessionData)
        self.assertEqual(45, decoded.expiry)
        self.assertEqual(101, decoded.user_id)
        self.assertEqual("alice", decoded.username)
        self.assertTrue(decoded.is_staff)
        self.assertTrue(decoded.is_superuser)

    async def test_integer_user_ids_use_decimal_redis_index_keys(self) -> None:
        """Zero and negative IDs remain integers until the Redis key boundary."""
        for user_id in (0, -7):
            with self.subTest(user_id=user_id):
                sid = await self.interface.login(AdminSessionData(user_id=user_id, is_active=True))

                self.assertEqual(f"user-session-test:{user_id}", self.interface._get_user_key(user_id))
                self.assertEqual((sid,), await self.interface.get_active_session_ids(user_id))
                self.assertTrue(await self.interface.validate_session(sid, user_id))
                self.assertEqual((sid,), await self.interface.force_logout_user(user_id))

        for invalid_user_id in (cast(int, "1"), cast(int, True)):
            with self.subTest(invalid_user_id=invalid_user_id):
                with self.assertRaisesRegex(TypeError, "user_id must be an int"):
                    await self.interface.get_active_session_ids(invalid_user_id)

    async def test_schema_defaults_and_unknown_fields_do_not_trigger_an_untouched_write(self) -> None:
        """Canonical comparison preserves an older payload until the model really changes."""
        sid = "schema-compatible"
        key = self.interface._get_session_key(sid)
        older_payload = msgspec.msgpack.encode(
            {
                "expiry": 30,
                "user_id": None,
                "is_active": False,
                "username": "legacy",
                "profile": {"roles": []},
                "future_field": "must-survive-an-untouched-request",
            }
        )
        await self.connection.set(key, older_payload, ex=30)
        request = self.request({self.interface.cookie_name: sid})
        response = self.response()

        opened = cast(AdminSessionData, await self.interface.open(request))
        await self.interface.save(request, response)

        self.assertFalse(opened.is_staff)
        self.assertEqual(older_payload, await self.connection.get(key))
        self.assertNotIn("set-cookie", response.headers)

    async def test_ordinary_and_exclusive_login_share_one_multi_sid_index(self) -> None:
        """Ordinary logins coexist and an exclusive login revokes all predecessors."""
        login_data = AdminSessionData(
            user_id=1,
            is_active=True,
            username="alice",
            is_staff=True,
        )
        original = login_data.to_msgpack()

        first = await self.interface.login(login_data)
        second = await self.interface.login(login_data)

        self.assertEqual(original, login_data.to_msgpack())
        self.assertEqual({first, second}, set(await self.interface.get_active_session_ids(1)))
        self.assertTrue(await self.interface.is_user_online(1))
        self.assertFalse(await self.interface.validate_exclusive_session(first, 1))

        exclusive = await self.interface.exclusive_login(login_data)

        self.assertEqual((exclusive,), await self.interface.get_active_session_ids(1))
        self.assertTrue(await self.interface.validate_exclusive_session(exclusive, 1))
        self.assertEqual(0, await self.connection.exists(self.interface._get_session_key(first)))
        self.assertEqual(0, await self.connection.exists(self.interface._get_session_key(second)))

        orphan = "unindexed-session"
        exclusive_payload = await self.connection.get(self.interface._get_session_key(exclusive))
        await self.connection.set(self.interface._get_session_key(orphan), exclusive_payload, ex=60)
        self.assertFalse(await self.interface.validate_exclusive_session(orphan, 1))
        self.assertEqual(0, await self.connection.exists(self.interface._get_session_key(orphan)))

    async def test_ordinary_session_validation_covers_lifecycle_and_user_ownership(self) -> None:
        """Every ordinary login remains valid only while its value and user index agree."""
        data = AdminSessionData(user_id=2, is_active=True, username="alice")
        first = await self.interface.login(data)
        second = await self.interface.login(data)

        self.assertTrue(await self.interface.validate_session(first, 2))
        self.assertTrue(await self.interface.validate_session(second, 2))
        self.assertFalse(await self.interface.validate_session(first, 3))
        self.assertEqual(1, await self.connection.exists(self.interface._get_session_key(first)))

        await self.interface.logout(first)
        self.assertFalse(await self.interface.validate_session(first, 2))
        self.assertTrue(await self.interface.validate_session(second, 2))

        await self.interface.force_logout_user(2)
        self.assertFalse(await self.interface.validate_session(second, 2))
        self.assertFalse(await self.interface.validate_session("", 2))

    async def test_session_validation_cleans_only_safe_index_inconsistencies(self) -> None:
        """Orphan indexes are removed, while unindexed values are left untouched."""
        data = AdminSessionData(user_id=4, is_active=True, username="alice")
        indexed_without_value = await self.interface.login(data)
        user_key = self.interface._get_user_key(4)
        await self.connection.delete(self.interface._get_session_key(indexed_without_value))

        self.assertFalse(await self.interface.validate_session(indexed_without_value, 4))
        self.assertIsNone(await self.connection.zscore(user_key, indexed_without_value))

        value_without_index = await self.interface.login(data)
        session_key = self.interface._get_session_key(value_without_index)
        await self.connection.zrem(user_key, value_without_index)

        self.assertFalse(await self.interface.validate_session(value_without_index, 4))
        self.assertEqual(1, await self.connection.exists(session_key))

    async def test_session_validation_removes_expired_index_without_deleting_value(self) -> None:
        """An expired member is invalid, but its still-live value is not guessed to be owned."""
        data = AdminSessionData(user_id=5, is_active=True, username="alice")
        sid = await self.interface.login(data)
        user_key = self.interface._get_user_key(5)
        session_key = self.interface._get_session_key(sid)
        await self.connection.zadd(user_key, {sid: 0})

        self.assertFalse(await self.interface.validate_session(sid, 5))
        self.assertIsNone(await self.connection.zscore(user_key, sid))
        self.assertEqual(1, await self.connection.exists(session_key))

    async def test_session_validation_does_not_refresh_value_ttl_or_member_score(self) -> None:
        """Long-lived SSE checks observe expiry without extending the login."""
        data = AdminSessionData(expiry=20, user_id=6, is_active=True, username="alice")
        sid = await self.interface.login(data)
        session_key = self.interface._get_session_key(sid)
        user_key = self.interface._get_user_key(6)
        ttl_before = await self.connection.pttl(session_key)
        index_ttl_before = await self.connection.pttl(user_key)
        score_before = await self.connection.zscore(user_key, sid)

        self.assertTrue(await self.interface.validate_session(sid, 6))

        ttl_after = await self.connection.pttl(session_key)
        index_ttl_after = await self.connection.pttl(user_key)
        score_after = await self.connection.zscore(user_key, sid)
        self.assertLessEqual(ttl_after, ttl_before)
        self.assertGreater(ttl_after, ttl_before - 1000)
        self.assertLessEqual(index_ttl_after, index_ttl_before)
        self.assertGreater(index_ttl_after, index_ttl_before - 1000)
        self.assertEqual(score_before, score_after)

    async def test_logout_removes_only_its_sid_and_force_logout_removes_the_rest(self) -> None:
        """A stale logout cannot erase another valid ordinary login."""
        login_data = AdminSessionData(user_id=7, is_active=True, username="bob")
        first = await self.interface.login(login_data)
        second = await self.interface.login(login_data)

        await self.interface.logout(first)
        await self.interface.logout(first)

        self.assertEqual((second,), await self.interface.get_active_session_ids(7))
        self.assertEqual(1, await self.connection.exists(self.interface._get_session_key(second)))
        self.assertEqual((second,), await self.interface.force_logout_user(7))
        self.assertFalse(await self.interface.is_user_online(7))

    async def test_logout_resolves_identity_and_a_stale_save_cannot_restore_the_sid(self) -> None:
        """Public logout removes the authoritative index before an old response saves."""
        login_data = AdminSessionData(user_id=8, is_active=True, username="before")
        sid = await self.interface.login(login_data)
        stale_request = self.request({self.interface.cookie_name: sid})
        stale_data = cast(AdminSessionData, await self.interface.open(stale_request))

        await self.interface.logout(sid)
        stale_data.username = "after-logout"
        response = self.response()
        await self.interface.save(stale_request, response)

        self.assertEqual(0, await self.connection.exists(self.interface._get_session_key(sid)))
        self.assertEqual((), await self.interface.get_active_session_ids(8))
        self.assertNotIn("set-cookie", response.headers)

    async def test_modified_stale_request_cannot_resurrect_an_exclusively_revoked_sid(self) -> None:
        """A response racing with a newer exclusive login is failed closed."""
        first_data = AdminSessionData(user_id=9, is_active=True, username="carol")
        first_sid = await self.interface.exclusive_login(first_data)
        stale_request = self.request({self.interface.cookie_name: first_sid})
        stale_data = cast(AdminSessionData, await self.interface.open(stale_request))

        second_sid = await self.interface.exclusive_login(first_data)
        stale_data.profile.roles.append("stale-write")
        response = self.response()
        await self.interface.save(stale_request, response)

        self.assertEqual((second_sid,), await self.interface.get_active_session_ids(9))
        self.assertEqual(0, await self.connection.exists(self.interface._get_session_key(first_sid)))
        self.assertNotIn("set-cookie", response.headers)

    async def test_concurrent_logins_and_stale_saves_leave_only_the_exclusive_sid(self) -> None:
        """Concurrent stale responses cannot race an exclusive login into reviving old SIDs."""
        login_data = AdminSessionData(user_id=10, is_active=True, username="before")
        ordinary_sids = await asyncio.gather(*(self.interface.login(login_data) for _ in range(40)))
        stale_requests: list[Request] = []
        for sid in ordinary_sids[:20]:
            request = self.request({self.interface.cookie_name: sid})
            data = cast(AdminSessionData, await self.interface.open(request))
            data.username = "stale-write"
            stale_requests.append(request)

        exclusive_task = asyncio.create_task(self.interface.exclusive_login(login_data))
        save_tasks = [asyncio.create_task(self.interface.save(request, self.response())) for request in stale_requests]
        exclusive_sid = await exclusive_task
        await asyncio.gather(*save_tasks)

        self.assertEqual((exclusive_sid,), await self.interface.get_active_session_ids(10))
        for sid in ordinary_sids:
            self.assertEqual(0, await self.connection.exists(self.interface._get_session_key(sid)))

    async def test_stale_save_cannot_delete_a_new_cookie_already_set_on_the_response(self) -> None:
        """A replacement login cookie wins over persistence from its revoked request SID."""
        old_data = AdminSessionData(user_id=11, is_active=True, username="old")
        old_sid = await self.interface.exclusive_login(old_data)
        stale_request = self.request({self.interface.cookie_name: old_sid})
        stale_data = cast(AdminSessionData, await self.interface.open(stale_request))
        stale_data.username = "stale-change"

        new_data = AdminSessionData(user_id=11, is_active=True, username="new")
        new_sid = await self.interface.exclusive_login(new_data)
        response = self.response()
        self.interface.update_session_id_to_cookie(response, new_sid, new_data)

        await self.interface.save(stale_request, response)

        cookie = response.cookies.get_cookie(self.interface.cookie_name)
        self.assertIsNotNone(cookie)
        assert cookie is not None
        self.assertEqual(new_sid, cookie.value)
        self.assertIsNotNone(cookie.max_age)
        assert cookie.max_age is not None
        self.assertGreater(cookie.max_age, 0)

    async def test_authenticated_save_refreshes_session_and_index_expiry_together(self) -> None:
        """The session TTL, member score, and index TTL remain aligned."""
        login_data = AdminSessionData(expiry=20, user_id=12, is_active=True, username="dana")
        sid = await self.interface.login(login_data)
        request = self.request({self.interface.cookie_name: sid})
        data = cast(AdminSessionData, await self.interface.open(request))
        data.profile.roles.append("owner")

        response = self.response()
        await self.interface.save(request, response)

        session_key = self.interface._get_session_key(sid)
        user_key = self.interface._get_user_key(12)
        session_ttl = await self.connection.ttl(session_key)
        index_ttl = await self.connection.ttl(user_key)
        redis_time = await self.connection.time()
        redis_now_ms = int(redis_time[0]) * 1000 + int(redis_time[1]) // 1000
        score = await self.connection.zscore(user_key, sid)
        assert score is not None
        cookie = response.cookies.get_cookie(self.interface.cookie_name)
        self.assertIsNotNone(cookie)
        assert cookie is not None

        self.assertGreaterEqual(session_ttl, 18)
        self.assertLessEqual(session_ttl, 20)
        self.assertLessEqual(abs(index_ttl - session_ttl), 1)
        self.assertLessEqual(abs(((int(score) - redis_now_ms) // 1000) - session_ttl), 1)
        self.assertEqual(20, cookie.max_age)

    async def test_corrupt_json_and_wrong_typed_payloads_are_deleted_fail_closed(self) -> None:
        """Legacy or malformed values become fresh anonymous sessions, never 500s."""
        payloads = (
            b'{"legacy": true}',
            msgspec.msgpack.encode(
                {
                    "expiry": 60,
                    "user_id": "user-5",
                    "is_active": True,
                    "username": 123,
                    "is_staff": False,
                    "profile": {"roles": []},
                }
            ),
        )

        for index, payload in enumerate(payloads):
            with self.subTest(index=index):
                old_sid = f"invalid-{index}"
                old_key = self.interface._get_session_key(old_sid)
                await self.connection.set(old_key, payload, ex=60)
                request = self.request({self.interface.cookie_name: old_sid})

                data = await self.interface.open(request)

                self.assertTrue(data.is_anonymous)
                self.assertNotEqual(old_sid, self.state_sid(request))
                self.assertEqual(0, await self.connection.exists(old_key))

    async def test_invalid_logout_wins_over_a_concurrent_authenticated_save(self) -> None:
        """A save completed before invalid logout is removed with the corrupt SID."""
        login_data = AdminSessionData(user_id=13, is_active=True, username="before")
        sid = await self.interface.login(login_data)
        stale_request = self.request({self.interface.cookie_name: sid})
        stale_data = cast(AdminSessionData, await self.interface.open(stale_request))
        stale_data.username = "concurrent-save"
        key = self.interface._get_session_key(sid)
        await self.connection.set(key, b"invalid-before-concurrent-save", ex=60)
        original_delete = self.connection.delete

        async def delete_after_stale_save(*keys: str) -> int:
            """Complete the real stale save immediately before invalidation."""
            await self.interface.save(stale_request, self.response())
            return await original_delete(*keys)

        with patch.object(self.connection, "delete", side_effect=delete_after_stale_save):
            await self.interface.logout(sid)

        self.assertEqual(0, await self.connection.exists(key))
        self.assertEqual((), await self.interface.get_active_session_ids(13))

    async def test_invalid_logout_blocks_a_later_stale_save_and_redacts_the_sid(self) -> None:
        """Invalidation is final and its warning contains no reusable credential."""
        login_data = AdminSessionData(user_id=14, is_active=True, username="before")
        sid = await self.interface.login(login_data)
        stale_request = self.request({self.interface.cookie_name: sid})
        stale_data = cast(AdminSessionData, await self.interface.open(stale_request))
        stale_data.username = "must-not-return"
        key = self.interface._get_session_key(sid)
        user_key = self.interface._get_user_key(14)
        invalid_payload = b"secret-invalid-session-payload"
        await self.connection.set(key, invalid_payload, ex=60)
        with patch("oldman.web.session.base.logger.warning") as warning:
            await self.interface.logout(sid)

        self.assertEqual(0, await self.connection.exists(key))
        rendered_calls = " ".join(str(call) for call in warning.call_args_list)
        self.assertNotIn(sid, rendered_calls)
        self.assertNotIn(repr(invalid_payload), rendered_calls)

        response = self.response()
        await self.interface.save(stale_request, response)

        self.assertEqual(0, await self.connection.exists(key))
        self.assertIsNone(await self.connection.zscore(user_key, sid))
        self.assertEqual((), await self.interface.get_active_session_ids(14))
        self.assertNotIn("set-cookie", response.headers)

    async def test_login_validation_and_direct_authentication_transition_fail_before_writes(self) -> None:
        """Wrong models and identity changes cannot bypass the login path."""
        with self.assertRaisesRegex(TypeError, "AdminSessionData"):
            await self.interface.login(OtherSessionData(user_id=15, is_active=True))
        with self.assertRaisesRegex(ValueError, "requires (a )?user_id"):
            await self.interface.login(AdminSessionData(is_active=True))
        with self.assertRaises(msgspec.ValidationError):
            await self.interface.login(
                AdminSessionData(
                    user_id=15,
                    is_active=True,
                    username=cast(str, 123),
                )
            )
        with self.assertRaisesRegex(ValueError, "anonymous session cannot contain privileges"):
            await self.interface.login(AdminSessionData(is_staff=True))
        with self.assertRaises(msgspec.ValidationError):
            await self.interface.login(
                AdminSessionData(
                    user_id=15,
                    is_active=True,
                    is_staff=cast(bool, "yes"),
                )
            )
        with self.assertRaises(msgspec.ValidationError):
            await self.interface.login(
                AdminSessionData(
                    user_id=15,
                    is_active=True,
                    is_superuser=cast(bool, 1),
                )
            )
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            await self.interface.login(AdminSessionData(expiry=0, user_id=15, is_active=True))
        with self.assertRaises(msgspec.ValidationError):
            await self.interface.login(AdminSessionData(expiry=cast(int, True), user_id=15, is_active=True))

        request = self.request()
        data = cast(AdminSessionData, await self.interface.open(request))
        data.user_id = 15
        data.is_active = True
        with self.assertRaisesRegex(RuntimeError, "must be created with login"):
            await self.interface.save(request, self.response())
        self.assertEqual(0, await self.connection.dbsize())

    async def test_logout_session_deletes_redis_state_and_response_cookie(self) -> None:
        """The request helper removes one authenticated SID and marks its cookie deleted."""
        login_data = AdminSessionData(user_id=17, is_active=True, username="erin")
        sid = await self.interface.login(login_data)
        request = self.request({self.interface.cookie_name: sid})
        opened = cast(AdminSessionData, await self.interface.open(request))
        opened.user_id = 16

        await Session.logout_session(request)
        response = self.response()
        await self.interface.save(request, response)

        self.assertEqual(0, await self.connection.exists(self.interface._get_session_key(sid)))
        self.assertEqual((), await self.interface.get_active_session_ids(17))
        self.assertIn("set-cookie", response.headers)

    async def test_custom_alias_uses_the_same_binary_registry_contract(self) -> None:
        """A configured custom alias initializes without fallback to SESSION."""
        interface = DefaultSessionInterface(redis_alias="ADMIN_SESSION", session_model=AdminSessionData)

        sid = await interface.login(AdminSessionData(user_id=18, is_active=True))

        self.assertEqual((sid,), await interface.get_active_session_ids(18))

    async def test_registry_close_and_script_flush_require_no_session_reinitialization(self) -> None:
        """Every operation resolves the current provider client and reloads missing Lua."""
        first = await self.interface.login(AdminSessionData(user_id=19, is_active=True))
        old_connection = await self.interface._get_redis()

        await self.registry.close()
        self.assertEqual({}, self.registry._clients)

        second = await self.interface.login(AdminSessionData(user_id=19, is_active=True))
        new_connection = await self.interface._get_redis()
        self.assertIsNot(old_connection, new_connection)
        self.assertEqual(1, len(self.registry._clients))

        await new_connection.script_flush()
        third = await self.interface.login(AdminSessionData(user_id=19, is_active=True))
        self.assertEqual({first, second, third}, set(await self.interface.get_active_session_ids(19)))

    async def test_session_model_missing_anonymous_defaults_fails_during_interface_construction(self) -> None:
        """A bad application model is rejected locally without touching Redis."""
        with self.assertRaises(TypeError):
            DefaultSessionInterface(session_model=MissingDefaultSessionData)
        with self.assertRaises(msgspec.ValidationError):
            DefaultSessionInterface(session_model=WrongDefaultTypeSessionData)
        with self.assertRaisesRegex(ValueError, "anonymous session cannot contain privileges"):
            DefaultSessionInterface(session_model=PrivilegedDefaultSessionData)

    async def test_real_sanic_lifecycle_runs_typed_request_and_response_middleware(self) -> None:
        """A real Sanic request initializes, mutates, and persists the configured model."""
        app = Sanic(f"typed-session-{time.time_ns()}")
        interface = DefaultSessionInterface(
            prefix="sanic-session-test:",
            user_prefix="sanic-user-session-test:",
            cookie_name="sanic-session-id",
            session_model=AdminSessionData,
        )
        Session(app, interface)

        @app.get("/")
        async def mutate_session(request: Request) -> BaseHTTPResponse:
            """Mutate nested state through the public statically typed accessor."""
            session = get_session_data(request, AdminSessionData)
            session.profile.roles.append("member")
            return text("ok")

        _request, response = await app.asgi_client.get("/")

        self.assertEqual(200, response.status)
        self.assertIn("sanic-session-id", response.cookies)
        sid = str(response.cookies["sanic-session-id"])
        self.assertEqual(1, await self.connection.exists(interface._get_session_key(sid)))

    async def test_real_sanic_replaces_a_success_response_when_session_validation_fails(self) -> None:
        """A response-middleware error must not be logged and returned as HTTP 200."""
        app = Sanic(f"invalid-session-save-{time.time_ns()}")
        interface = DefaultSessionInterface(
            prefix="invalid-save-test:",
            user_prefix="invalid-save-user-test:",
            session_model=AdminSessionData,
        )
        Session(app, interface)

        @app.get("/")
        async def write_invalid_runtime_type(request: Request) -> BaseHTTPResponse:
            """Bypass static typing to prove the runtime persistence boundary."""
            get_session_data(request, AdminSessionData).username = cast(str, 123)
            return text("handler-succeeded")

        _request, response = await app.asgi_client.get("/")

        self.assertEqual(500, response.status)
        self.assertNotEqual("handler-succeeded", response.text)
        self.assertEqual([], await self.connection.keys("invalid-save-test:*"))

    async def test_missing_redis_does_not_block_startup_but_returns_503_when_used(self) -> None:
        """Redis remains lazy and a real persistence failure replaces a 200 response."""
        missing_socket = Path(self._temporary_directory.name) / "missing.sock"
        failing_config = RedisConfig.model_validate(
            {
                "SESSION": {
                    "redis_url": f"unix://{missing_socket.as_posix()}?db=0",
                    "retry_attempts": 0,
                    "health_check_interval": 0,
                }
            }
        )
        failing_registry = RedisClientRegistry(failing_config)
        interface = DefaultSessionInterface(session_model=AdminSessionData)
        app = Sanic(f"missing-session-redis-{time.time_ns()}")
        Session(app, interface)

        @app.get("/")
        async def mutate_session(request: Request) -> BaseHTTPResponse:
            """Force the first real Redis use from response persistence."""
            get_session_data(request, AdminSessionData).username = "requires-redis"
            return text("handler-succeeded")

        try:
            with patch("oldman.web.session.base.redis_client", failing_registry):
                self.assertEqual({}, failing_registry._clients)
                _request, response = await app.asgi_client.get("/")
                self.assertEqual(503, response.status)
                self.assertNotEqual("handler-succeeded", response.text)
        finally:
            await failing_registry.close()

    async def test_missing_redis_returns_503_before_handler_when_cookie_requires_a_read(self) -> None:
        """A request-side Redis failure is explicit and prevents handler execution."""
        missing_socket = Path(self._temporary_directory.name) / "missing-read.sock"
        failing_config = RedisConfig.model_validate(
            {
                "SESSION": {
                    "redis_url": f"unix://{missing_socket.as_posix()}?db=0",
                    "retry_attempts": 0,
                    "health_check_interval": 0,
                }
            }
        )
        failing_registry = RedisClientRegistry(failing_config)
        interface = DefaultSessionInterface(cookie_name="missing-read-id", session_model=AdminSessionData)
        app = Sanic(f"missing-session-read-{time.time_ns()}")
        Session(app, interface)
        handler_called = False

        @app.get("/")
        async def handler(_request: Request) -> BaseHTTPResponse:
            """Record whether request middleware incorrectly allowed execution."""
            nonlocal handler_called
            handler_called = True
            return text("handler-succeeded")

        try:
            with patch("oldman.web.session.base.redis_client", failing_registry):
                _request, response = await app.asgi_client.get(
                    "/",
                    headers={"cookie": "missing-read-id=known-server-session"},
                )
                self.assertEqual(503, response.status)
                self.assertFalse(handler_called)
        finally:
            await failing_registry.close()

    def test_missing_redis_server_is_a_gate_failure_not_a_skip(self) -> None:
        """The integration requirement itself cannot be converted into a green skip."""
        with self.assertRaisesRegex(RuntimeError, "redis-server is required"):
            require_redis_server(lambda _name: None)


if __name__ == "__main__":
    unittest.main()
