import base64
import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn


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
) -> dict[str, Any]:
    """Decode and verify a JSON Web Token signed by :func:`jwt_encode`."""
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

    if verify_exp:
        _verify_exp(payload, leeway)

    return payload


def _split_token(token: str) -> tuple[str, str, str]:
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        raise InvalidTokenError("Malformed JWT")
    return parts[0], parts[1], parts[2]


def _b64encode_json(value: Mapping[str, Any]) -> str:
    data = json.dumps(value, default=_json_default, separators=(",", ":"), sort_keys=True).encode("utf-8")
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
        value = json.loads(_b64decode(segment))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
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


def _verify_exp(payload: Mapping[str, Any], leeway: int | float | timedelta) -> None:
    exp = payload.get("exp")
    if exp is None:
        return
    if not isinstance(exp, int | float):
        raise InvalidTokenError("Invalid JWT exp claim")

    leeway_seconds = leeway.total_seconds() if isinstance(leeway, timedelta) else float(leeway)
    if datetime.now(UTC).timestamp() > exp + leeway_seconds:
        raise ExpiredTokenError("JWT has expired")


__all__ = [
    "ExpiredTokenError",
    "InvalidTokenError",
    "JWTError",
    "jwt_decode",
    "jwt_encode",
]
