"""Framework Python/Jinja Tailwind inventory tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.oldman_tailwind_inventory import (
    admin_tailwind_utilities,
    css_class_selector,
    framework_tailwind_utilities,
    inventory_utilities,
    render_inventory_block,
)

ROOT = Path(__file__).resolve().parents[1]
SHARED_CSS = ROOT / "frontend" / "packages" / "oldman-web" / "src" / "styles" / "tailwind.css"
ADMIN_CSS = ROOT / "frontend" / "apps" / "admin" / "src" / "admin.css"


class OldmanTailwindInventoryTest(unittest.TestCase):
    """Prevent server-rendered framework classes from disappearing in npm consumers."""

    def test_shared_css_includes_framework_emitters(self) -> None:
        expected = framework_tailwind_utilities(ROOT)
        actual = inventory_utilities(SHARED_CSS.read_text(encoding="utf-8"))

        self.assertTrue(set(expected).issubset(actual))
        for utility in (
            "-translate-y-1/2",
            "align-middle",
            "min-h-9",
            "focus:ring-red-200/60",
            "min-w-[680px]",
            "pe-11",
            "right-0",
            "sm:flex-row",
            "top-1/2",
            "lg:justify-between",
            "px-4",
            "py-10",
            "w-64",
        ):
            self.assertIn(utility, actual)

    def test_admin_keeps_its_private_python_utility_inventory(self) -> None:
        admin_source = ADMIN_CSS.read_text(encoding="utf-8")
        shared = set(framework_tailwind_utilities(ROOT))
        admin = set(admin_tailwind_utilities(ROOT))

        self.assertIn('@source "../../../../oldman/apps/admin/**/*.py";', admin_source)
        self.assertIn("max-w-xl", admin)
        self.assertNotIn("max-w-xl", shared)

        admin_assets = (
            ROOT / "oldman" / "apps" / "admin" / "static" / "oldman" / "admin" / "assets"
        )
        built_css = "\n".join(
            path.read_text(encoding="utf-8")
            for path in admin_assets.glob("*.css")
        )
        self.assertTrue(built_css, "Admin CSS bundle must be built and tracked")
        for utility in admin:
            self.assertIn(css_class_selector(utility), built_css, utility)

    def test_shared_back_to_top_template_does_not_promise_an_undefined_shadow(self) -> None:
        template = ROOT / "oldman" / "web" / "templates" / "oldman" / "dashboard" / "partials" / "back_to_top.html"
        source = template.read_text(encoding="utf-8")

        self.assertIn('id="back-to-top"', source)
        self.assertNotIn("shadow-om-dropdown", source)

    def test_inventory_is_derived_from_python_and_jinja_class_emitters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            web_root = root / "oldman" / "web"
            admin_root = root / "oldman" / "admin"
            web_root.mkdir(parents=True)
            admin_root.mkdir(parents=True)
            (web_root / "renderer.py").write_text(
                'class Renderer:\n    wrapper_class = "flex min-h-[41px] pe-11 -translate-y-1/2 om-field"\n',
                encoding="utf-8",
            )
            (web_root / "fragment.html").write_text(
                '<div class="sm:flex-row px-7 om-card"></div>\n',
                encoding="utf-8",
            )
            (admin_root / "private.html").write_text(
                '<div class="max-w-[913px]"></div>\n',
                encoding="utf-8",
            )

            utilities = framework_tailwind_utilities(root)

        self.assertEqual(("-translate-y-1/2", "flex", "min-h-[41px]", "pe-11", "px-7", "sm:flex-row"), utilities)
        self.assertNotIn("max-w-[913px]", utilities)
        block = render_inventory_block(root=ROOT)
        self.assertIn('/* oldman-tailwind-inventory:start */', block)
        self.assertIn('@source inline("min-w-[680px]");', block)


if __name__ == "__main__":
    unittest.main()
