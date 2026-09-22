"""Select/Autocomplete 签名绑定上下文。"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import asdict, dataclass
from typing import Literal

import orjson


class SelectBindError(ValueError):
    """远程选择器绑定签名无效。"""


@dataclass(frozen=True)
class SelectContext:
    """远程选择器签名绑定上下文。"""

    provider: str
    field_name: str
    multiple: bool
    dependent_fields: tuple[str, ...]
    page_size: int
    value_field: str
    label_mode: Literal["text", "html"]


def sign_select_context(context: SelectContext, *, secret_key: str) -> str:
    """签名远程选择器上下文并返回前端 bind 值。"""
    payload = _encode_json(_context_payload(context))
    signature = _signature(payload, secret_key=secret_key)
    return f"{payload}.{signature}"


def verify_select_context(bind: str, *, secret_key: str) -> SelectContext:
    """验证 bind 签名并恢复 SelectContext。"""
    try:
        payload, signature = bind.rsplit(".", 1)
    except ValueError as exc:
        raise SelectBindError("Invalid select bind format") from exc

    expected = _signature(payload, secret_key=secret_key)
    if not hmac.compare_digest(signature, expected):
        raise SelectBindError("Invalid select bind signature")

    try:
        data = orjson.loads(_decode_base64(payload))
        data["dependent_fields"] = tuple(data.get("dependent_fields") or ())
        context = SelectContext(**data)
        if context.label_mode not in {"text", "html"}:
            raise ValueError("Invalid select label mode")
        return context
    except (TypeError, ValueError, orjson.JSONDecodeError) as exc:
        raise SelectBindError("Invalid select bind payload") from exc


def _context_payload(context: SelectContext) -> dict[str, object]:
    """转换上下文为稳定 JSON payload。"""
    payload = asdict(context)
    payload["dependent_fields"] = list(context.dependent_fields)
    return payload


def _encode_json(payload: dict[str, object]) -> str:
    """以稳定格式编码 JSON 并做 URL-safe base64。"""
    raw = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_base64(value: str) -> str:
    """解码 URL-safe base64 字符串。"""
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}").decode()


def _signature(payload: str, *, secret_key: str) -> str:
    """返回 payload 的 HMAC-SHA256 签名。"""
    digest = hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")
