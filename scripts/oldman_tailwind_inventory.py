#!/usr/bin/env python3
"""Derive the published Tailwind utility inventory from Python/Jinja emitters."""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSS = ROOT / "frontend" / "packages" / "oldman-web" / "src" / "styles" / "tailwind.css"
INVENTORY_START = "/* oldman-tailwind-inventory:start */"
INVENTORY_END = "/* oldman-tailwind-inventory:end */"

_CLASS_ATTRIBUTE = re.compile(r"class\s*=\s*(['\"])(.*?)\1", re.DOTALL)
_INLINE_SOURCE = re.compile(r'^@source inline\("([^\"]+)"\);$', re.MULTILINE)
_SPACING_UTILITY = re.compile(r"^[mp][trblxyse]?-.+")
_EXACT_UTILITIES = {
    "absolute",
    "block",
    "border",
    "contents",
    "fixed",
    "flex",
    "grid",
    "hidden",
    "inline",
    "inline-block",
    "inline-flex",
    "relative",
    "rounded",
    "shrink",
    "sr-only",
    "sticky",
    "transition",
    "truncate",
}
_UTILITY_PREFIXES = (
    "align-",
    "bg-",
    "border-",
    "bottom-",
    "col-",
    "cursor-",
    "duration-",
    "ease-",
    "flex-",
    "font-",
    "gap-",
    "grid-",
    "h-",
    "inset-",
    "items-",
    "justify-",
    "leading-",
    "left-",
    "line-clamp-",
    "max-",
    "min-",
    "object-",
    "opacity-",
    "overflow-",
    "place-",
    "right-",
    "ring-",
    "rounded-",
    "shadow-",
    "shrink-",
    "size-",
    "space-",
    "text-",
    "top-",
    "transition-",
    "translate-",
    "w-",
    "whitespace-",
    "z-",
)


def _literal_strings(node: ast.AST) -> list[str]:
    return [
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    ]


def _target_mentions_class(target: ast.AST) -> bool:
    if isinstance(target, ast.Name):
        return "class" in target.id
    if isinstance(target, ast.Attribute):
        return "class" in target.attr
    if isinstance(target, (ast.List, ast.Tuple)):
        return any(_target_mentions_class(item) for item in target.elts)
    return False


def _python_class_values(source: str, path: Path) -> list[str]:
    values = [match.group(2) for match in _CLASS_ATTRIBUTE.finditer(source)]
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(_target_mentions_class(target) for target in node.targets):
            values.extend(_literal_strings(node.value))
        elif isinstance(node, ast.AnnAssign) and _target_mentions_class(node.target) and node.value is not None:
            values.extend(_literal_strings(node.value))
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == "class":
                    values.extend(_literal_strings(value))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and "class" in node.name:
            for child in ast.walk(node):
                if isinstance(child, ast.Return) and child.value is not None:
                    values.extend(_literal_strings(child.value))
    return values


def _base_utility(token: str) -> str:
    base = token
    while ":" in base and not base.startswith("["):
        base = base.split(":", 1)[1]
    return base.removeprefix("!")


def is_tailwind_utility(token: str) -> bool:
    """Return whether a literal class token belongs to Tailwind's utility vocabulary."""
    if not token or any(character in token for character in "{}%<>=|\"'"):
        return False
    base = _base_utility(token).removeprefix("-")
    return (
        base in _EXACT_UTILITIES
        or base.startswith(_UTILITY_PREFIXES)
        or _SPACING_UTILITY.fullmatch(base) is not None
    )


def tailwind_utilities_for_roots(root: Path, relative_roots: tuple[Path, ...]) -> tuple[str, ...]:
    """Collect literal Tailwind utilities emitted below selected source roots."""
    values: list[str] = []
    for relative_root in relative_roots:
        source_root = root / relative_root
        for path in sorted(source_root.rglob("*")):
            if path.suffix == ".html":
                values.extend(match.group(2) for match in _CLASS_ATTRIBUTE.finditer(path.read_text(encoding="utf-8")))
            elif path.suffix == ".py" and "__pycache__" not in path.parts:
                source = path.read_text(encoding="utf-8")
                values.extend(_python_class_values(source, path))
    return tuple(sorted({token for value in values for token in value.split() if is_tailwind_utility(token)}))


def framework_tailwind_utilities(root: Path = ROOT) -> tuple[str, ...]:
    """Collect utilities emitted by the public ``oldman.web`` Python/Jinja contract."""
    return tailwind_utilities_for_roots(root, (Path("oldman/web"),))


def admin_tailwind_utilities(root: Path = ROOT) -> tuple[str, ...]:
    """Collect utilities owned by the private Admin consumer."""
    return tailwind_utilities_for_roots(root, (Path("oldman/apps/admin"),))


def css_class_selector(class_name: str) -> str:
    """Return the selector prefix emitted by Tailwind for one literal class."""
    escaped = "".join(character if character.isalnum() or character in {"_", "-"} else f"\\{character}" for character in class_name)
    return f".{escaped}"


def render_inventory_block(root: Path = ROOT) -> str:
    """Render the generated CSS block carried by the npm package."""
    directives = "\n".join(f'@source inline("{utility}");' for utility in framework_tailwind_utilities(root))
    return (
        f"{INVENTORY_START}\n"
        "/* Generated by scripts/oldman_tailwind_inventory.py from framework Python/Jinja class emitters. */\n"
        f"{directives}\n"
        f"{INVENTORY_END}"
    )


def inventory_block(css: str) -> str | None:
    """Return the generated inventory block from a CSS document."""
    start = css.find(INVENTORY_START)
    end = css.find(INVENTORY_END)
    if start < 0 or end < start:
        return None
    return css[start : end + len(INVENTORY_END)]


def declared_inline_utilities(css: str) -> tuple[str, ...]:
    """Return every utility the stylesheet safelists, generated block and hand-written alike.

    A consumer's Tailwind build only emits a utility it can see. For the framework's own markup
    that visibility comes from `@source inline(...)` directives, so this set is exactly what a
    clean consumer can be expected to produce without writing the class itself.
    """
    return tuple(sorted(set(_INLINE_SOURCE.findall(css))))


def inventory_utilities(css: str) -> tuple[str, ...]:
    """Return exact utility directives recorded inside the generated block."""
    block = inventory_block(css)
    return tuple(_INLINE_SOURCE.findall(block or ""))


def synchronized_css(css: str, root: Path = ROOT) -> str:
    """Replace the generated inventory block without changing hand-authored CSS."""
    current = inventory_block(css)
    if current is None:
        raise ValueError("Tailwind CSS has no generated framework utility inventory block")
    return css.replace(current, render_inventory_block(root), 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--css", type=Path, default=DEFAULT_CSS)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--print", dest="print_block", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    css_path = args.css.resolve()
    expected = render_inventory_block(root)
    if args.print_block:
        print(expected)
        return 0
    current_css = css_path.read_text(encoding="utf-8")
    updated_css = synchronized_css(current_css, root)
    if args.write:
        css_path.write_text(updated_css, encoding="utf-8")
        print(f"Updated {css_path}")
        return 0
    if updated_css != current_css:
        expected_set = set(framework_tailwind_utilities(root))
        actual_set = set(inventory_utilities(current_css))
        for utility in sorted(expected_set - actual_set):
            print(f"missing: {utility}")
        for utility in sorted(actual_set - expected_set):
            print(f"unexpected: {utility}")
        print(f"Run `python {Path(__file__).relative_to(root)} --write` to synchronize the inventory.")
        return 1
    print("Oldman framework Tailwind utility inventory verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
