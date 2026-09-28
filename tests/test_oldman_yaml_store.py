"""YamlStore: a typed YAML file that follows outside edits and validates what it saves."""

from __future__ import annotations

import asyncio
import datetime as dt
import enum
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import msgspec
from ruamel.yaml.error import YAMLError

from oldman.conf.base import yaml
from oldman.conf.containers import YamlStore
from oldman.serializers import MsgspecModel
from oldman.utils.files import atomic_write


class Mode(enum.Enum):
    FAST = "fast"
    SAFE = "safe"


class Channel(MsgspecModel):
    name: str = ""
    limit: int = 1


class ChannelsFile(MsgspecModel):
    channels: dict[str, Channel] = {}
    proxies: list[str] = msgspec.field(default_factory=lambda: ["http://proxy-a"])
    mode: Mode = Mode.SAFE
    updated_at: dt.datetime | None = None


class RecordingStore(YamlStore[ChannelsFile]):
    """Records every on_file_changed call."""

    def __init__(self, path: Path, *, check_interval: float = 0) -> None:
        super().__init__(ChannelsFile, path, check_interval=check_interval)
        self.changes: list[tuple[ChannelsFile, ChannelsFile]] = []

    def on_file_changed(self, old: ChannelsFile, new: ChannelsFile) -> None:
        self.changes.append((old, new))


def edit_outside(path: Path, text: str) -> None:
    """Replace the file the way editors and deploy tools do: a new file moved over the old one.

    A new inode always changes the signature; two in-place writes within one timestamp tick of the
    same size would not, which is a limit of change detection, not what these tests are about.
    """
    atomic_write(path, text, follow_symlinks=False)


def file_data(path: Path) -> Any:
    return yaml.load(path.read_text(encoding="utf-8"))


class YamlStoreTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "channels.yaml"

    async def test_a_missing_file_is_written_from_the_schema_defaults(self) -> None:
        store = RecordingStore(self.path)

        value = await store.get()

        self.assertEqual(ChannelsFile(), value)
        self.assertEqual({"channels": {}, "proxies": ["http://proxy-a"], "mode": "safe", "updated_at": None}, file_data(self.path))
        self.assertEqual([], store.changes)

    async def test_an_outside_edit_is_loaded_and_reported_once(self) -> None:
        edit_outside(self.path, "channels:\n  news:\n    name: News\n")
        store = RecordingStore(self.path)
        first = await store.get()

        edit_outside(self.path, "channels:\n  news:\n    name: News\n    limit: 3\n")
        second = await store.get()
        third = await store.get()

        self.assertEqual(1, first.channels["news"].limit)
        self.assertEqual(3, second.channels["news"].limit)
        self.assertIs(second, third)
        self.assertEqual([(first, second)], store.changes)

    async def test_the_file_is_not_checked_again_within_the_interval(self) -> None:
        edit_outside(self.path, "mode: safe\n")
        store = RecordingStore(self.path, check_interval=60)
        await store.get()

        edit_outside(self.path, "mode: fast\n")

        self.assertEqual(Mode.SAFE, (await store.get()).mode)

    async def test_own_saves_are_not_reported_as_file_changes(self) -> None:
        store = RecordingStore(self.path)
        value = await store.get()

        value.channels["news"] = Channel(name="News", limit=2)
        await store.save(value)
        updated = await store.update(mode=Mode.FAST)

        self.assertEqual([], store.changes)
        self.assertEqual(updated, await store.get())
        self.assertEqual({"news": {"name": "News", "limit": 2}}, file_data(self.path)["channels"])
        self.assertEqual("fast", file_data(self.path)["mode"])

    async def test_update_saves_through_save_so_an_override_covers_both(self) -> None:
        """A subclass clears what it derived from the value in save(); update() must not bypass it."""

        class CountingSaves(YamlStore[ChannelsFile]):
            saves = 0

            async def save(self, value: ChannelsFile) -> None:
                await super().save(value)
                self.saves += 1

        store = CountingSaves(ChannelsFile, self.path)
        await store.update(mode=Mode.FAST)

        self.assertEqual(1, store.saves)

    async def test_update_refuses_unknown_fields_and_wrong_types_without_writing(self) -> None:
        store = RecordingStore(self.path)
        await store.get()
        before = self.path.read_text(encoding="utf-8")

        with self.assertRaises(TypeError):
            await store.update(proxy="http://proxy-b")
        with self.assertRaises(msgspec.ValidationError):
            await store.update(proxies="http://proxy-b")

        self.assertEqual(before, self.path.read_text(encoding="utf-8"))
        self.assertEqual(ChannelsFile(), await store.get())

    async def test_concurrent_updates_of_different_fields_keep_both(self) -> None:
        """Without the lock around read-modify-write, both updates start from the same value and the later save drops the other's field.

        Within the check interval get() answers from memory without the lock, so that is where the race shows.
        """
        store = RecordingStore(self.path, check_interval=60)
        await store.get()

        await asyncio.gather(store.update(mode=Mode.FAST), store.update(proxies=["http://proxy-b"]))

        saved = ChannelsFile.from_dict(file_data(self.path))
        self.assertEqual(Mode.FAST, saved.mode)
        self.assertEqual(["http://proxy-b"], saved.proxies)

    async def test_an_update_starts_from_what_another_process_just_saved(self) -> None:
        """G4-4: update() changed the value this process read up to check_interval ago, rolling back another process's save."""
        first, second = RecordingStore(self.path, check_interval=60), RecordingStore(self.path, check_interval=60)
        await first.get()
        await second.get()

        await first.update(mode=Mode.FAST)
        await second.update(proxies=["http://proxy-b"])

        self.assertEqual({"mode": "fast", "proxies": ["http://proxy-b"]}, {key: file_data(self.path)[key] for key in ("mode", "proxies")})

    async def test_update_returns_the_value_as_saved(self) -> None:
        """G4-8: it returned the object before validation, so a string stood where the file holds a datetime."""
        store = RecordingStore(self.path)

        updated = await store.update(updated_at=cast(Any, "2026-09-27T10:00:00+00:00"))

        self.assertEqual(dt.datetime(2026, 9, 27, 10, 0, tzinfo=dt.UTC), updated.updated_at)
        self.assertEqual(updated, await store.get())

    async def test_a_save_that_fails_validation_leaves_memory_as_the_file(self) -> None:
        """Callers change the shared value in place before saving; a refused save must not leave that change in memory."""
        edit_outside(self.path, "channels:\n  news:\n    name: News\n")
        store = RecordingStore(self.path)
        value = await store.get()

        value.channels["broken"] = Channel(name="Broken", limit=cast(Any, "many"))
        with self.assertRaises(msgspec.ValidationError):
            await store.save(value)

        self.assertEqual(["news"], list((await store.get()).channels))
        self.assertEqual(["news"], list(file_data(self.path)["channels"]))
        self.assertEqual([], store.changes)

    async def test_an_invalid_outside_edit_keeps_the_last_valid_value(self) -> None:
        edit_outside(self.path, "channels:\n  news:\n    limit: 2\n")
        store = RecordingStore(self.path)
        valid = await store.get()

        edit_outside(self.path, "channels:\n  news:\n    limit: many\n")
        with self.assertLogs("default", level="ERROR") as logs:
            self.assertIs(valid, await store.get())
        with self.assertNoLogs("default", level="ERROR"):
            self.assertIs(valid, await store.get())
        edit_outside(self.path, "channels:\n  news:\n    limit: 4\n")
        fixed = await store.get()

        self.assertIn("channels", logs.output[0])
        self.assertEqual(4, fixed.channels["news"].limit)
        self.assertEqual([(valid, fixed)], store.changes)

    async def test_a_file_saved_in_another_encoding_keeps_the_last_valid_value(self) -> None:
        """G4-7: a file saved as GBK raised UnicodeDecodeError on every check instead of being treated as invalid."""
        edit_outside(self.path, "channels:\n  news:\n    limit: 2\n")
        store = RecordingStore(self.path)
        valid = await store.get()

        self.path.write_bytes("channels:\n  news:\n    name: 新闻\n".encode("gbk"))
        with self.assertLogs("default", level="ERROR"):
            self.assertIs(valid, await store.get())

    async def test_an_invalid_file_on_the_first_load_raises(self) -> None:
        edit_outside(self.path, "channels: [news]\n")
        with self.assertRaises(msgspec.ValidationError):
            await RecordingStore(self.path).get()

        edit_outside(self.path, "channels: {news: [\n")
        with self.assertRaises(YAMLError):
            await RecordingStore(self.path).get()

    async def test_a_deleted_file_is_written_back_from_the_defaults_and_reported(self) -> None:
        edit_outside(self.path, "mode: fast\n")
        store = RecordingStore(self.path)
        before = await store.get()

        self.path.unlink()
        after = await store.get()

        self.assertEqual(ChannelsFile(), after)
        self.assertTrue(self.path.exists())
        self.assertEqual([(before, after)], store.changes)

    async def test_values_keep_their_types_through_the_file(self) -> None:
        store = RecordingStore(self.path)
        await store.get()
        saved = await store.update(
            channels={"news": Channel(name="News", limit=3)},
            mode=Mode.FAST,
            updated_at=dt.datetime(2026, 9, 27, 8, 30, tzinfo=dt.UTC),
        )

        reloaded = await RecordingStore(self.path).get()

        self.assertEqual(saved, reloaded)
        self.assertIsInstance(reloaded.channels["news"], Channel)
        self.assertIs(Mode.FAST, reloaded.mode)
        self.assertEqual(dt.datetime(2026, 9, 27, 8, 30, tzinfo=dt.UTC), reloaded.updated_at)

    async def test_an_unquoted_date_is_read_as_a_date(self) -> None:
        edit_outside(self.path, "updated_at: 2026-09-27 08:30:00\n")

        value = await RecordingStore(self.path).get()

        self.assertEqual(dt.datetime(2026, 9, 27, 8, 30), value.updated_at)

    async def test_a_failing_hook_is_logged_and_the_new_value_still_served(self) -> None:
        class FailingStore(YamlStore[ChannelsFile]):
            def on_file_changed(self, old: ChannelsFile, new: ChannelsFile) -> None:
                raise RuntimeError("hook failed")

        edit_outside(self.path, "mode: safe\n")
        store = FailingStore(ChannelsFile, self.path, check_interval=0)
        await store.get()

        edit_outside(self.path, "mode: fast\n")
        with self.assertLogs("default", level="ERROR"):
            value = await store.get()

        self.assertIs(Mode.FAST, value.mode)

    async def test_a_cancelled_save_finishes_the_write_before_raising(self) -> None:
        """The write runs in a thread cancellation cannot stop; releasing the lock early would let it land after the next save."""
        store = RecordingStore(self.path)
        await store.get()

        def slow_write(path: Any, data: Any, **options: Any) -> Any:
            time.sleep(0.1)
            return atomic_write(path, data, **options)

        with patch("oldman.conf.containers.atomic_write", slow_write):
            saving = asyncio.create_task(store.update(mode=Mode.FAST))
            await asyncio.sleep(0.02)
            saving.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await saving

        self.assertEqual("fast", file_data(self.path)["mode"])
        self.assertIs(Mode.FAST, (await store.get()).mode)
        self.assertEqual([], store.changes)

    def test_the_schema_is_a_msgspec_model_with_defaults_everywhere(self) -> None:
        class NeedsName(MsgspecModel):
            name: str

        class Plain(msgspec.Struct):
            name: str = ""

        with self.assertRaisesRegex(TypeError, "name"):
            YamlStore(NeedsName, self.path)
        with self.assertRaises(TypeError):
            YamlStore(cast(Any, Plain), self.path)


if __name__ == "__main__":
    unittest.main()
