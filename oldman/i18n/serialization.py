"""Binary-safe serialization for payloads containing lazy translations."""

from __future__ import annotations

import math
from typing import Any, ClassVar

import msgspec

from oldman.i18n.translations import (
    LazyTranslation,
    TranslationCatalog,
    bind_translations,
    reset_translations,
)
from oldman.serializers import MsgspecModel

_TranslationVariable = str | int | float | bool | None

# Oldman private MessagePack extension permanently reserved for LazyTranslation.
_LAZY_TRANSLATION_EXT_CODE = 1


class _LazyTranslationWire(msgspec.Struct, array_like=True):
    """Compact, versioned-by-extension representation of one lazy message."""

    singular: str
    plural: str | None
    n: int | None
    variables: dict[str, _TranslationVariable]


_WIRE_ENCODER = msgspec.msgpack.Encoder()
_WIRE_DECODER = msgspec.msgpack.Decoder(type=_LazyTranslationWire)


def _validate_wire(wire: _LazyTranslationWire) -> None:
    """Reject values that cannot be translated and emitted as strict JSON."""
    if not wire.singular:
        raise TypeError("LazyTranslation singular message must be a non-empty string")
    if (wire.plural is None) != (wire.n is None):
        raise TypeError("LazyTranslation plural message and count must be provided together")
    if wire.n is not None and type(wire.n) is not int:
        raise TypeError("LazyTranslation count must be an integer")

    for key, value in wire.variables.items():
        if type(key) is not str:
            raise TypeError("LazyTranslation variable keys must be strings")
        if type(value) not in {str, int, float, bool, type(None)}:
            raise TypeError(
                "LazyTranslation variable values must be JSON scalar values"
            )
        if type(value) is float and not math.isfinite(value):
            raise TypeError("LazyTranslation float variables must be finite")


def _wire_from_translation(value: LazyTranslation) -> _LazyTranslationWire:
    """Validate and copy mutable translation state into the wire struct."""
    if type(value.singular) is not str:
        raise TypeError("LazyTranslation singular message must be a string")
    if value.plural is not None and type(value.plural) is not str:
        raise TypeError("LazyTranslation plural message must be a string or None")
    if type(value.variables) is not dict:
        raise TypeError("LazyTranslation variables must be a dictionary")

    wire = _LazyTranslationWire(
        singular=value.singular,
        plural=value.plural,
        n=value.n,
        variables=dict(value.variables),
    )
    _validate_wire(wire)
    return wire


def _msgpack_enc_hook(value: Any) -> msgspec.msgpack.Ext:
    """Encode only LazyTranslation as the reserved private extension."""
    if not isinstance(value, LazyTranslation):
        raise NotImplementedError
    wire = _wire_from_translation(value)
    return msgspec.msgpack.Ext(
        _LAZY_TRANSLATION_EXT_CODE,
        _WIRE_ENCODER.encode(wire),
    )


def _msgpack_ext_hook(code: int, data: memoryview) -> LazyTranslation:
    """Decode the reserved extension and reject every unknown extension code."""
    if code != _LAZY_TRANSLATION_EXT_CODE:
        raise msgspec.DecodeError(f"Unsupported MessagePack extension code: {code}")
    try:
        wire = _WIRE_DECODER.decode(data)
        _validate_wire(wire)
    except TypeError as exc:
        raise msgspec.DecodeError(str(exc)) from exc
    return LazyTranslation(
        wire.singular,
        wire.plural,
        wire.n,
        **wire.variables,
    )


def _json_enc_hook(value: Any) -> str:
    """Resolve LazyTranslation in the caller's catalog; other str subclasses (Markup) go out as plain text."""
    if not isinstance(value, LazyTranslation):
        if isinstance(value, str):
            return str(value)
        raise NotImplementedError
    _wire_from_translation(value)
    try:
        return str(value)
    except LookupError:
        source = value.singular if value.n == 1 or value.plural is None else value.plural
        variables = dict(value.variables)
        if value.n is not None:
            variables.setdefault("num", value.n)
        return source % variables if variables else source


_MSGPACK_ENCODER = msgspec.msgpack.Encoder(enc_hook=_msgpack_enc_hook)
_MSGPACK_DECODER = msgspec.msgpack.Decoder(ext_hook=_msgpack_ext_hook)
_JSON_ENCODER = msgspec.json.Encoder(enc_hook=_json_enc_hook)


def _decode_translatable_msgpack(data: bytes) -> object:
    """Decode an untyped SSE payload while restoring marked lazy values."""
    return _MSGPACK_DECODER.decode(data)


def _encode_json_with_translations(
    value: object,
    translations: TranslationCatalog,
) -> bytes:
    """Encode one generic payload under an explicit connection catalog."""
    token = bind_translations(translations)
    try:
        return _JSON_ENCODER.encode(value)
    finally:
        reset_translations(token)


class TranslatableMsgspecModel(MsgspecModel):
    """Strong model whose nested LazyTranslation values survive MessagePack."""

    _mp_encoder: ClassVar[msgspec.msgpack.Encoder] = _MSGPACK_ENCODER
    _json_encoder: ClassVar[msgspec.json.Encoder] = _JSON_ENCODER

    def to_dict(self) -> dict[str, Any]:
        """Resolve nested lazy translations into frontend-safe builtins."""
        return msgspec.to_builtins(self, enc_hook=_json_enc_hook)

    @classmethod
    def _get_mp_decoder(cls) -> msgspec.msgpack.Decoder:
        """Cache one extension-aware typed decoder on each concrete subclass."""
        attr_name = "_translatable_mp_decoder"
        decoder = cls.__dict__.get(attr_name)
        if decoder is None:
            decoder = msgspec.msgpack.Decoder(
                type=cls,
                ext_hook=_msgpack_ext_hook,
            )
            setattr(cls, attr_name, decoder)
        return decoder


__all__ = ["TranslatableMsgspecModel"]
