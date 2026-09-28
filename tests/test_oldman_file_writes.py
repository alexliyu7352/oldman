"""Whole-file writes and symbolic links: who writes through a link, and who replaces it."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

import orjson

from oldman.conf.containers import YamlStore
from oldman.serializers import DataclassModelMixin, MsgspecModel
from oldman.utils.files import atomic_write, save_json_file


class Flags(MsgspecModel):
    enabled: bool = False


@dataclass
class Point(DataclassModelMixin):
    x: int = 0


class LinkedFileWriteTest(unittest.IsolatedAsyncioTestCase):
    """G4-9 / G5-3: the atomic replace swapped a linked file for a regular one, splitting what the link shared."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.real = root / "shared" / "data.txt"
        self.real.parent.mkdir()
        self.real.write_text("old\n", encoding="utf-8")
        self.link = root / "service" / "data.txt"
        self.link.parent.mkdir()
        self.link.symlink_to(self.real)

    def assert_written_through(self, text: str) -> None:
        self.assertTrue(self.link.is_symlink(), "the link is still a link")
        self.assertEqual(text, self.real.read_text(encoding="utf-8"))

    def test_the_caller_says_whether_a_link_is_followed(self) -> None:
        with self.assertRaises(TypeError):
            atomic_write(self.link, "new\n")  # type: ignore[call-arg]

        atomic_write(self.link, "through\n", follow_symlinks=True)
        self.assert_written_through("through\n")

        atomic_write(self.link, "replaced\n", follow_symlinks=False)
        self.assertFalse(self.link.is_symlink())
        self.assertEqual("through\n", self.real.read_text(encoding="utf-8"))

    def test_json_helpers_write_through_a_link(self) -> None:
        save_json_file({"a": 1}, self.link)
        self.assertTrue(self.link.is_symlink())
        self.assertEqual({"a": 1}, orjson.loads(self.real.read_bytes()))

        Point(x=3).to_json_file(self.link)
        self.assertTrue(self.link.is_symlink())
        self.assertEqual({"x": 3}, orjson.loads(self.real.read_bytes()))

    async def test_a_yaml_store_writes_through_a_link(self) -> None:
        self.real.write_text("enabled: false\n", encoding="utf-8")
        store = YamlStore(Flags, self.link, check_interval=0)

        await store.update(enabled=True)

        self.assertTrue(self.link.is_symlink())
        self.assertIn("enabled: true", self.real.read_text(encoding="utf-8"))
        self.assertTrue((await store.get()).enabled)


if __name__ == "__main__":
    unittest.main()
