"""media_url derives the browser URL of a stored name from the media route."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import oldman.conf as conf
from oldman.storage import media_url


def settings_with(url: str) -> SimpleNamespace:
    return SimpleNamespace(web=SimpleNamespace(media=SimpleNamespace(url=url, storage="default")))


class MediaUrlTest(unittest.TestCase):
    def test_it_joins_the_configured_prefix_and_escapes_the_name(self) -> None:
        with patch.dict(conf.__dict__, {"settings": settings_with("/media/")}):
            self.assertEqual("/media/logos/cctv%201.png", media_url("logos/cctv 1.png"))
            self.assertEqual("/media/logos/a.png", media_url("/logos/a.png"))

        with patch.dict(conf.__dict__, {"settings": settings_with("/assets/files")}):
            self.assertEqual("/assets/files/logos/a.png", media_url("logos/a.png"))

    def test_absolute_and_inline_addresses_pass_through(self) -> None:
        with patch.dict(conf.__dict__, {"settings": settings_with("/media/")}):
            self.assertEqual("https://cdn.example.test/a.png", media_url("https://cdn.example.test/a.png"))
            self.assertEqual("data:image/png;base64,AAAA", media_url("data:image/png;base64,AAAA"))

    def test_no_media_route_and_no_name_give_an_empty_url(self) -> None:
        with patch.dict(conf.__dict__, {"settings": settings_with("")}):
            self.assertEqual("", media_url("logos/a.png"))
        with patch.dict(conf.__dict__, {"settings": settings_with("/media/")}):
            self.assertEqual("", media_url(""))


if __name__ == "__main__":
    unittest.main()
