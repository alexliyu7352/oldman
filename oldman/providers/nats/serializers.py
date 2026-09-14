"""
自定义 NATS 序列化器 — 纯 msgspec 链路，消除 stdlib json 中间层

消息类型约束为 MsgspecModel（msgspec.Struct 子类），直接使用其内置
encoder/decoder，无需外部编解码器或中间转换。

两种模式:
  - MsgspecJsonNatsSerializer + msgspec_json_decoder
      wire format: JSON bytes，可与约定了相同消息结构的 JSON 客户端互通
  - MsgpackNatsSerializer + msgpack_decoder
      wire format: MessagePack bytes，双方须使用相同编码与消息结构

用法（在 NATSConnection 中选择一种）:
    from oldman.providers.nats.serializers import MsgpackNatsSerializer, msgpack_decoder
    broker = NatsBroker(..., serializer=MsgpackNatsSerializer(), decoder=msgpack_decoder)
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import msgspec
import msgspec.structs
from fast_depends.exceptions import ValidationError
from fast_depends.library.serializer import OptionItem, Serializer, SerializerProto

from oldman.serializers.base import MsgspecModel

if TYPE_CHECKING:
    from faststream.message import StreamMessage


# ─────────────────────────────────────────────────────────────────────────────
# 共用 DI Serializer — dict → handler 类型参数注入
# ─────────────────────────────────────────────────────────────────────────────

class _StructDISerializer(Serializer):
    """
    基于 msgspec.convert() 的 DI 参数注入序列化器。

    接收 call_kwargs: dict（由 broker decoder 解出），通过 msgspec.defstruct
    动态构造对应函数签名的 Struct，然后将字段值注入 handler 参数。

    约束：所有 handler 消息参数类型须为 MsgspecModel 子类（msgspec.Struct），
    msgspec 原生支持，无需 dec_hook。
    """

    __slots__ = ("aliases", "model", "response_type")

    def __init__(
        self,
        *,
        name: str,
        options: list[OptionItem],
        response_type: Any,
    ) -> None:
        model_fields: list[str | tuple[str, type] | tuple[str, type, Any]] = []
        aliases: dict[str, str] = {}

        for item in options:
            default = item.default_value

            # msgspec.structs.FieldInfo 出现于参数用 msgspec.field(name=...) 指定别名时
            if isinstance(default, msgspec.structs.FieldInfo) and default.name:
                aliases[item.field_name] = default.name
            else:
                aliases[item.field_name] = item.field_name

            if default is Ellipsis:
                model_fields.append((item.field_name, item.field_type))
            else:
                model_fields.append((item.field_name, item.field_type, default))

        self.aliases = aliases
        self.model = msgspec.defstruct(name, model_fields, kw_only=True)
        self.response_type: Any = response_type  # 基类不存此属性，手动存储
        super().__init__(name=name, options=options, response_type=response_type)

    def get_aliases(self) -> tuple[str, ...]:
        return tuple(self.aliases.values())

    def __call__(self, call_kwargs: dict[str, Any]) -> dict[str, Any]:
        with self._wrap_validation_error(call_kwargs):
            casted = msgspec.convert(
                call_kwargs,
                type=self.model,
                strict=False,
                str_keys=True,
            )
        return {field: getattr(casted, field, None) for field in self.aliases}

    def response(self, value: Any) -> Any:
        rt = self.response_type
        if rt is not None and rt is not inspect.Parameter.empty:
            return msgspec.convert(value, type=rt, strict=False)
        return value

    @contextmanager
    def _wrap_validation_error(self, call_kwargs: Any) -> Iterator[None]:
        try:
            yield
        except msgspec.ValidationError as exc:
            raise ValidationError(
                incoming_options=call_kwargs,
                expected=self.options,
                locations=(),
                original_error=exc,
            ) from exc


# ─────────────────────────────────────────────────────────────────────────────
# 模式一：JSON（msgspec.json，替代 stdlib json，兼容性最好）
# ─────────────────────────────────────────────────────────────────────────────

class MsgspecJsonNatsSerializer(SerializerProto):
    """
    用 MsgspecModel 内置 JSON 编码器完成序列化，消除 stdlib json 中间层。

    encode: message.to_json_bytes()   — MsgspecModel 内置 JSON bytes 编码
    decode: msgspec_json_decoder 负责  bytes → dict（broker 层）
            _StructDISerializer 负责   dict  → 类型参数（DI 层）

    wire format: JSON UTF-8 bytes；其他语言客户端须约定相同字段和数据类型。
    """

    def __call__(self, *, name: str, options: list[OptionItem], response_type: Any) -> _StructDISerializer:
        return _StructDISerializer(name=name, options=options, response_type=response_type)

    @staticmethod
    def encode(message: MsgspecModel | bytes) -> bytes:
        if isinstance(message, bytes):
            return message
        return message.to_json_bytes()


async def msgspec_json_decoder(msg: StreamMessage[Any]) -> Any:
    """
    替换 FastStream 默认的 decode_message（stdlib json.loads）。
    使用 msgspec.json.decode 将 msg.body bytes → dict/value。

    传给 NatsBroker(decoder=msgspec_json_decoder)
    """
    body: bytes = msg.body  # type: ignore[attr-defined]
    if not body:
        return None
    try:
        return msgspec.json.decode(body)
    except msgspec.DecodeError:
        # 非 JSON 消息降级返回原始 bytes，与原 decode_message 行为一致
        return body


# ─────────────────────────────────────────────────────────────────────────────
# 模式二：Msgpack（纯二进制，Python-to-Python 内部服务最优选）
# ─────────────────────────────────────────────────────────────────────────────

class MsgpackNatsSerializer(SerializerProto):
    """
    用 MsgspecModel 内置 Msgpack 编码器完成序列化，全链路二进制，零 JSON 开销。

    encode: message.to_msgpack()     — MsgspecModel 内置 msgpack 编码
    decode: msgpack_decoder 负责      bytes → dict（broker 层）
            _StructDISerializer 负责  dict  → 类型参数（DI 层）

    wire format: MessagePack bytes，非 JSON；并不限定 Python 客户端。
    双方必须约定相同字段、数据类型及 MessagePack 扩展类型；不承诺固定性能倍数。
    """

    def __call__(self, *, name: str, options: list[OptionItem], response_type: Any) -> _StructDISerializer:
        return _StructDISerializer(name=name, options=options, response_type=response_type)

    @staticmethod
    def encode(message: MsgspecModel | bytes) -> bytes:
        if isinstance(message, bytes):
            return message
        return message.to_msgpack()


async def msgpack_decoder(msg: StreamMessage[Any]) -> Any:
    """
    替换 FastStream 默认的 decode_message，使用 msgspec.msgpack 解码。
    传给 NatsBroker(decoder=msgpack_decoder)

    注意：发布方须使用 MsgpackNatsSerializer 编码，否则解码失败。
    """
    body: bytes = msg.body  # type: ignore[attr-defined]
    if not body:
        return None
    try:
        return msgspec.msgpack.decode(body)
    except msgspec.DecodeError:
        return body
