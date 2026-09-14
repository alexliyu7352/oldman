"""Signed-Cookie flash message protocol and real Sanic lifecycle tests."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import unittest
import zlib
from http.cookies import SimpleCookie
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import msgspec
from sanic import Request, Sanic
from sanic.response import BaseHTTPResponse, html, redirect, text
from sanic_ext import Config, Extend
from sanic_ext.extensions.templating.extension import TemplatingExtension

import oldman.conf as conf
from oldman.conf.schemas import DefaultSettings
from oldman.web import messages
from oldman.web.messages._cookie_storage import (
    FLASH_COOKIE_NAME,
    FLASH_COOKIE_VALUE_LIMIT,
    _FlashCookieCodec,
    _InvalidFlashCookie,
)
from oldman.web.messages.flash import _FlashRequestStorage

_ROOT_SECRET = "oldman-web-messages-test-root-secret"
_CODEC_KEY = "oldman-web-messages-test-codec-key"
_FIXED_TIME = 1_800_000_000


def _message(
    content: str,
    *,
    level: messages.MessageLevel = messages.MessageLevel.INFO,
    format: messages.MessageFormat = messages.MessageFormat.TEXT,
) -> messages.FlashMessage:
    """Build one representative immutable flash message."""
    return messages.FlashMessage(level=level, content=content, format=format)


def _sign_payload(
    key: str,
    compressed: bytes,
    *,
    version: str = "v1",
) -> str:
    """Build a correctly signed value for malformed-payload tests."""
    payload = base64.urlsafe_b64encode(compressed).rstrip(b"=").decode("ascii")
    signed = f"{version}.{payload}"
    signature = hmac.new(
        key.encode("ascii"),
        signed.encode("ascii"),
        hashlib.sha256,
    ).digest()
    encoded_signature = (
        base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    )
    return f"{signed}.{encoded_signature}"


def _incompressible_text(length: int, *, seed: str) -> str:
    """Create stable high-entropy text without relying on random state."""
    chunks: list[str] = []
    index = 0
    while sum(map(len, chunks)) < length:
        chunks.append(hashlib.sha256(f"{seed}:{index}".encode()).hexdigest())
        index += 1
    return "".join(chunks)[:length]


class FlashMessageModelTest(unittest.TestCase):
    """Keep the public model and request-local consumption semantics strict."""

    def test_models_use_str_enums_and_reject_untyped_values(self) -> None:
        self.assertEqual("success", messages.MessageLevel.SUCCESS)
        self.assertEqual("html", messages.MessageFormat.HTML)
        self.assertEqual(
            _message("saved", level=messages.MessageLevel.SUCCESS),
            messages.FlashMessage(
                level=messages.MessageLevel.SUCCESS,
                content="saved",
            ),
        )
        with self.assertRaisesRegex(TypeError, "level must be a MessageLevel"):
            messages.FlashMessage(level=cast(Any, "success"), content="saved")
        with self.assertRaisesRegex(TypeError, "format must be a MessageFormat"):
            messages.FlashMessage(
                level=messages.MessageLevel.SUCCESS,
                content="saved",
                format=cast(Any, "text"),
            )

    def test_dashboard_activity_action_uses_one_flat_transient_payload(self) -> None:
        action = messages.DashboardActivityAction(
            title="Saved",
            description="Alice was updated",
            tone="success",
            icon="ri-user-line",
            href="/users",
            time="Just now",
        )

        self.assertEqual(
            {
                "action": "dashboard_activity",
                "title": "Saved",
                "description": "Alice was updated",
                "tone": "success",
                "icon": "ri-user-line",
                "href": "/users",
                "time": "Just now",
            },
            action.to_dict(),
        )

    def test_truth_and_length_do_not_consume_but_iteration_consumes_a_snapshot(self) -> None:
        first = _message("first")
        second = _message("second")
        later = _message("later")
        storage = _FlashRequestStorage(loaded=(first, second), had_cookie=True)

        self.assertTrue(storage)
        self.assertEqual(2, len(storage))
        self.assertEqual((first, second), storage.pending)
        self.assertEqual([first, second], list(storage))
        self.assertEqual((), storage.pending)

        storage.add(later)

        self.assertEqual((later,), storage.pending)
        self.assertTrue(storage.has_unconsumed_additions)

    def test_helper_requires_middleware_owned_request_storage(self) -> None:
        request = cast(Request, SimpleNamespace(ctx=SimpleNamespace()))

        with self.assertRaisesRegex(
            RuntimeError,
            "Messages middleware has not initialized this request",
        ):
            messages.success(request, "saved")


class FlashCookieCodecTest(unittest.TestCase):
    """Verify authentication, expiry, serialization, and bounded capacity."""

    def codec(
        self,
        *,
        key: str = _CODEC_KEY,
        now: int = _FIXED_TIME,
        **kwargs: Any,
    ) -> _FlashCookieCodec:
        """Create a deterministic codec for protocol assertions."""
        return _FlashCookieCodec(key, clock=lambda: now, **kwargs)

    def test_all_levels_formats_and_translated_unicode_round_trip(self) -> None:
        original = (
            _message("保存成功", level=messages.MessageLevel.SUCCESS),
            _message("处理中", level=messages.MessageLevel.INFO),
            _message("部分记录被跳过", level=messages.MessageLevel.WARNING),
            _message(
                "<strong>保存失败</strong>",
                level=messages.MessageLevel.ERROR,
                format=messages.MessageFormat.HTML,
            ),
        )
        codec = self.codec()

        encoded = codec.encode_with_eviction(original)

        self.assertIsNotNone(encoded.value)
        self.assertEqual(0, encoded.dropped)
        self.assertEqual(original, codec.decode(cast(str, encoded.value)))

    def test_independent_instances_share_only_the_same_signing_key(self) -> None:
        value = cast(
            str,
            self.codec().encode_with_eviction((_message("shared"),)).value,
        )

        self.assertEqual((_message("shared"),), self.codec().decode(value))
        with self.assertRaisesRegex(_InvalidFlashCookie, "signature is invalid"):
            self.codec(key="a-different-signing-key").decode(value)

    def test_expired_and_implausibly_future_cookies_are_rejected(self) -> None:
        value = cast(
            str,
            self.codec().encode_with_eviction((_message("timed"),)).value,
        )

        with self.assertRaisesRegex(_InvalidFlashCookie, "expired"):
            self.codec(now=_FIXED_TIME + 3601).decode(value)
        future_value = cast(
            str,
            self.codec(now=_FIXED_TIME + 61)
            .encode_with_eviction((_message("future"),))
            .value,
        )
        with self.assertRaisesRegex(_InvalidFlashCookie, "in the future"):
            self.codec().decode(future_value)

    def test_tampering_unknown_versions_and_bad_encodings_are_rejected(self) -> None:
        value = cast(
            str,
            self.codec().encode_with_eviction((_message("safe"),)).value,
        )
        replacement = "A" if value[-1] != "A" else "B"

        with self.assertRaisesRegex(_InvalidFlashCookie, "signature is invalid"):
            self.codec().decode(f"{value[:-1]}{replacement}")
        with self.assertRaisesRegex(_InvalidFlashCookie, "version is unsupported"):
            self.codec().decode(value.replace("v1.", "v2.", 1))

        invalid_payload = "v1.!"
        signature = hmac.new(
            _CODEC_KEY.encode("ascii"),
            invalid_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        signed_invalid_payload = (
            f"{invalid_payload}."
            f"{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"
        )
        with self.assertRaisesRegex(_InvalidFlashCookie, "payload encoding"):
            self.codec().decode(signed_invalid_payload)

        bad_signature_encoding = value.rsplit(".", 1)[0] + ".!"
        with self.assertRaisesRegex(_InvalidFlashCookie, "signature encoding"):
            self.codec().decode(bad_signature_encoding)
        with self.assertRaisesRegex(_InvalidFlashCookie, "compression is invalid"):
            self.codec().decode(_sign_payload(_CODEC_KEY, b"not-zlib"))

    def test_invalid_messagepack_enums_and_empty_envelopes_are_rejected(self) -> None:
        malformed_values = (
            msgspec.msgpack.encode(b"not-an-envelope"),
            msgspec.msgpack.encode(
                {
                    "issued_at": _FIXED_TIME,
                    "messages": [
                        {
                            "level": "debug",
                            "content": "unsupported",
                            "format": "text",
                        }
                    ],
                }
            ),
            msgspec.msgpack.encode(
                {"issued_at": _FIXED_TIME, "messages": []}
            ),
        )

        for payload in malformed_values:
            value = _sign_payload(_CODEC_KEY, zlib.compress(payload))
            with self.subTest(payload=payload), self.assertRaises(
                _InvalidFlashCookie
            ):
                self.codec().decode(value)

    def test_decompression_output_is_bounded(self) -> None:
        generous = self.codec(decompressed_limit=4096)
        value = cast(
            str,
            generous.encode_with_eviction((_message("x" * 1500),)).value,
        )

        with self.assertRaisesRegex(_InvalidFlashCookie, "decompressed limit"):
            self.codec(decompressed_limit=128).decode(value)

    def test_encoded_limit_is_inclusive(self) -> None:
        message = _message(_incompressible_text(320, seed="boundary"))
        generous = self.codec(value_limit=4096)
        value = cast(str, generous.encode_with_eviction((message,)).value)
        exact_size = len(value.encode("ascii"))

        self.assertEqual(
            value,
            self.codec(value_limit=exact_size)
            .encode_with_eviction((message,))
            .value,
        )
        rejected = self.codec(value_limit=exact_size - 1).encode_with_eviction(
            (message,)
        )
        self.assertIsNone(rejected.value)
        self.assertEqual(1, rejected.dropped)

    def test_actual_capacity_drops_oldest_and_rejects_one_oversized_message(self) -> None:
        original = tuple(
            _message(_incompressible_text(720, seed=f"message-{index}"))
            for index in range(5)
        )
        codec = self.codec()

        encoded = codec.encode_with_eviction(original)

        self.assertIsNotNone(encoded.value)
        self.assertGreater(encoded.dropped, 0)
        self.assertEqual(original[encoded.dropped :], encoded.messages)
        self.assertLessEqual(
            len(cast(str, encoded.value).encode("ascii")),
            FLASH_COOKIE_VALUE_LIMIT,
        )
        self.assertEqual(
            encoded.messages,
            codec.decode(cast(str, encoded.value)),
        )

        oversized = self.codec().encode_with_eviction(
            (_message(_incompressible_text(5000, seed="oversized")),)
        )
        self.assertIsNone(oversized.value)
        self.assertEqual(1, oversized.dropped)
        self.assertEqual((), oversized.messages)


class FlashSanicLifecycleTest(unittest.IsolatedAsyncioTestCase):
    """Exercise middleware, Cookie policy, and Jinja proxy through real HTTP."""

    def setUp(self) -> None:
        self.settings = DefaultSettings.model_validate(
            {
                "web": {
                    "security": {"secret_key": _ROOT_SECRET},
                    "session": {
                        "enabled": False,
                        "cookie_domain": "example.test",
                        "cookie_httponly": True,
                        "cookie_secure": True,
                        "cookie_samesite": "Strict",
                    },
                }
            }
        )
        self.app = Sanic(
            f"oldman-web-messages-{time.time_ns()}",
            configure_logging=False,
        )
        Extend(
            self.app,
            config=Config(
                LOGGING=False,
                OAS=False,
                OAS_AUTODOC=False,
                TEMPLATING_ENABLE_ASYNC=True,
            ),
            extensions=[TemplatingExtension],
            built_in_extensions=False,
        )
        with patch.dict(
            conf.__dict__,
            {"settings": self.settings},
        ):
            messages.init_app(self.app)
        self._register_routes()

    def tearDown(self) -> None:
        Sanic.unregister_app(self.app)

    def _register_routes(self) -> None:
        @self.app.get("/add")
        async def add(request: Request) -> BaseHTTPResponse:
            messages.success(request, "Saved <script>alert(1)</script>")
            messages.info(request, "Import running")
            messages.warning(request, "Some records were skipped")
            messages.add_message(
                request,
                messages.MessageLevel.ERROR,
                "<strong>Save failed</strong>",
                format=messages.MessageFormat.HTML,
            )
            return redirect("/render", status=303)

        @self.app.get("/add-one")
        async def add_one(request: Request) -> BaseHTTPResponse:
            messages.success(request, "New message")
            return text("added")

        @self.app.get("/render")
        async def render(_request: Request) -> BaseHTTPResponse:
            template = self.app.ext.environment.from_string(
                "{% for message in messages %}"
                "{{ message.level }}:"
                "{% if message.format == 'html' %}"
                "{{ message.content | safe }}"
                "{% else %}{{ message.content }}{% endif %}|"
                "{% endfor %}"
            )
            return html(await template.render_async())

        @self.app.get("/peek")
        async def peek(_request: Request) -> BaseHTTPResponse:
            template = self.app.ext.environment.from_string(
                "{% if messages %}{{ messages | length }}{% else %}0{% endif %}"
            )
            return text(await template.render_async())

        @self.app.get("/consume-then-add")
        async def consume_then_add(request: Request) -> BaseHTTPResponse:
            template = self.app.ext.environment.from_string(
                "{% for message in messages %}{{ message.content }}|{% endfor %}"
            )
            rendered = await template.render_async()
            messages.info(request, "Added after rendering")
            return text(rendered)

        @self.app.get("/noop")
        async def noop(_request: Request) -> BaseHTTPResponse:
            return text("ok")

    @staticmethod
    def _set_cookie_header(response: BaseHTTPResponse) -> str | None:
        """Return the single flash Set-Cookie header if one exists."""
        return response.headers.get("set-cookie")

    @classmethod
    def _cookie_value(cls, response: BaseHTTPResponse) -> str:
        """Extract the flash value from one response header."""
        header = cls._set_cookie_header(response)
        if header is None:
            raise AssertionError("response did not set a Cookie")
        parsed = SimpleCookie()
        parsed.load(header)
        return parsed[FLASH_COOKIE_NAME].value

    @staticmethod
    def _request_headers(value: str) -> dict[str, str]:
        """Build an explicit request Cookie without client persistence."""
        return {"cookie": f"{FLASH_COOKIE_NAME}={value}"}

    async def test_anonymous_session_disabled_flow_renders_all_and_consumes_once(self) -> None:
        _request, added = await self.app.asgi_client.get("/add")

        self.assertEqual(303, added.status)
        cookie_value = self._cookie_value(added)
        _request, rendered = await self.app.asgi_client.get(
            "/render",
            headers=self._request_headers(cookie_value),
        )

        self.assertEqual(
            "success:Saved &lt;script&gt;alert(1)&lt;/script&gt;|"
            "info:Import running|"
            "warning:Some records were skipped|"
            "error:<strong>Save failed</strong>|",
            rendered.text,
        )
        deleted = self._set_cookie_header(rendered)
        self.assertIsNotNone(deleted)
        self.assertIn("Max-Age=0", cast(str, deleted))

        _request, refreshed = await self.app.asgi_client.get("/render")
        self.assertEqual("", refreshed.text)
        self.assertIsNone(self._set_cookie_header(refreshed))

    async def test_cookie_attributes_follow_session_policy(self) -> None:
        _request, response = await self.app.asgi_client.get("/add-one")
        parsed = SimpleCookie()
        parsed.load(cast(str, self._set_cookie_header(response)))
        cookie = parsed[FLASH_COOKIE_NAME]

        self.assertEqual("/", cookie["path"])
        self.assertEqual("example.test", cookie["domain"])
        self.assertEqual("3600", cookie["max-age"])
        self.assertTrue(cookie["httponly"])
        self.assertTrue(cookie["secure"])
        self.assertEqual("Strict", cookie["samesite"])

    async def test_truth_and_length_do_not_consume_or_renew(self) -> None:
        _request, added = await self.app.asgi_client.get("/add-one")
        cookie_value = self._cookie_value(added)

        _request, peeked = await self.app.asgi_client.get(
            "/peek",
            headers=self._request_headers(cookie_value),
        )

        self.assertEqual("1", peeked.text)
        self.assertIsNone(self._set_cookie_header(peeked))

        _request, rendered = await self.app.asgi_client.get(
            "/render",
            headers=self._request_headers(cookie_value),
        )
        self.assertEqual("success:New message|", rendered.text)

    async def test_consumption_followed_by_addition_keeps_only_later_message(self) -> None:
        _request, added = await self.app.asgi_client.get("/add-one")
        cookie_value = self._cookie_value(added)

        _request, consumed = await self.app.asgi_client.get(
            "/consume-then-add",
            headers=self._request_headers(cookie_value),
        )

        self.assertEqual("New message|", consumed.text)
        replacement = self._cookie_value(consumed)
        _request, rendered = await self.app.asgi_client.get(
            "/render",
            headers=self._request_headers(replacement),
        )
        self.assertEqual("info:Added after rendering|", rendered.text)

    async def test_invalid_cookie_is_deleted_or_replaced_by_new_messages(self) -> None:
        invalid_headers = self._request_headers("v1.invalid.invalid")

        _request, deleted = await self.app.asgi_client.get(
            "/noop",
            headers=invalid_headers,
        )
        self.assertIn(
            "Max-Age=0",
            cast(str, self._set_cookie_header(deleted)),
        )

        _request, replaced = await self.app.asgi_client.get(
            "/add-one",
            headers=invalid_headers,
        )
        replacement = self._cookie_value(replaced)
        _request, rendered = await self.app.asgi_client.get(
            "/render",
            headers=self._request_headers(replacement),
        )
        self.assertEqual("success:New message|", rendered.text)

    async def test_empty_request_writes_no_cookie(self) -> None:
        _request, response = await self.app.asgi_client.get("/noop")

        self.assertIsNone(self._set_cookie_header(response))

    def test_duplicate_initialization_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "already initialized"):
            messages.init_app(self.app)

    def test_missing_jinja_environment_is_rejected(self) -> None:
        app = Sanic(
            f"oldman-web-messages-no-jinja-{time.time_ns()}",
            configure_logging=False,
        )
        try:
            Extend(
                app,
                config=Config(LOGGING=False),
                extensions=[],
                built_in_extensions=False,
            )
            with patch.dict(
                conf.__dict__,
                {"settings": self.settings},
            ), self.assertRaisesRegex(RuntimeError, "Jinja environment"):
                messages.init_app(app)
        finally:
            Sanic.unregister_app(app)


if __name__ == "__main__":
    unittest.main()
