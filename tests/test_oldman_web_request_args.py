"""One reading of request arguments, shared by every component that reads them."""

from __future__ import annotations

import unittest

from oldman.web.components.selects import providers as select_providers
from oldman.web.components.tables import views as table_views
from oldman.web.http import get_arg as http_get_arg
from oldman.web.request import first_arg_value, get_arg, iter_args


class MultiValueArgs(dict):
    """Stand in for Sanic's RequestParameters: values are lists, with a getlist()."""

    def getlist(self, key: str) -> list[object]:
        """Return the stored list for one key."""
        return list(self.get(key, []))


class RequestArgumentHelpersTest(unittest.TestCase):
    """These helpers existed in four copies with two different answers; pin the one."""

    def test_every_component_reads_arguments_through_the_same_function(self) -> None:
        """Separate copies are how the two readings drifted apart in the first place."""
        self.assertIs(get_arg, http_get_arg)
        self.assertIs(get_arg, table_views.get_arg)
        self.assertIs(get_arg, select_providers.get_arg)
        self.assertIs(iter_args, table_views.iter_args)
        self.assertIs(iter_args, select_providers.iter_args)

    def test_an_empty_multi_value_means_absent_and_yields_the_default(self) -> None:
        """This is where the copies disagreed: one returned the default, one returned None."""
        self.assertEqual("fallback", get_arg({"q": []}, "q", "fallback"))
        self.assertIsNone(get_arg({"q": []}, "q"))

    def test_tuples_are_reduced_like_lists(self) -> None:
        """Only one of the old copies handled tuples; both shapes reach here from Sanic."""
        self.assertEqual("first", get_arg({"q": ("first", "second")}, "q"))
        self.assertEqual("fallback", get_arg({"q": ()}, "q", "fallback"))

    def test_present_values_win_over_the_default(self) -> None:
        """The ordinary path must be untouched by the empty-value rule."""
        self.assertEqual("news", get_arg({"q": ["news", "ignored"]}, "q", "fallback"))
        self.assertEqual("news", get_arg({"q": "news"}, "q", "fallback"))

    def test_a_mapping_without_get_falls_back(self) -> None:
        """Views pass whatever `request.args` is; a stand-in may not be a mapping at all."""
        self.assertEqual("fallback", get_arg(object(), "q", "fallback"))
        self.assertEqual([], iter_args(object()))

    def test_iter_args_reduces_every_value(self) -> None:
        """Filter parsing walks the args, so it needs the same single-value reading."""
        self.assertEqual(
            [("a", "1"), ("b", "2")],
            sorted(iter_args({"a": ["1"], "b": ("2", "3")})),
        )

    def test_first_arg_value_keeps_non_sequences_intact(self) -> None:
        """Strings are sequences too, and must not be reduced to their first character."""
        self.assertEqual("abc", first_arg_value("abc"))
        self.assertEqual(7, first_arg_value(7))

    def test_getlist_survives_a_missing_key(self) -> None:
        """`value in {"", None}` raised TypeError once get_arg could return a list."""
        args = MultiValueArgs({"kept": ["1", "2"]})
        self.assertEqual(["1", "2"], select_providers.getlist_arg(args, "kept"))
        self.assertEqual([], select_providers.getlist_arg(args, "absent"))
        self.assertEqual([], select_providers.getlist_arg({}, "absent"))


if __name__ == "__main__":
    unittest.main()
