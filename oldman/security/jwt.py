"""Encode and verify HMAC-signed JSON Web Tokens (HS256, HS384, HS512).

This is the codec only. It checks what a token says about itself — signature, algorithm,
`exp`, `nbf`, and `aud` / `iss` when the caller names what it expects — and nothing about
whom it was issued to. A token without `exp` never expires here; an authentication layer
that issues tokens must require `exp` itself.
"""

import base64
import hashlib
import hmac
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn

import orjson


class JWTError(ValueError):
    """Base error for JWT encode/decode failures."""


class InvalidTokenError(JWTError):
    """Raised when a token is malformed or its signature is invalid."""


class ExpiredTokenError(InvalidTokenError):
    """Raised when a token has expired."""


_HMAC_ALGORITHMS = {
    "HS256": hashlib.sha256,
    "HS384": hashlib.sha384,
    "HS512": hashlib.sha512,
}


def jwt_encode(
    payload: Mapping[str, Any],
    secret_key: str | bytes,
    *,
    algorithm: str = "HS256",
    headers: Mapping[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Encode a JSON Web Token signed with an HMAC SHA algorithm."""
    if algorithm not in _HMAC_ALGORITHMS:
        raise ValueError(f"Unsupported JWT algorithm: {algorithm}")

    token_header: dict[str, Any] = {"alg": algorithm, "typ": "JWT"}
    if headers:
        token_header.update(headers)
        token_header["alg"] = algorithm

    token_payload = dict(payload)
    if expires_delta is not None:
        token_payload["exp"] = datetime.now(UTC) + expires_delta

    signing_input = ".".join(
        (
            _b64encode_json(token_header),
            _b64encode_json(token_payload),
        )
    )
    signature = _sign(signing_input.encode("ascii"), secret_key, algorithm)
    return f"{signing_input}.{_b64encode(signature)}"


def jwt_decode(
    token: str,
    secret_key: str | bytes,
    *,
    algorithms: Sequence[str] | None = None,
    verify_exp: bool = True,
    leeway: int | float | timedelta = 0,
    audience: str | None = None,
    issuer: str | None = None,
) -> dict[str, Any]:
    """Decode and verify a JSON Web Token signed by :func:`jwt_encode`.

    `nbf` is always checked when present. `audience` and `issuer` name what this caller
    expects. A token that carries `aud` is refused when no audience is expected, because a
    service that does not say who it is would otherwise accept tokens meant for another.
    """
    header_segment, payload_segment, signature_segment = _split_token(token)
    header = _decode_json_segment(header_segment)
    payload = _decode_json_segment(payload_segment)

    algorithm = header.get("alg")
    allowed_algorithms = tuple(algorithms or ("HS256",))
    if not isinstance(algorithm, str) or algorithm not in allowed_algorithms or algorithm not in _HMAC_ALGORITHMS:
        raise InvalidTokenError("Invalid JWT algorithm")

    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    expected_signature = _sign(signing_input, secret_key, algorithm)
    actual_signature = _b64decode(signature_segment)
    if not hmac.compare_digest(actual_signature, expected_signature):
        raise InvalidTokenError("Invalid JWT signature")

    leeway_seconds = leeway.total_seconds() if isinstance(leeway, timedelta) else float(leeway)
    now = datetime.now(UTC).timestamp()
    if verify_exp:
        _verify_exp(payload, now, leeway_seconds)
    _verify_nbf(payload, now, leeway_seconds)
    _verify_audience(payload, audience)
    _verify_issuer(payload, issuer)

    return payload


def _split_token(token: str) -> tuple[str, str, str]:
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        raise InvalidTokenError("Malformed JWT")
    return parts[0], parts[1], parts[2]


def _b64encode_json(value: Mapping[str, Any]) -> str:
    # OPT_PASSTHROUGH_DATETIME 不能少：orjson 原生把 datetime 写成 ISO 字符串，而 JWT 的
    # exp/iat 必须是数字。没有它，_json_default 根本不会被调用，claims 会变成不合规的形状。
    data = orjson.dumps(value, default=_json_default, option=orjson.OPT_SORT_KEYS | orjson.OPT_PASSTHROUGH_DATETIME)
    return _b64encode(data)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(f"{data}{padding}".encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise InvalidTokenError("Invalid JWT segment encoding") from exc


def _decode_json_segment(segment: str) -> dict[str, Any]:
    try:
        value = orjson.loads(_b64decode(segment))
    except (UnicodeDecodeError, orjson.JSONDecodeError) as exc:
        raise InvalidTokenError("Invalid JWT JSON") from exc
    if not isinstance(value, dict):
        raise InvalidTokenError("Invalid JWT JSON object")
    return value


def _sign(data: bytes, secret_key: str | bytes, algorithm: str) -> bytes:
    key = secret_key.encode("utf-8") if isinstance(secret_key, str) else secret_key
    if not key:
        raise ValueError("secret_key cannot be empty")
    return hmac.new(key, data, _HMAC_ALGORITHMS[algorithm]).digest()


def _json_default(value: Any) -> int | NoReturn:
    if isinstance(value, datetime):
        return int(value.timestamp())
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _numeric_date(payload: Mapping[str, Any], claim: str) -> float | None:
    """Read one NumericDate claim; a bool is not a number here, whatever Python says."""
    value = payload.get(claim)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidTokenError(f"Invalid JWT {claim} claim")
    return float(value)


def _verify_exp(payload: Mapping[str, Any], now: float, leeway: float) -> None:
    exp = _numeric_date(payload, "exp")
    if exp is not None and now > exp + leeway:
        raise ExpiredTokenError("JWT has expired")


def _verify_nbf(payload: Mapping[str, Any], now: float, leeway: float) -> None:
    nbf = _numeric_date(payload, "nbf")
    if nbf is not None and now + leeway < nbf:
        raise InvalidTokenError("JWT is not valid yet")


def _verify_audience(payload: Mapping[str, Any], audience: str | None) -> None:
    claimed = payload.get("aud")
    if audience is None:
        if claimed is not None:
            raise InvalidTokenError("JWT names an audience but none is expected")
        return
    if isinstance(claimed, str):
        accepted = claimed == audience
    elif isinstance(claimed, list):
        accepted = audience in claimed
    else:
        accepted = False
    if not accepted:
        raise InvalidTokenError("JWT audience does not match")


def _verify_issuer(payload: Mapping[str, Any], issuer: str | None) -> None:
    if issuer is not None and payload.get("iss") != issuer:
        raise InvalidTokenError("JWT issuer does not match")


__all__ = [
    "ExpiredTokenError",
    "InvalidTokenError",
    "JWTError",
    "jwt_decode",
    "jwt_encode",
]
