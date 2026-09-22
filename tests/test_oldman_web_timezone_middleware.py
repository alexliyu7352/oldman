"""The optional per-request timezone middleware."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import oldman.conf as conf

ROOT = Path(__file__).resolve().parents[1]


class TimezoneMiddlewareTest(unittest.TestCase):
    """Resolves a caller timezone, and only when the application asks for it.

    This used to be `middlewares/context.py`, named for an ambition it never grew into -
    a place to put whatever shared request context an application needs - while holding
    one timezone helper that nothing registered. It is now named for what it is, and it
    can actually be installed.
    """

    @staticmethod
    def _request(header: str | None = None, cookie: str | None = None) -> Any:
        return SimpleNamespace(
            headers={"X-Timezone": header} if header else {},
            cookies={"timezone": cookie} if cookie else {},
            ctx=SimpleNamespace(),
        )

    def _resolve(self, request: Any) -> str:
        from oldman.web.middlewares import add_timezone_info

        configured = SimpleNamespace(core=SimpleNamespace(time_zone="Asia/Singapore"))
        with patch.dict(conf.__dict__, {"settings": configured}):
            asyncio.run(add_timezone_info(request))
        return str(request.ctx.timezone)

    def test_it_is_not_installed_unless_asked_for(self) -> None:
        """Most services never read ctx.timezone; they should not pay for it."""
        from oldman.web.middlewares import install_timezone

        class FakeApp:
            def __init__(self) -> None:
                self.middlewares: list[Any] = []

            def register_middleware(self, middleware: Any, location: str, **kwargs: object) -> None:
                del kwargs
                self.middlewares.append((middleware, location))

        app = FakeApp()
        self.assertEqual([], app.middlewares)
        install_timezone(app)
        self.assertEqual(1, len(app.middlewares))

    def test_the_header_wins_then_the_cookie(self) -> None:
        self.assertEqual("Asia/Shanghai", self._resolve(self._request(header="Asia/Shanghai")))
        self.assertEqual("Europe/Paris", self._resolve(self._request(cookie="Europe/Paris")))
        self.assertEqual("Asia/Shanghai", self._resolve(self._request(header="Asia/Shanghai", cookie="Europe/Paris")))

    def test_no_caller_value_uses_the_configured_timezone(self) -> None:
        """Hardcoding UTC here would silently override the deployment's setting."""
        self.assertEqual("Asia/Singapore", self._resolve(self._request()))

    def test_a_hostile_value_falls_back_instead_of_raising(self) -> None:
        self.assertEqual("Asia/Singapore", self._resolve(self._request(header="Not/AZone")))

    def test_the_empty_middleware_stubs_are_gone(self) -> None:
        """Two seven-line files with no code invited people to put things in the wrong place."""
        middlewares = ROOT / "oldman" / "web" / "middlewares"
        self.assertFalse((middlewares / "_legacy_i18n.py").exists())
        self.assertFalse((middlewares / "session.py").exists())
        self.assertFalse((middlewares / "context.py").exists())


if __name__ == "__main__":
    unittest.main()
