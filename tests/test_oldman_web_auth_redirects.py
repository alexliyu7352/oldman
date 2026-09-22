"""safe_next_url: only plain same-site paths survive."""

from __future__ import annotations

import unittest

from oldman.web.auth import safe_next_url


class SafeNextUrlTest(unittest.TestCase):
    def test_same_site_paths_pass_through(self) -> None:
        self.assertEqual("/dashboard?tab=2#top", safe_next_url("/dashboard?tab=2#top"))
        self.assertEqual("/x", safe_next_url(["/x", "/y"]))
        self.assertEqual("/control", safe_next_url(None, "/control"))
        self.assertEqual("/", safe_next_url(""))

    def test_everything_that_could_leave_the_site_falls_back(self) -> None:
        for value in (
            "https://evil.test/",
            "//evil.test/path",
            "/\\evil.test",  # browsers normalise the backslash into //evil.test
            "\\\\evil.test",
            "/ok\r\nLocation: https://evil.test",
            "/tab\x7f",
            "relative/path",
            "javascript:alert(1)",
            [],
            b"\xff",
        ):
            with self.subTest(value=value):
                self.assertEqual("/control", safe_next_url(value, "/control"))


if __name__ == "__main__":
    unittest.main()
