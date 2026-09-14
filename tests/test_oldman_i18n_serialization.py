"""Lazy translation serialization contracts."""

from __future__ import annotations

import math
import unittest
from enum import StrEnum
from typing import Any, cast

import msgspec

from oldman.i18n import (
    LazyTranslation,
    TranslatableMsgspecModel,
    bind_translations,
    gettext,
    gettext_lazy,
    ngettext_lazy,
    reset_translations,
)
from oldman.i18n.serialization import (
    _LAZY_TRANSLATION_EXT_CODE,
    _decode_translatable_msgpack,
    _encode_json_with_translations,
)
from oldman.serializers import MsgspecModel


class _Catalog:
    """Prefix translated source strings so language selection stays visible."""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def gettext(self, message: str) -> str:
        """Translate one singular source string."""
        return f"{self.prefix}:{message}"

    def ngettext(self, singular: str, plural: str, n: int) -> str:
        """Translate the source form selected by the count."""
        return f"{self.prefix}:{singular if n == 1 else plural}"

    def pgettext(self, context: str, message: str) -> str:
        """Translate one contextual source string."""
        return f"{self.prefix}:{context}:{message}"


class _FailingCatalog(_Catalog):
    """Expose cleanup when one connection catalog cannot translate."""

    def gettext(self, message: str) -> str:
        """Fail before a generic payload can be encoded."""
        raise RuntimeError(f"cannot translate {message}")


class ProbeLevel(StrEnum):
    """Keep enum decoding inside the typed payload contract."""

    INFO = "info"


class ProbeDetail(msgspec.Struct, kw_only=True, frozen=True):
    """Place a lazy value below the top-level payload."""

    message: LazyTranslation
    source: str


class ProbePayload(TranslatableMsgspecModel, kw_only=True, frozen=True):  # pyright: ignore[reportGeneralTypeIssues] -- msgspec permits freezing a specialized Struct subclass
    """Exercise every value category required by notification payloads."""

    title: LazyTranslation
    body: LazyTranslation | None
    detail: ProbeDetail
    level: ProbeLevel
    note: str | None = None


class TitlePayload(TranslatableMsgspecModel, kw_only=True, frozen=True):  # pyright: ignore[reportGeneralTypeIssues] -- msgspec permits freezing a specialized Struct subclass
    """Provide a minimal target for malformed extension tests."""

    title: LazyTranslation


class PlainPayload(MsgspecModel, kw_only=True):
    """Protect the existing serializer wire format from the opt-in codec."""

    value: str
    count: int


