"""Collection helper migration parity tests."""

from __future__ import annotations

import unittest

from oldman.utils.collections_utils import CollectionUtils, OptimizedFixedSizeList


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

        result = CollectionUtils.try_call(lambda value, increment=0: value + increment, args=args, kwargs=kwargs)

        self.assertEqual(7, result)

    def test_try_call_none_defaults_remain_empty(self) -> None:
        self.assertEqual("called", CollectionUtils.try_call(lambda: "called"))

    def test_try_call_gives_every_function_the_same_arguments(self) -> None:
        """G5-9: a generator passed as args was used up by the first function; the next one got no arguments."""

        def fails(value: int) -> int:
            raise KeyError(value)

        self.assertEqual(5, CollectionUtils.try_call(fails, lambda value: value, args=(value for value in [5])))


class OptimizedFixedSizeListTest(unittest.TestCase):
    def test_an_unhashable_item_is_refused_before_it_is_stored(self) -> None:
        """G5-10: the item was stored first, and once it was the oldest every later append failed until clear()."""
        items = OptimizedFixedSizeList(2)

        with self.assertRaises(TypeError):
            items.append(["unhashable"])
        for value in (1, 2, 3):
            items.append(value)

        self.assertEqual([2, 3], list(items))
        self.assertNotIn(1, items)
        self.assertIn(3, items)


if __name__ == "__main__":
    unittest.main()
