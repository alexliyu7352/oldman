"""Collection helper migration parity tests."""

from __future__ import annotations

import unittest

from oldman.utils.collections_utils import try_call


class FalseyArgs(list[int]):
    def __bool__(self) -> bool:
        return False


class FalseyKwargs(dict[str, int]):
    def __bool__(self) -> bool:
        return False


class OldmanCollectionsUtilsTest(unittest.TestCase):
    def test_try_call_only_replaces_none_defaults(self) -> None:
        args = FalseyArgs([3])
        kwargs = FalseyKwargs({"increment": 4})

        result = try_call(lambda value, increment=0: value + increment, args=args, kwargs=kwargs)

        self.assertEqual(7, result)

    def test_try_call_none_defaults_remain_empty(self) -> None:
        self.assertEqual("called", try_call(lambda: "called"))


if __name__ == "__main__":
    unittest.main()
