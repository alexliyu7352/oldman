"""Serializer migration public-boundary tests."""

from __future__ import annotations

import unittest

import oldman.serializers as serializers
from oldman.serializers import (
    BaseSerializer,
    DataclassModelMixin,
    JsonSerializer,
    MsgpackSerializer,
    MsgspecModel,
    MsgspecSafeModel,
    NullSerializer,
    PickleSerializer,
    create_cache_serializer,
    resolve_cache_serializer,
)


class ExampleModel(MsgspecModel):
    value: str


class ExampleSafeModel(MsgspecSafeModel):
    value: str


class OldmanSerializersPublicApiTest(unittest.TestCase):
    def test_dunder_all_and_star_exports_match_the_live_source_surface(self) -> None:
        expected_exports = (
            "BaseSerializer",
            "DataclassModelMixin",
            "JsonSerializer",
            "MsgpackSerializer",
            "MsgspecModel",
            "MsgspecSafeModel",
            "NullSerializer",
            "PickleSerializer",
            "create_cache_serializer",
            "resolve_cache_serializer",
        )
        namespace: dict[str, object] = {}
        exec("from oldman.serializers import *", {}, namespace)

        self.assertEqual(expected_exports, serializers.__all__)
        self.assertEqual(set(expected_exports), set(namespace))
        self.assertFalse(hasattr(serializers, "All"))
        self.assertNotIn("ModelSerializer", namespace)
        self.assertNotIn("PydanticModelSerializer", namespace)
        expected_objects = {
            "BaseSerializer": BaseSerializer,
            "DataclassModelMixin": DataclassModelMixin,
            "JsonSerializer": JsonSerializer,
            "MsgpackSerializer": MsgpackSerializer,
            "MsgspecModel": MsgspecModel,
            "MsgspecSafeModel": MsgspecSafeModel,
            "NullSerializer": NullSerializer,
            "PickleSerializer": PickleSerializer,
            "create_cache_serializer": create_cache_serializer,
            "resolve_cache_serializer": resolve_cache_serializer,
        }
        for name, value in expected_objects.items():
            with self.subTest(name=name):
                self.assertIs(value, getattr(serializers, name))

    def test_msgspec_models_keep_source_to_dict_without_invented_aliases(self) -> None:
        self.assertEqual({"value": "one"}, ExampleModel("one").to_dict())
        self.assertEqual({"value": "two"}, ExampleSafeModel("two").to_dict())
        self.assertFalse(hasattr(ExampleModel("one"), "to_builtins"))
        self.assertFalse(hasattr(ExampleSafeModel("two"), "to_builtins"))

    def test_msgpack_decoder_cache_isolated_between_parent_and_child_models(self) -> None:
        """A child model must never inherit a decoder configured for its parent."""

        class ParentModel(MsgspecModel):
            value: str

        class ChildModel(ParentModel):
            enabled: bool = False

        parent = ParentModel.from_msgpack(ParentModel("parent").to_msgpack())
        child = ChildModel.from_msgpack(ChildModel("child", True).to_msgpack())

        self.assertIs(type(parent), ParentModel)
        self.assertIs(type(child), ChildModel)
        self.assertTrue(child.enabled)

    def test_json_decoder_cache_isolated_between_parent_and_child_models(self) -> None:
        """JSON decoding must use the concrete subclass after decoding its parent."""

        class ParentModel(MsgspecModel):
            value: str

        class ChildModel(ParentModel):
            enabled: bool = False

        parent = ParentModel.from_json_bytes(ParentModel("parent").to_json_bytes())
        child = ChildModel.from_json_bytes(ChildModel("child", True).to_json_bytes())

        self.assertIs(type(parent), ParentModel)
        self.assertIs(type(child), ChildModel)
        self.assertTrue(child.enabled)


if __name__ == "__main__":
    unittest.main()
