"""Collected language-flag and real HTTP serving tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sanic import Sanic

from oldman.web.i18n.assets import direct_flag_url
from oldman.web.staticfiles import collect_project_static


class OldmanI18nFlagsTest(unittest.IsolatedAsyncioTestCase):
    """Keep flags optional, licensed, packaged, and shared by Web consumers."""

    def test_flag_urls_use_the_configured_static_prefix(self) -> None:
        """Built-in and project flags share one settings.web.static.url contract."""
        self.assertEqual(direct_flag_url("", static_url="/assets"), "")
        self.assertEqual(
            direct_flag_url("cn", static_url="/assets"),
            "/assets/oldman/images/flags/cn.svg",
        )
        self.assertEqual(
            direct_flag_url("custom/flags/fr.svg", static_url="/assets"),
            "/assets/custom/flags/fr.svg",
        )
        self.assertEqual(
            direct_flag_url("/media/custom/fr.svg", static_url="/assets"),
            "/media/custom/fr.svg",
        )
        self.assertEqual(
            direct_flag_url(
                "https://cdn.example/fr.svg",
                static_url="/assets",
            ),
            "https://cdn.example/fr.svg",
        )
        with self.assertRaises(ValueError):
            direct_flag_url("../secret", static_url="/assets")

    async def test_collected_flags_are_served_without_python_files(self) -> None:
        """Sanic exposes only collected data, never the package source directory."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_static = root / "source"
            public_static = root / "public"
            project_static.mkdir()
            result = collect_project_static(
                project_directory=project_static,
                destination=public_static,
            )

            self.assertGreaterEqual(result.copied, 3)
            app = Sanic(f"oldman-i18n-flags-{id(self)}")
            app.static("/assets", public_static, name="test-static")

            for flag in ("cn", "tw", "us"):
                with self.subTest(flag=flag):
                    _request, response = await app.asgi_client.get(
                        f"/assets/oldman/images/flags/{flag}.svg"
                    )
                    self.assertEqual(response.status, 200)
                    self.assertIn("image/svg+xml", response.content_type)

            for forbidden_path in (
                "/assets/oldman/__init__.py",
                "/assets/oldman/__pycache__/__init__.cpython-312.pyc",
            ):
                with self.subTest(forbidden_path=forbidden_path):
                    _request, response = await app.asgi_client.get(
                        forbidden_path
                    )
                    self.assertEqual(response.status, 404)


if __name__ == "__main__":
    unittest.main()
