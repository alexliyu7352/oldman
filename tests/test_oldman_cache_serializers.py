from __future__ import annotations

import unittest

from oldman.serializers.cache import (
    JsonSerializer,
    MsgpackSerializer,
    NullSerializer,
    PickleSerializer,
    create_cache_serializer,
    resolve_cache_serializer,
)


class CacheSerializerTest(unittest.TestCase):
    def test_builtin_serializers_round_trip_structured_values(self) -> None:
        value = {"items": [1, 2], "enabled": True}
        for serializer in (PickleSerializer(), JsonSerializer(), MsgpackSerializer()):
            with self.subTest(serializer=type(serializer).__name__):
                self.assertEqual(value, serializer.loads(serializer.dumps(value)))

    def test_null_serializer_keeps_object_identity(self) -> None:
        value: list[int] = [1]
        serializer = NullSerializer()
        self.assertIs(value, serializer.loads(serializer.dumps(value)))

    def test_loads_none_preserves_cache_miss(self) -> None:
        for serializer in (PickleSerializer(), JsonSerializer(), MsgpackSerializer(), NullSerializer()):
            self.assertIsNone(serializer.loads(None))

    def test_names_are_case_insensitive_and_unknown_names_fail(self) -> None:
        self.assertIsInstance(create_cache_serializer("PICKLE"), PickleSerializer)
        with self.assertRaisesRegex(ValueError, "unknown cache serializer"):
            create_cache_serializer("yaml")

    def test_existing_serializer_instance_is_not_wrapped(self) -> None:
        serializer = MsgpackSerializer()
        self.assertIs(serializer, resolve_cache_serializer(serializer))
