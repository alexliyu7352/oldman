"""clean_text removes invisible characters without breaking the ones that shape visible text."""

from __future__ import annotations

import unittest

from oldman.utils.strings_utils import clean_text

SCOTLAND_FLAG = "\U0001f3f4\U000e0067\U000e0062\U000e0073\U000e0063\U000e0074\U000e007f"


class CleanTextTest(unittest.TestCase):
    def test_whitespace_is_collapsed_and_invisible_characters_are_removed(self) -> None:
        self.assertEqual("第一行 第二行 A B CD", clean_text("第一行\n第二行\tA\xa0B　C​D".encode()))
        # zero width space, BOM, direction marks and overrides, soft hyphen, word joiner, language tag
        self.assertEqual("abcdefgh", clean_text("a​b﻿c‎d‮e­f⁠g\U000e0001h"))

    def test_joiners_that_shape_the_text_are_kept(self) -> None:
        """G5-7: every Cf character was removed, which split emoji sequences and changed Persian spelling."""
        family = "\U0001f468‍\U0001f469‍\U0001f467"
        persian = "می‌خواهم"
        for text in (family, persian):
            with self.subTest(text=text):
                self.assertEqual(text, clean_text(text))

    def test_a_subdivision_flag_is_kept_and_stray_tags_are_removed(self) -> None:
        self.assertEqual(SCOTLAND_FLAG, clean_text(SCOTLAND_FLAG))
        # Tag characters show nothing on their own and can carry hidden text.
        self.assertEqual("abc", clean_text("abc\U000e0069\U000e0067\U000e006e"))
        self.assertEqual(SCOTLAND_FLAG, clean_text(SCOTLAND_FLAG + "\U000e0068\U000e0069"))

    def test_format_characters_that_are_themselves_visible_are_kept(self) -> None:
        arabic_number_sign = "؀١٢٣"
        self.assertEqual(arabic_number_sign, clean_text(arabic_number_sign))


if __name__ == "__main__":
    unittest.main()
