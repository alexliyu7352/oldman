"""The service refuses to start when a configured language has no published catalog."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import oldman.conf as conf
from oldman.web.i18n import ensure_frontend_catalogs
from oldman.web.staticfiles import StaticBundleRegistry, register_project_bundle

LANGUAGES = {
    "en": {"aliases": [], "name": "English", "flag": ""},
    "zh-Hans": {"aliases": [], "name": "简体中文", "flag": ""},
}


def fake_settings(languages: dict[str, Any] | None = None) -> Any:
    """Only the language set matters here; the build reads the same mapping."""
    return SimpleNamespace(
        i18n=SimpleNamespace(use_i18n=True, languages=LANGUAGES if languages is None else languages, default_language="en"),
        web=SimpleNamespace(static=SimpleNamespace(url="/static")),
    )


def publish(catalogs_dir: Path, *names: str) -> None:
    """Write the catalog files `oldman i18n compile-frontend` would have published."""
    catalogs_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (catalogs_dir / f"{name}.json").write_text('{"locale":"x","messages":{}}\n', encoding="utf-8")


class PublishedCatalogGateTest(unittest.TestCase):
    """Startup contract between settings.i18n.languages and the collected static root."""

    def setUp(self) -> None:
        self.enterContext(patch.dict(conf.__dict__, {"settings": fake_settings()}))

    def production_registry(self, root: Path) -> StaticBundleRegistry:
        """Register one project bundle against a collected static root."""
        registry = StaticBundleRegistry()
        register_project_bundle(
            registry,
            name="app:main",
            entry_path="src/main.ts",
            static_root=root,
            static_url="/static/",
            dev_mode=False,
        )
        return registry

    def test_every_configured_language_published_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            publish(root / "dist" / "i18n", "en", "zh-hans")

            ensure_frontend_catalogs(self.production_registry(root), "app:main")

    def test_a_language_without_a_catalog_stops_the_start(self) -> None:
        """菜单由 settings 驱动，产物由构建驱动；少一份目录就会点出一个没有翻译的语言。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            publish(root / "dist" / "i18n", "en")

            with self.assertRaisesRegex(RuntimeError, "zh-Hans") as caught:
                ensure_frontend_catalogs(self.production_registry(root), "app:main")

        self.assertIn(str(root / "dist" / "i18n"), str(caught.exception))
        self.assertNotIn("en,", str(caught.exception))

    def test_dev_mode_warns_against_the_source_directory_and_never_raises(self) -> None:
        registry = StaticBundleRegistry()
        register_project_bundle(
            registry,
            name="app:main",
            entry_path="src/main.ts",
            static_root="",
            static_url="",
            dev_mode=True,
            dev_server_url="http://localhost:5173/",
        )
        with tempfile.TemporaryDirectory() as directory:
            source_dir = Path(directory) / "frontend" / "public" / "i18n"
            publish(source_dir, "en")

            with patch("oldman.web.i18n.assets.logger") as logged:
                ensure_frontend_catalogs(registry, "app:main", source_dir=source_dir)
                warned = logged.warning.call_args
                ensure_frontend_catalogs(registry, "app:main")

        self.assertIn("zh-Hans", warned.args)
        self.assertEqual(1, logged.warning.call_count)


if __name__ == "__main__":
    unittest.main()
