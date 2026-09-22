"""Signed Cookie codec and Sanic lifecycle for one-time Web messages."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass

import msgspec
from sanic import Request, Sanic
from sanic.cookies.response import SameSite
from sanic.middleware import MiddlewareLocation
from sanic.response import BaseHTTPResponse

from oldman.logging import get_logger
from oldman.serializers import MsgspecModel
from oldman.web.messages._template import messages_proxy
from oldman.web.messages.flash import (
    FlashMessage,
    _FlashRequestStorage,
    _get_request_storage,
    _set_request_storage,
)
from oldman.web.security.keys import (
    WebSecurityPurpose,
    configured_web_security_key,
)

FLASH_COOKIE_NAME = "oldman_messages"
FLASH_COOKIE_MAX_AGE = 3600
FLASH_COOKIE_VALUE_LIMIT = 2048
_FLASH_DECOMPRESSED_LIMIT = 64 * 1024
_FLASH_FUTURE_TOLERANCE = 60
_FLASH_VERSION = "v1"
_APP_RUNTIME_ATTRIBUTE = "_oldman_flash_messages_runtime"


class _FlashEnvelope(
    MsgspecModel,
    kw_only=True,
    frozen=True,  # pyright: ignore[reportGeneralTypeIssues] -- msgspec freezes the generated Struct
):
    """Versioned payload authenticated as one indivisible Cookie value."""

    issued_at: int
    messages: tuple[FlashMessage, ...]


class _InvalidFlashCookie(ValueError):
    """Describe a safe-to-log Cookie validation failure."""


class _FlashCookieTooLarge(ValueError):
    """Report encoded and decoded sizes without exposing message contents."""

    def __init__(self, encoded_size: int, decoded_size: int) -> None:
        super().__init__("flash Cookie payload exceeds its configured limit")
        self.encoded_size = encoded_size
        self.decoded_size = decoded_size


@dataclass(frozen=True, slots=True)
class _EncodedMessages:
    """Result of evicting oldest messages until one Cookie value fits."""

    messages: tuple[FlashMessage, ...]
    value: str | None
    dropped: int
    original_encoded_size: int


class _FlashCookieCodec:
    """Encode, authenticate, bound, and validate the flash Cookie protocol."""

    def __init__(
        self,
        signing_key: str,
        *,
        max_age: int = FLASH_COOKIE_MAX_AGE,
        value_limit: int = FLASH_COOKIE_VALUE_LIMIT,
        decompressed_limit: int = _FLASH_DECOMPRESSED_LIMIT,
        future_tolerance: int = _FLASH_FUTURE_TOLERANCE,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not isinstance(signing_key, str) or not signing_key:
            raise ValueError("signing_key must be a non-empty string")
        for name, value in (
            ("max_age", max_age),
            ("value_limit", value_limit),
            ("decompressed_limit", decompressed_limit),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if type(future_tolerance) is not int or future_tolerance < 0:
            raise ValueError("future_tolerance must be a non-negative integer")
        if not callable(clock):
            raise TypeError("clock must be callable")

        self._signing_key = signing_key.encode("ascii")
        self.max_age = max_age
        self.value_limit = value_limit
        self.decompressed_limit = decompressed_limit
        self.future_tolerance = future_tolerance
        self._clock = clock

    def decode(self, value: str) -> tuple[FlashMessage, ...]:
        """Return authenticated unexpired messages or raise a safe error."""
        if not isinstance(value, str):
            raise _InvalidFlashCookie("Cookie value is not text")
        try:
            encoded_size = len(value.encode("ascii"))
        except UnicodeEncodeError:
            raise _InvalidFlashCookie("Cookie value is not ASCII") from None
        if encoded_size > self.value_limit:
            raise _InvalidFlashCookie("Cookie value exceeds the encoded limit")

        parts = value.split(".")
        if len(parts) != 3 or parts[0] != _FLASH_VERSION:
            raise _InvalidFlashCookie("Cookie version is unsupported")
        version, payload_text, signature_text = parts
        try:
            supplied_signature = _urlsafe_b64decode(signature_text)
        except (ValueError, binascii.Error):
            raise _InvalidFlashCookie("Cookie signature encoding is invalid") from None
        if len(supplied_signature) != hashlib.sha256().digest_size:
            raise _InvalidFlashCookie("Cookie signature length is invalid")

        signed_value = f"{version}.{payload_text}".encode("ascii")
        expected_signature = hmac.new(
            self._signing_key,
            signed_value,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise _InvalidFlashCookie("Cookie signature is invalid")

        try:
            compressed = _urlsafe_b64decode(payload_text)
        except (ValueError, binascii.Error):
            raise _InvalidFlashCookie("Cookie payload encoding is invalid") from None
        payload = self._decompress(compressed)
        try:
            envelope = _FlashEnvelope.from_msgpack(payload)
        except (msgspec.DecodeError, msgspec.ValidationError):
            raise _InvalidFlashCookie("Cookie payload is invalid") from None

        now = int(self._clock())
        if envelope.issued_at <= 0:
            raise _InvalidFlashCookie("Cookie issue time is invalid")
        if envelope.issued_at > now + self.future_tolerance:
            raise _InvalidFlashCookie("Cookie issue time is in the future")
        if now - envelope.issued_at > self.max_age:
            raise _InvalidFlashCookie("Cookie has expired")
        if not envelope.messages:
            raise _InvalidFlashCookie("Cookie contains no messages")
        return envelope.messages

    def encode_with_eviction(
        self,
        messages: tuple[FlashMessage, ...],
    ) -> _EncodedMessages:
        """Drop oldest complete messages until the newest suffix fits."""
        if not messages:
            return _EncodedMessages((), None, 0, 0)

        original_size = 0
        for dropped in range(len(messages)):
            retained = messages[dropped:]
            try:
                value = self._encode(retained)
            except _FlashCookieTooLarge as exc:
                if dropped == 0:
                    original_size = exc.encoded_size
                continue
            encoded_size = len(value.encode("ascii"))
            if dropped == 0:
                original_size = encoded_size
            return _EncodedMessages(
                retained,
                value,
                dropped,
                original_size,
            )
        return _EncodedMessages(
            (),
            None,
            len(messages),
            original_size,
        )

    def _encode(self, messages: tuple[FlashMessage, ...]) -> str:
        """Encode one non-empty message tuple without applying eviction."""
        envelope = _FlashEnvelope(
            issued_at=int(self._clock()),
            messages=messages,
        )
        payload = envelope.to_msgpack()
        compressed = zlib.compress(payload, level=9)
        payload_text = _urlsafe_b64encode(compressed)
        signed_value = f"{_FLASH_VERSION}.{payload_text}"
        signature = hmac.new(
            self._signing_key,
            signed_value.encode("ascii"),
            hashlib.sha256,
        ).digest()
        value = f"{signed_value}.{_urlsafe_b64encode(signature)}"
        encoded_size = len(value.encode("ascii"))
        if len(payload) > self.decompressed_limit or encoded_size > self.value_limit:
            raise _FlashCookieTooLarge(encoded_size, len(payload))
        return value

    def _decompress(self, compressed: bytes) -> bytes:
        """Inflate a payload without allowing output beyond the fixed bound."""
        decompressor = zlib.decompressobj()
        try:
            payload = decompressor.decompress(
                compressed,
                self.decompressed_limit + 1,
            )
            if len(payload) > self.decompressed_limit or decompressor.unconsumed_tail:
                raise _InvalidFlashCookie("Cookie payload exceeds the decompressed limit")
            payload += decompressor.flush(self.decompressed_limit + 1 - len(payload))
        except zlib.error:
            raise _InvalidFlashCookie("Cookie compression is invalid") from None
        if len(payload) > self.decompressed_limit:
            raise _InvalidFlashCookie("Cookie payload exceeds the decompressed limit")
        if not decompressor.eof or decompressor.unused_data:
            raise _InvalidFlashCookie("Cookie compression is invalid")
        return payload


@dataclass(frozen=True, slots=True)
class _FlashCookiePolicy:
    """Cookie attributes shared with the configured Web Session policy."""

    domain: str | None
    httponly: bool
    secure: bool
    samesite: SameSite | None


class _CookieFlashRuntime:
    """Open and persist one request-local flash storage per Sanic request."""

    def __init__(
        self,
        codec: _FlashCookieCodec,
        policy: _FlashCookiePolicy,
    ) -> None:
        self.codec = codec
        self.policy = policy
        self._logger = get_logger("default.web.messages")

    def open_request(self, request: Request) -> None:
        """Authenticate the incoming Cookie and attach isolated request state."""
        raw_cookie = request.cookies.get(FLASH_COOKIE_NAME)
        if not raw_cookie:
            _set_request_storage(request, _FlashRequestStorage())
            return

        try:
            loaded = self.codec.decode(str(raw_cookie))
        except _InvalidFlashCookie as exc:
            self._logger.warning("Ignoring invalid flash Cookie: %s", exc)
            storage = _FlashRequestStorage(
                had_cookie=True,
                invalid_cookie=True,
            )
        else:
            storage = _FlashRequestStorage(
                loaded=loaded,
                had_cookie=True,
            )
        _set_request_storage(request, storage)

    def save_response(
        self,
        request: Request,
        response: BaseHTTPResponse,
    ) -> None:
        """Apply consumption, renewal, deletion, and capacity semantics."""
        storage = _get_request_storage(request)
        pending = storage.pending

        if not pending:
            if storage.had_cookie:
                self._delete_cookie(response)
            return

        if not storage.invalid_cookie and not storage.has_unconsumed_additions:
            # Untouched valid messages retain the browser's existing expiry.
            return

        encoded = self.codec.encode_with_eviction(pending)
        if encoded.dropped:
            self._logger.warning(
                "Dropped %d flash message(s) to fit the Cookie limit; encoded bytes before eviction: %d",
                encoded.dropped,
                encoded.original_encoded_size,
            )
        if encoded.value is None:
            if storage.had_cookie:
                self._delete_cookie(response)
            return

        response.add_cookie(
            FLASH_COOKIE_NAME,
            encoded.value,
            path="/",
            domain=self.policy.domain,
            secure=self.policy.secure,
            max_age=self.codec.max_age,
            httponly=self.policy.httponly,
            samesite=self.policy.samesite,
        )

    def _delete_cookie(self, response: BaseHTTPResponse) -> None:
        """Remove the flash Cookie with the same path and domain as writes."""
        response.delete_cookie(
            FLASH_COOKIE_NAME,
            path="/",
            domain=self.policy.domain,
        )


def init_app(app: Sanic) -> None:
    """Install signed Cookie flash storage and its Jinja global on one app."""
    if not isinstance(app, Sanic):
        raise TypeError("app must be a Sanic application")
    if hasattr(app.ctx, _APP_RUNTIME_ATTRIBUTE):
        raise RuntimeError("Web messages are already initialized on this app")

    environment = getattr(getattr(app, "ext", None), "environment", None)
    if environment is None:
        raise RuntimeError("Web messages require the Sanic-Ext Jinja environment")

    import oldman.conf as conf

    session_config = conf.settings.web.session
    runtime = _CookieFlashRuntime(
        _FlashCookieCodec(configured_web_security_key(WebSecurityPurpose.FLASH)),
        _FlashCookiePolicy(
            domain=session_config.cookie_domain,
            httponly=session_config.cookie_httponly,
            secure=session_config.cookie_secure,
            samesite=session_config.cookie_samesite,
        ),
    )
    app.register_middleware(
        runtime.open_request,
        MiddlewareLocation.REQUEST.name,
    )
    app.register_middleware(
        runtime.save_response,
        MiddlewareLocation.RESPONSE.name,
    )
    environment.globals["messages"] = messages_proxy
    setattr(app.ctx, _APP_RUNTIME_ATTRIBUTE, runtime)


def _urlsafe_b64encode(value: bytes) -> str:
    """Encode compact URL-safe base64 without optional padding."""
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _urlsafe_b64decode(value: str) -> bytes:
    """Decode strict URL-safe base64 with restored padding."""
    if not value:
        raise ValueError("base64 value must not be empty")
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(
        value + padding,
        altchars=b"-_",
        validate=True,
    )


__all__ = ["init_app"]
