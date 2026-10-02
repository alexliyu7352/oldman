"""The generated public API index under docs/public/en/api/ and the resolver that builds it."""

from __future__ import annotations

import re
import tempfile
import textwrap
import unittest
from pathlib import Path

from scripts import api_index

ROOT = Path(__file__).resolve().parents[1]
#: ``from oldman.x import A, B as C`` or a parenthesized, possibly multi-line, name list.
DOCUMENTED_IMPORT = re.compile(r"from (oldman[\w.]*) import (\([^)]*\)|[^\n]+)")


def write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")


class CommittedIndexTest(unittest.TestCase):
    """Agents read the committed pages, so they must say what the source says."""

    def test_committed_index_matches_the_source(self) -> None:
        stale = api_index.stale_pages(ROOT, api_index.render(ROOT))
        self.assertEqual([], stale, f"run `python {api_index.GENERATOR} --write` and commit the result")


def documented_imports(text: str) -> list[tuple[str, str]]:
    """Every (module, name) a Markdown page imports from oldman."""
    found = []
    for match in DOCUMENTED_IMPORT.finditer(text):
        names = match.group(2).strip().strip("()")
        for raw in re.split(r"[,\n]", names):
            name = raw.split("#", 1)[0].strip().split(" as ")[0].strip().strip("`")
            if name.isidentifier():
                found.append((match.group(1), name))
    return found


class DocumentedImportsTest(unittest.TestCase):
    """What the docs teach to import must be something the index lists."""

    def test_every_documented_import_is_listed_in_the_index(self) -> None:
        modules = api_index.public_modules(ROOT)
        unlisted = []
        for page in sorted((ROOT / "docs" / "public").rglob("*.md")):
            if page.is_relative_to(ROOT / api_index.OUTPUT):
                continue
            for module, name in documented_imports(page.read_text(encoding="utf-8")):
                listed = name in modules.get(module, ())
                submodule = not name.startswith("_") and (f"{module}.{name}" in modules or api_index.is_package(ROOT, f"{module}.{name}"))
                if not (listed or submodule):
                    unlisted.append(f"{page.relative_to(ROOT)}: from {module} import {name}")
        self.assertEqual([], unlisted, "import it from where the API index lists it, or add the name to that module's __all__")

    def test_documented_imports_are_read_from_parenthesized_lists(self) -> None:
        text = "```python\nfrom oldman.conf.schemas import (\n    DatabaseConfig,\n    RedisConfig as Redis,  # note\n)\nfrom oldman.web import router\n```"
        self.assertEqual(
            [("oldman.conf.schemas", "DatabaseConfig"), ("oldman.conf.schemas", "RedisConfig"), ("oldman.web", "router")],
            documented_imports(text),
        )


