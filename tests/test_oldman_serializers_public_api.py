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
    NullSerializer,
    PickleSerializer,
    create_cache_serializer,
    resolve_cache_serializer,
)


class ExampleModel(MsgspecModel):
    value: str


class OldmanSerializersPublicApiTest(unittest.TestCase):
    def test_dunder_all_and_star_exports_match_the_live_source_surface(self) -> None:
        expected_exports = (
            "BaseSerializer",
            "DataclassModelMixin",
            "JsonSerializer",
            "MsgpackSerializer",
            "MsgspecModel",
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
        self.assertFalse(hasattr(ExampleModel("one"), "to_builtins"))

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


class SharedEncoderConcurrencyTest(unittest.TestCase):
    """One model base is enough because the shared encoder tolerates concurrent use.

    MsgspecSafeModel existed as a hedge: it kept a thread-local encoder per thread while
    MsgspecModel shares one class-level instance across every subclass. msgspec documents
    no thread-safety guarantee either way, so the hedge was removed only after measuring
    - and the measurement is kept here, because that is the premise the deletion rests on.
    """

    def test_the_shared_encoder_survives_concurrent_use(self) -> None:
        import threading
        from queue import Queue

        class Alpha(MsgspecModel):
            n: int
            blob: str

        class Beta(MsgspecModel):
            tag: str
            items: list[int]

        self.assertIs(Alpha._mp_encoder, Beta._mp_encoder, "subclasses share one encoder instance")

        samples = [Alpha(n=i, blob="x" * 2000) for i in range(40)]
        samples += [Beta(tag="t" * 1500, items=list(range(200))) for _ in range(40)]
        reference = {id(sample): sample.to_msgpack() for sample in samples}
        failures: Queue[str] = Queue()

        def hammer() -> None:
            try:
                for _ in range(30):
                    for sample in samples:
                        encoded = sample.to_msgpack()
                        if encoded != reference[id(sample)]:
                            failures.put(f"{type(sample).__name__} encoded differently under concurrency")
                            return
                        if type(sample).from_msgpack(encoded).to_msgpack() != encoded:
                            failures.put(f"{type(sample).__name__} failed to round trip")
                            return
            except Exception as error:  # noqa: BLE001 - any failure is the point
                failures.put(f"{type(error).__name__}: {error}")

        threads = [threading.Thread(target=hammer) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertTrue(failures.empty(), failures.get() if not failures.empty() else "")