class OldmanI18nSerializationTest(unittest.TestCase):
    """Keep lazy translations typed in storage and resolved only for output."""

    def test_msgpack_round_trip_preserves_nested_lazy_translation_state(self) -> None:
        """Binary storage must retain source messages, plural state and variables."""
        payload = ProbePayload(
            title=gettext_lazy("Imported %(count)s records", count=3),
            body=ngettext_lazy("One warning", "%(num)s warnings", 2),
            detail=ProbeDetail(
                message=gettext_lazy("Source %(name)s", name="worker"),
                source="scheduler",
            ),
            level=ProbeLevel.INFO,
        )

        encoded = payload.to_msgpack()
        decoded = ProbePayload.from_msgpack(encoded)

        self.assertIsInstance(decoded.title, LazyTranslation)
        self.assertEqual("Imported %(count)s records", decoded.title.singular)
        self.assertEqual({"count": 3}, decoded.title.variables)
        assert decoded.body is not None
        self.assertEqual(("One warning", "%(num)s warnings", 2), (decoded.body.singular, decoded.body.plural, decoded.body.n))
        self.assertIsInstance(decoded.detail.message, LazyTranslation)
        self.assertEqual("scheduler", decoded.detail.source)
        self.assertIs(decoded.level, ProbeLevel.INFO)
        self.assertIsNone(decoded.note)

        untyped = _decode_translatable_msgpack(encoded)
        self.assertIsInstance(untyped, dict)
        assert isinstance(untyped, dict)
        self.assertIsInstance(untyped["title"], LazyTranslation)
        self.assertIsInstance(untyped["detail"]["message"], LazyTranslation)

    def test_json_resolves_one_payload_per_catalog_and_restores_context(self) -> None:
        """The same decoded payload must render in each connection language."""
        decoded = ProbePayload.from_msgpack(
            ProbePayload(
                title=gettext_lazy("Imported %(count)s records", count=3),
                body=ngettext_lazy("One warning", "%(num)s warnings", 2),
                detail=ProbeDetail(
                    message=gettext_lazy("Source %(name)s", name="worker"),
                    source="scheduler",
                ),
                level=ProbeLevel.INFO,
            ).to_msgpack()
        )

        outer = bind_translations(_Catalog("outer"))
        try:
            english = bind_translations(_Catalog("en"))
            try:
                english_json = msgspec.json.decode(decoded.to_json_str())
            finally:
                reset_translations(english)

            chinese = bind_translations(_Catalog("zh"))
            try:
                chinese_json = msgspec.json.decode(decoded.to_json_bytes())
            finally:
                reset_translations(chinese)

            generic = _decode_translatable_msgpack(decoded.to_msgpack())
            connection_json = msgspec.json.decode(
                _encode_json_with_translations(generic, _Catalog("connection"))
            )

            self.assertEqual("en:Imported 3 records", english_json["title"])
            self.assertEqual("en:2 warnings", english_json["body"])
            self.assertEqual("zh:Imported 3 records", chinese_json["title"])
            self.assertEqual("connection:Source worker", connection_json["detail"]["message"])
            self.assertEqual("outer:Save", gettext("Save"))
        finally:
            reset_translations(outer)

        self.assertEqual("Save", gettext("Save"))
        fallback = msgspec.json.decode(
            TitlePayload(title=gettext_lazy("Source title")).to_json_bytes()
        )
        self.assertEqual("Source title", fallback["title"])

    def test_explicit_json_catalog_is_restored_after_translation_failure(self) -> None:
        """One broken connection translation must not leak into later work."""
        generic = _decode_translatable_msgpack(
            TitlePayload(title=gettext_lazy("Title")).to_msgpack()
        )
        outer = bind_translations(_Catalog("outer"))
        try:
            with self.assertRaisesRegex(RuntimeError, "cannot translate Title"):
                _encode_json_with_translations(generic, _FailingCatalog("broken"))
            self.assertEqual("outer:Save", gettext("Save"))
        finally:
            reset_translations(outer)

    def test_to_dict_resolves_nested_translations_and_source_plural_fallback(self) -> None:
        """通用内建值转换必须递归翻译，并保留带变量的源文本回退。"""

        class NestedPayload(TranslatableMsgspecModel, kw_only=True):
            message: LazyTranslation
            data: dict[str, Any]

        class MissingCatalog(_Catalog):
            def gettext(self, message: str) -> str:
                raise LookupError(message)

            def ngettext(self, singular: str, plural: str, n: int) -> str:
                raise LookupError(singular)

        payload = NestedPayload(
            message=gettext_lazy("Hello %(name)s", name="Oldman"),
            data={"count": ngettext_lazy("One file", "%(num)s files", 2)},
        )
        token = bind_translations(MissingCatalog("missing"))
        try:
            self.assertEqual(
                payload.to_dict(),
                {"message": "Hello Oldman", "data": {"count": "2 files"}},
            )
        finally:
            reset_translations(token)

    def test_to_dict_does_not_hide_non_lookup_translation_failures(self) -> None:
        """真正的翻译程序错误必须继续抛出。"""

        token = bind_translations(_FailingCatalog("broken"))
        try:
            with self.assertRaisesRegex(RuntimeError, "cannot translate Title"):
                TitlePayload(title=gettext_lazy("Title")).to_dict()
        finally:
            reset_translations(token)

    def test_invalid_extension_payloads_are_rejected(self) -> None:
        """Known malformed and unknown extension values must never leak through."""
        malformed_wires = (
            ["", None, None, {}],
            ["One item", "Many items", None, {}],
        )
        for wire in malformed_wires:
            malformed = msgspec.msgpack.encode(
                {
                    "title": msgspec.msgpack.Ext(
                        _LAZY_TRANSLATION_EXT_CODE,
                        msgspec.msgpack.encode(wire),
                    )
                }
            )
            with self.subTest(wire=wire), self.assertRaises(msgspec.DecodeError):
                TitlePayload.from_msgpack(malformed)

        unknown = msgspec.msgpack.encode(
            {"title": msgspec.msgpack.Ext(127, b"unsupported")}
        )
        with self.assertRaises(msgspec.DecodeError):
            _decode_translatable_msgpack(unknown)

    def test_invalid_translation_variables_are_rejected_before_encoding(self) -> None:
        """Only finite JSON scalar variables may enter the binary wire format."""
        invalid_values: tuple[Any, ...] = (
            object(),
            math.nan,
            math.inf,
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(TypeError):
                TitlePayload(
                    title=gettext_lazy("Invalid %(value)s", value=value),
                ).to_msgpack()

        invalid_key = gettext_lazy("Invalid variables")
        invalid_key.variables = cast(Any, {1: "not-a-string-key"})
        with self.assertRaises(TypeError):
            TitlePayload(title=invalid_key).to_msgpack()

    def test_typed_decoder_rejects_invalid_enum_values(self) -> None:
        """Decoding must validate the concrete payload instead of converting later."""
        invalid = ProbePayload(
            title=gettext_lazy("Title"),
            body=None,
            detail=ProbeDetail(
                message=gettext_lazy("Detail"),
                source="scheduler",
            ),
            level=cast(Any, "invalid"),
        )

        with self.assertRaises(msgspec.DecodeError):
            ProbePayload.from_msgpack(invalid.to_msgpack())

    def test_plain_msgspec_model_keeps_its_existing_wire_bytes(self) -> None:
        """Opt-in translation support must not change ordinary model encoding."""
        payload = PlainPayload(value="plain", count=3)

        self.assertEqual(
            b"\x82\xa5value\xa5plain\xa5count\x03",
            payload.to_msgpack(),
        )
        self.assertEqual(b'{"value":"plain","count":3}', payload.to_json_bytes())
        self.assertEqual(payload, PlainPayload.from_msgpack(payload.to_msgpack()))


if __name__ == "__main__":
    unittest.main()
