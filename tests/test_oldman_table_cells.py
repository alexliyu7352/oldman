"""Shared table cell primitives and filter parsers."""

from __future__ import annotations

import datetime as dt
import unittest

from markupsafe import Markup

from oldman.web.components.tables import (
    RowAction,
    TableValidationError,
    badge,
    date_cell,
    link,
    muted,
    parse_boolean_filter,
    parse_filter_datetime,
    parse_int_filter,
    row_actions,
    truncated,
)


class CellPrimitiveTest(unittest.TestCase):
    def test_badge_escapes_and_falls_back_to_the_neutral_tone(self) -> None:
        self.assertEqual('<span class="om-badge om-badge-success">Live</span>', str(badge("Live", "success")))
        self.assertEqual('<span class="om-badge om-badge-default">&lt;b&gt;</span>', str(badge("<b>", "secondary")))
        self.assertEqual('<span class="om-badge om-badge-default">x</span>', str(badge("x", "neon")))

    def test_text_helpers(self) -> None:
        self.assertEqual('<span class="text-default-500">Never</span>', str(muted("Never")))
        self.assertEqual('<span class="text-default-500 truncate inline-block" style="max-width: 120px;">-</span>', str(truncated(None, max_width=120)))
        self.assertEqual('<a class="link-primary font-medium" href="/users/1/edit">a&amp;b</a>', str(link("/users/1/edit", "a&b")))

    def test_date_cell_returns_display_and_iso_raw(self) -> None:
        moment = dt.datetime(2026, 9, 17, 8, 30)
        self.assertEqual(("2026-09-17 08:30", "2026-09-17T08:30:00"), date_cell(moment))
        self.assertEqual(("2026-09-17", "2026-09-17"), date_cell(dt.date(2026, 9, 17), date_format="%Y-%m-%d"))
        self.assertEqual(("", ""), date_cell(None))
        display, raw = date_cell("", empty="Never")
        self.assertEqual(('<span class="text-default-500">Never</span>', ""), (str(display), raw))
        self.assertIsInstance(display, Markup)
        self.assertEqual(("fixture", "fixture"), date_cell("fixture"))

    def test_row_actions_render_links_and_modal_buttons(self) -> None:
        html = str(
            row_actions(
                [
                    RowAction("Edit", href="/rows/1/edit", icon="ri-pencil-fill"),
                    RowAction("Delete", modal_target="#row-delete-modal", modal_url="/rows/1/delete-modal", icon="ri-delete-bin-line", danger=True),
                ],
                label="Row actions",
            )
        )
        self.assertIn('<div class="om-dropdown"><button class="om-button om-button-ghost-secondary om-button-sm om-button-icon" type="button" data-om-dropdown-toggle aria-expanded="false">', html)
        self.assertIn('<span class="sr-only">Row actions</span>', html)
        self.assertIn('<li><a class="om-dropdown-item" href="/rows/1/edit"><i class="ri-pencil-fill" aria-hidden="true"></i>Edit</a></li>', html)
        self.assertIn(
            '<li><button class="om-dropdown-item om-dropdown-item-danger" type="button" data-om-modal-target="#row-delete-modal" data-om-modal-url="/rows/1/delete-modal">',
            html,
        )
        self.assertTrue(html.endswith("</ul></div>"))

        hinted = str(RowAction("Preview", icon="ri-image-line", attrs={"data-om-feedback-message": 'Use the "edit" page'}).render())
        self.assertEqual('<li><button class="om-dropdown-item" type="button" data-om-feedback-message="Use the &#34;edit&#34; page"><i class="ri-image-line" aria-hidden="true"></i>Preview</button></li>', hinted)


class FilterParserTest(unittest.TestCase):
    def test_boolean_filter(self) -> None:
        for value, expected in (("1", True), ("YES", True), ("on", True), ("0", False), ("false", False), (" off ", False)):
            self.assertIs(expected, parse_boolean_filter(value))
        with self.assertRaises(TableValidationError):
            parse_boolean_filter("maybe")

    def test_datetime_filter_normalises_timezones_to_naive_utc(self) -> None:
        self.assertIsNone(parse_filter_datetime(""))
        self.assertIsNone(parse_filter_datetime(None))
        self.assertEqual(dt.datetime(2026, 9, 17, 8, 0), parse_filter_datetime("2026-09-17T10:00:00+02:00"))
        self.assertEqual(dt.datetime(2026, 9, 17, 0, 0), parse_filter_datetime(dt.date(2026, 9, 17)))
        self.assertEqual(dt.datetime(2026, 9, 17, 9, 30), parse_filter_datetime("2026-09-17T09:30"))
        with self.assertRaises(TableValidationError):
            parse_filter_datetime("yesterday")

    def test_int_filter_checks_bounds(self) -> None:
        self.assertEqual(42, parse_int_filter(" 42 ", label="confidence", minimum=0, maximum=100))
        for bad in ("abc", "-1", "101"):
            with self.subTest(bad=bad), self.assertRaisesRegex(TableValidationError, "Invalid confidence filter"):
                parse_int_filter(bad, label="confidence", minimum=0, maximum=100)


class CellLinkSchemeTest(unittest.TestCase):
    """`escape()` keeps a url inside its quotes; it says nothing about the scheme.

    These two helpers build an anchor out of a url a column callback computed, and that callback
    routinely passes row data through. `is_safe_link` is the framework's existing rule for exactly
    this; it just had not reached here.
    """

    def test_link_refuses_a_scheme_that_executes(self) -> None:
        for url in ("javascript:alert(1)", "data:text/html,<script>1</script>", "vbscript:msgbox"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                link(url, "Open")

    def test_link_still_allows_an_external_destination(self) -> None:
        rendered = str(link("https://vendor.example/orders/7", "Vendor"))
        self.assertIn('href="https://vendor.example/orders/7"', rendered)

    def test_row_action_refuses_a_scheme_that_executes(self) -> None:
        with self.assertRaises(ValueError):
            RowAction(label="Open", href="javascript:alert(1)").render()

    def test_row_action_still_allows_an_external_destination(self) -> None:
        rendered = str(RowAction(label="Vendor", href="https://vendor.example/orders/7").render())
        self.assertIn('href="https://vendor.example/orders/7"', rendered)


if __name__ == "__main__":
    unittest.main()
