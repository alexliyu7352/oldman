"""Framework Python/Jinja Tailwind inventory tests."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from scripts.oldman_tailwind_inventory import (
    admin_tailwind_utilities,
    css_class_selector,
    declared_inline_utilities,
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

        # 失败时要说清是哪几个类不见了、怎么修：这条红了通常意味着有人改了模板或 Python 里的 class。
        self.assertEqual(
            set(),
            set(expected) - set(actual),
            "framework utilities missing from the published inventory; "
            "run `python scripts/oldman_tailwind_inventory.py --write`",
        )
        for utility in (
            "-translate-y-1/2",
            "align-middle",
            "focus:ring-danger/20",
            "min-w-[680px]",
            "mt-6",
            "pe-11",
            "right-0.5",
            "space-y-4",
            "top-1/2",
        ):
            self.assertIn(utility, actual)

    def test_the_auth_language_switcher_overrides_the_dropdown_position(self) -> None:
        """两条规则都是单类选择器，后写的赢：排在 .om-dropdown 前面的话切换器会掉回 relative。"""
        source = SHARED_CSS.read_text(encoding="utf-8")

        dropdown = source.index("  .om-dropdown {")
        switcher = source.index("  .om-auth-language-switcher {")

        self.assertLess(dropdown, switcher)
        self.assertIn("@apply absolute right-4 top-4 z-20;", source[switcher:switcher + 200])

    def test_base_layer_gives_enabled_click_targets_the_pointer_cursor(self) -> None:
        # Tailwind 4 preflight dropped the hand cursor from buttons; the framework restores it once,
        # in the base layer, so sort headers, menu items and pagination never opt in one by one.
        source = SHARED_CSS.read_text(encoding="utf-8")
        base_layer = source[source.index("@layer base {") : source.index("@layer components")]
        rule = base_layer[base_layer.index("button:not(:disabled)") :]
        rule = rule[: rule.index("}") + 1]

        for selector in ("button:not(:disabled)", '[role="button"]:not([aria-disabled="true"])', "select:not(:disabled)", "summary"):
            self.assertIn(selector, rule)
        self.assertIn("cursor: pointer;", rule)

    def test_small_icon_buttons_extend_their_hit_area_and_skip_paint_containment(self) -> None:
        # Spec: 32px square icon buttons reach a 40px touch target through a pseudo-element; paint
        # containment would clip that pseudo-element, so icon-only buttons stay out of that list.
        source = SHARED_CSS.read_text(encoding="utf-8")
        rule_start = source.index(".om-button-icon.om-button-sm::after,")
        rule = source[rule_start : source.index("}", rule_start) + 1]

        self.assertIn(".oldman-icon-button-sm::after", rule)
        self.assertIn("inset: -0.25rem;", rule)
        self.assertIn(".om-button:not(.om-dropdown-toggle):not(.om-button-icon),", source)

    def test_admin_keeps_its_private_python_utility_inventory(self) -> None:
        admin_source = ADMIN_CSS.read_text(encoding="utf-8")
        shared = set(framework_tailwind_utilities(ROOT))
        admin = set(admin_tailwind_utilities(ROOT))

        self.assertIn('@source "../../../../oldman/apps/admin/**/*.py";', admin_source)
        self.assertIn("max-w-[26rem]", admin)
        self.assertNotIn("max-w-[26rem]", shared)

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


class ReleaseVerifierCanaryTest(unittest.TestCase):
    """`verify-oldman-web-package.py` names a few utilities by hand as canaries.

    The dynamic check next to them would pass vacuously if the scanner ever returned an empty
    set, so the fixed names are worth having. But nothing kept them honest: `.bg-red-600` and
    `.min-w-5` stayed in that list long after the classes left the markup, so the release
    verifier failed with "CSS is missing a published runtime selector" when the real cause was
    an expired list — and it only surfaced in a ten-minute release gate.

    This runs the same question in the ordinary suite, in milliseconds.
    """

    def test_every_hand_written_canary_is_still_safelisted(self) -> None:
        verifier = (ROOT / "scripts" / "verify-oldman-web-package.py").read_text(encoding="utf-8")
        match = re.search(r"required_utility_canaries = \(([^)]*)\)", verifier)
        self.assertIsNotNone(match, "the canary tuple is not in the shape this test reads")
        assert match is not None
        canaries = re.findall(r'"([^"]+)"', match.group(1))
        self.assertTrue(canaries, "the canary list is empty, which would make the guard vacuous")

        declared = set(declared_inline_utilities(SHARED_CSS.read_text(encoding="utf-8")))
        self.assertEqual(
            set(),
            set(canaries) - declared,
            "a release-verifier canary names a utility the published stylesheet no longer "
            "safelists; drop it from required_utility_canaries or pick a live replacement",
        )

    def test_declared_inline_utilities_covers_generated_and_hand_written_entries(self) -> None:
        declared = set(declared_inline_utilities(SHARED_CSS.read_text(encoding="utf-8")))
        generated = set(inventory_utilities(SHARED_CSS.read_text(encoding="utf-8")))

        self.assertTrue(generated <= declared, "the generated block must be part of the safelist")
        # 手写条目在生成块之外，所以 declared 必须是真超集，否则说明解析只看到了生成块。
        self.assertTrue(declared - generated, "no hand-written @source inline entry was found")
