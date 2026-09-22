"""The fingerprint guard: opt-in twice, loud when misconfigured, and actually wired."""

from __future__ import annotations

import base64
import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import ujson
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sanic.exceptions import SanicException

import oldman.conf as conf
from oldman.conf.schemas import FingerprintSecurityConfig
from oldman.web.exceptions import Forbidden, TooManyRequests
from oldman.web.security.guard import FINGERPRINT_HEADER, fingerprint_required

RAW_KEY = os.urandom(32)
SHARED_KEY = base64.b64encode(RAW_KEY).decode("ascii")
VISITOR = "visitor-identifier-0001"


def browser_payload(visitor_id: str = VISITOR, *, age_ms: int = 0) -> str:
    """Build what the browser module sends: Base64(IV || ciphertext || tag)."""
    nonce = os.urandom(12)
    body = ujson.dumps({"vid": visitor_id, "ts": int(time.time() * 1000) - age_ms}).encode()
    return base64.b64encode(nonce + AESGCM(RAW_KEY).encrypt(nonce, body, None)).decode("ascii")


def settings(*, enabled: bool = True, key: str | None = SHARED_KEY) -> SimpleNamespace:
    """Only the fields the guard reads."""
    fingerprint = FingerprintSecurityConfig(enabled=enabled, aes_secret_key=key)
    return SimpleNamespace(
        web=SimpleNamespace(
            security=SimpleNamespace(fingerprint=fingerprint),
            session=SimpleNamespace(redis_alias="SESSION"),
        )
    )


class Allowed:
    """A limiter that lets everything through."""

    async def check(self, *_: object) -> SimpleNamespace:
        return SimpleNamespace(allowed=True, reason="ok", fingerprint_count=1, ip_count=1, anomalies=[])


class Refused:
    """A limiter that refuses everything."""

    async def check(self, *_: object) -> SimpleNamespace:
        return SimpleNamespace(allowed=False, reason="fp_rate_exceeded", fingerprint_count=99, ip_count=99, anomalies=[])


def request_with(payload: str | None) -> SimpleNamespace:
    """A request stand-in carrying only what the guard touches."""
    headers = {FINGERPRINT_HEADER: payload} if payload is not None else {}
    return SimpleNamespace(
        headers=headers,
        client_ip="203.0.113.7",
        ip="203.0.113.7",
        ctx=SimpleNamespace(),
        app=SimpleNamespace(ctx=SimpleNamespace()),
    )


class FingerprintGuardTest(unittest.IsolatedAsyncioTestCase):
    """Nothing enforced a fingerprint before this guard; these pin what it enforces now."""

    def setUp(self) -> None:
        """Route handlers record that they ran, and the visitor id they saw."""
        self.seen: list[str] = []

        @fingerprint_required(endpoint="default")
        async def handler(request: object) -> str:
            self.seen.append(request.ctx.visitor_id)  # type: ignore[attr-defined]
            return "ok"

        self.handler = handler

    async def call(self, request: object, *, limiter: object | None = None) -> object:
        """Run the guarded handler with an injected limiter."""
        with patch("oldman.web.security.guard._rate_limiter", return_value=limiter or Allowed()):
            return await self.handler(request)

    async def test_a_route_asking_for_a_disabled_subsystem_is_a_loud_error(self) -> None:
        """Silently passing through would leave the route looking protected."""
        with patch.dict(conf.__dict__, {"settings": settings(enabled=False)}):
            with self.assertRaisesRegex(RuntimeError, "fingerprint.enabled"):
                await self.call(request_with(browser_payload()))

    async def test_an_enabled_subsystem_without_a_key_is_a_loud_error(self) -> None:
        """The key is only required once the feature is on, and then it really is required."""
        with patch.dict(conf.__dict__, {"settings": settings(key=None)}):
            with self.assertRaisesRegex(RuntimeError, "aes_secret_key"):
                await self.call(request_with(browser_payload()))

    async def test_a_valid_payload_reaches_the_handler_with_its_visitor_id(self) -> None:
        """The happy path is what the demo page shows."""
        with patch.dict(conf.__dict__, {"settings": settings()}):
            self.assertEqual("ok", await self.call(request_with(browser_payload())))
        self.assertEqual([VISITOR], self.seen)

    async def test_a_missing_header_is_refused_and_recorded(self) -> None:
        """A scripted client that skips the page's crypto does not get through."""
        with (
            patch.dict(conf.__dict__, {"settings": settings()}),
            patch("oldman.web.security.guard.log_fake_fingerprint_attempt", new=AsyncMock()) as recorded,
        ):
            with self.assertRaises(Forbidden):
                await self.call(request_with(None))
        recorded.assert_awaited_once()
        assert recorded.await_args is not None
        self.assertEqual("missing_header", recorded.await_args.args[1])

    async def test_a_forged_payload_is_refused(self) -> None:
        """Anything that does not decrypt under the shared key is rejected."""
        with (
            patch.dict(conf.__dict__, {"settings": settings()}),
            patch("oldman.web.security.guard.log_fake_fingerprint_attempt", new=AsyncMock()),
        ):
            with self.assertRaises(Forbidden):
                await self.call(request_with(base64.b64encode(os.urandom(64)).decode()))
        self.assertEqual([], self.seen)

    async def test_a_stale_payload_is_refused_so_timestamp_max_diff_finally_does_something(self) -> None:
        """This setting was declared, validated and documented, and read by nobody."""
        config = FingerprintSecurityConfig(enabled=True, aes_secret_key=SHARED_KEY)
        stale = browser_payload(age_ms=config.timestamp_max_diff + 60_000)
        with (
            patch.dict(conf.__dict__, {"settings": settings()}),
            patch("oldman.web.security.guard.log_fake_fingerprint_attempt", new=AsyncMock()) as recorded,
        ):
            with self.assertRaises(Forbidden):
                await self.call(request_with(stale))
        assert recorded.await_args is not None
        self.assertEqual("timestamp_expired", recorded.await_args.args[1])

    async def test_a_rate_limited_visitor_gets_429_with_retry_after(self) -> None:
        """The limiter existed with zero callers; now a refusal reaches the client."""
        with patch.dict(conf.__dict__, {"settings": settings()}):
            with self.assertRaises(TooManyRequests) as caught:
                await self.call(request_with(browser_payload()), limiter=Refused())
        self.assertEqual(429, caught.exception.status_code)
        self.assertIn("Retry-After", caught.exception.headers)
        self.assertTrue(issubclass(TooManyRequests, SanicException))


if __name__ == "__main__":
    unittest.main()