class ResolverTest(unittest.TestCase):
    """Exported names are followed to their definitions without importing anything."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write(
            self.root,
            "oldman/shop/__init__.py",
            '''
            """Shop entry points."""
            raise RuntimeError("importing this package needs configured settings")
            from .models import Cart as Basket, PRICE_SCALE, Money
            from .services import checkout
            from sanic import Request
            from . import helpers

            def __getattr__(name):
                """Load expensive objects lazily."""

            __all__ = ["Basket", "PRICE_SCALE", "Money", "checkout", "Request", "helpers", "registry"]
            ''',
        )
        write(
            self.root,
            "oldman/shop/models.py",
            '''
            """Shop data."""

            #: Digits kept after the decimal point.
            PRICE_SCALE = 2

            class Discount:
                """Money taken off a cart."""

            type Money = int | str

            class Cart(Base):
                """A customer's open cart."""

                owner: str
                _secret: str = "x"

                def __init__(self, owner: str, *, size: int = 3) -> None:
                    self.owner = owner

                @property
                def total(self) -> int:
                    """Sum of the lines."""
                    return 0

                async def add(self, sku: str) -> None:
                    """Add one item."""

                def _hidden(self) -> None:
                    pass

            __all__ = ["PRICE_SCALE", "Discount"]
            ''',
        )
        write(self.root, "oldman/shop/services.py", "from ._impl import checkout\n")
        write(self.root, "oldman/shop/_impl.py", 'async def checkout(cart_id: int) -> str:\n    """Pay for a cart."""\n\n__all__ = ["checkout"]\n')
        write(self.root, "oldman/shop/helpers.py", '"""Small helpers."""\n')
        api_index.parse.cache_clear()

    def tearDown(self) -> None:
        api_index.parse.cache_clear()
        self.tmp.cleanup()

    def entries(self) -> dict[str, api_index.Entry]:
        (package,) = api_index.collect(self.root)
        self.assertEqual("oldman.shop", package.name)
        self.assertEqual("Shop entry points.", package.summary)
        return {entry.name: entry for entry in package.entries}

    def test_a_module_lists_only_names_its_package_does_not_already_export(self) -> None:
        (package,) = api_index.collect(self.root)
        # PRICE_SCALE is re-exported by the package from the same definition; _impl is private.
        self.assertEqual(
            [("oldman.shop.models", "Shop data.", ["Discount"])], [(s.module, s.summary, [e.name for e in s.entries]) for s in package.sections]
        )
        self.assertEqual(len(package.entries) + 1, package.size)

    def test_each_kind_of_definition_is_described(self) -> None:
        entries = self.entries()

        basket = entries["Basket"]
        self.assertEqual(("class", "class Cart(Base)", "oldman.shop.models"), (basket.kind, basket.signature, basket.defined_in))
        self.assertEqual("Cart(owner: str, *, size: int=3) -> None", basket.constructor)
        self.assertEqual(
            ["owner: str", "property total: int", "async def add(sku: str) -> None"],
            [member.signature for member in basket.members],
        )

        checkout = entries["checkout"]
        self.assertEqual(("function", "async def checkout(cart_id: int) -> str"), (checkout.kind, checkout.signature))
        self.assertEqual(("oldman.shop._impl", "Pay for a cart."), (checkout.defined_in, checkout.summary))

        self.assertEqual(
            ("value", "PRICE_SCALE = 2", "Digits kept after the decimal point."),
            (entries["PRICE_SCALE"].kind, entries["PRICE_SCALE"].signature, entries["PRICE_SCALE"].summary),
        )
        self.assertEqual(("type alias", "type Money = int | str"), (entries["Money"].kind, entries["Money"].signature))
        self.assertEqual(("re-export", "from sanic import Request"), (entries["Request"].kind, entries["Request"].signature))
        self.assertEqual(("module", "Small helpers."), (entries["helpers"].kind, entries["helpers"].summary))
        self.assertEqual("lazy attribute", entries["registry"].kind)

    def test_a_name_in_all_without_a_definition_fails(self) -> None:
        write(self.root, "oldman/shop/services.py", "from ._impl import refund\n")
        api_index.parse.cache_clear()
        with self.assertRaisesRegex(LookupError, r"'checkout' is exported by oldman\.shop\.services but bound nowhere"):
            api_index.collect(self.root)

    def test_stale_and_extra_pages_are_reported(self) -> None:
        pages = api_index.render(self.root)
        for path, text in pages.items():
            write(self.root, str(path), text)
        self.assertEqual([], api_index.stale_pages(self.root, pages))

        page = self.root / api_index.OUTPUT / "oldman.shop.md"
        page.write_text(page.read_text(encoding="utf-8").replace("size: int=3", "size: int=4"), encoding="utf-8")
        write(self.root, str(api_index.OUTPUT / "oldman.gone.md"), "# old\n")
        self.assertEqual(
            [str(api_index.OUTPUT / "oldman.shop.md"), str(api_index.OUTPUT / "oldman.gone.md")],
            api_index.stale_pages(self.root, pages),
        )


if __name__ == "__main__":
    unittest.main()
