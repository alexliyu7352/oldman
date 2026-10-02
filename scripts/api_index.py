#!/usr/bin/env python3
"""Generate the public API index under ``docs/public/en/api/`` from the Oldman source.

Agents look names up here before importing them. A name is public when a module whose dotted
name has no ``_``-prefixed part lists it in ``__all__``; that module is its import path. Nothing
is moved into packages to make this true, so the import graph never changes for the index.

``README.md`` has one row per page. A page belongs to a package: first the names the package
itself exports, then one section per submodule for the names only that submodule exports (names
an enclosing package already re-exports from the same definition are listed once, at the package).
Every entry shows its kind, signature, the first line of its docstring, the module that defines
it, and for a class its own public members.

The source is read with ``ast`` and nothing is imported: some packages need configured settings
at import time (``oldman.tasks.distributed``), and an index must not depend on that.

Run without arguments to check that the committed pages match the source (exit 1 when they do
not); run with ``--write`` to regenerate them.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path("docs/public/en/api")
#: Directories under ``oldman/`` that hold data or generated code rather than importable API.
SKIPPED_DIRECTORIES = frozenset({"scaffolds", "migrations", "locales", "static", "templates"})
GENERATOR = "scripts/api_index.py"
VALUE_LIMIT = 100


@dataclass(frozen=True)
class Member:
    """One public method, property or field defined directly in a class body."""

    signature: str
    summary: str


@dataclass(frozen=True)
class Entry:
    """One exported name of a package."""

    name: str
    kind: str
    signature: str
    summary: str
    defined_in: str
    constructor: str = ""
    members: tuple[Member, ...] = ()


@dataclass(frozen=True)
class Section:
    """The names one submodule exports that no enclosing package already exports."""

    module: str
    summary: str
    entries: tuple[Entry, ...]


@dataclass(frozen=True)
class Package:
    name: str
    summary: str
    entries: tuple[Entry, ...]
    sections: tuple[Section, ...] = ()

    @property
    def size(self) -> int:
        return len(self.entries) + sum(len(section.entries) for section in self.sections)


def module_file(root: Path, module: str) -> Path | None:
    """Return the source file of a dotted module under ``root``, or None when there is none."""
    base = root.joinpath(*module.split("."))
    if (base / "__init__.py").is_file():
        return base / "__init__.py"
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    return None


@cache
def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def exported_names(tree: ast.Module) -> list[str] | None:
    """Return a module's literal ``__all__``, or None when it has none."""
    names = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            names = ast.literal_eval(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "__all__" and node.value:
            names = ast.literal_eval(node.value)
    return list(names) if names is not None else None


def public_modules(root: Path) -> dict[str, list[str]]:
    """Every public package or module that declares ``__all__``, mapped to those names."""
    found: dict[str, list[str]] = {}
    for path in sorted((root / "oldman").rglob("*.py")):
        relative = path.relative_to(root)
        parts = relative.parent.parts if path.name == "__init__.py" else relative.with_suffix("").parts
        if any(part.startswith("_") for part in parts[1:]) or SKIPPED_DIRECTORIES.intersection(parts):
            continue
        names = exported_names(parse(path))
        if names:
            found[".".join(parts)] = names
    return found


def is_package(root: Path, module: str) -> bool:
    path = module_file(root, module)
    return path is not None and path.name == "__init__.py"


def absolute_module(current: str, is_package: bool, module: str | None, level: int) -> str:
    """Turn a (possibly relative) ``from`` import into an absolute dotted module name."""
    if level == 0:
        return module or ""
    base = current.split(".")
    if not is_package:
        base = base[:-1]
    base = base[: len(base) - (level - 1)] if level > 1 else base
    return ".".join([*base, module] if module else base)


def binding(tree: ast.Module, name: str) -> ast.AST | tuple[ast.ImportFrom, ast.alias] | None:
    """The last top-level statement that binds ``name``, as Python itself would see it."""
    found: ast.AST | tuple[ast.ImportFrom, ast.alias] | None = None
    for node in _top_level(tree.body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            found = node
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            found = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            found = node
        elif isinstance(node, ast.TypeAlias) and node.name.id == name:
            found = node
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if (alias.asname or alias.name) == name:
                    found = (node, alias)
    return found


def _top_level(body: list[ast.stmt]):
    """Top-level statements, looking into ``try``/``if`` blocks that only choose an implementation."""
    for node in body:
        if isinstance(node, ast.Try):
            yield from _top_level(node.body)
        elif isinstance(node, ast.If) and not _is_type_checking(node.test):
            yield from _top_level(node.body)
        else:
            yield node


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")


@dataclass(frozen=True)
class ThirdParty:
    """A name that a package re-exports from a library outside Oldman."""

    module: str
    name: str


def resolve(root: Path, module: str, name: str) -> tuple[str, ast.AST | ThirdParty | None]:
    """Follow re-exports until the module that defines ``name``; the node is None for a module."""
    for _ in range(20):
        path = module_file(root, module)
        if path is None:
            if module.split(".")[0] != "oldman":
                return module, ThirdParty(module, name)
            raise LookupError(f"{module} has no source file")
        tree = parse(path)
        found = binding(tree, name)
        if found is None:
            getattr_hook = binding(tree, "__getattr__")
            if isinstance(getattr_hook, ast.FunctionDef):
                return module, getattr_hook
            raise LookupError(f"{name!r} is exported by {module} but bound nowhere")
        if not isinstance(found, tuple):
            return module, found
        node, alias = found
        target = absolute_module(module, path.name == "__init__.py", node.module, node.level)
        if module_file(root, f"{target}.{alias.name}") is not None:
            return f"{target}.{alias.name}", None
        module, name = target, alias.name
    raise LookupError(f"re-export chain for {name!r} is too long")


def first_line(text: str | None) -> str:
    if not text:
        return ""
    return text.strip().splitlines()[0].strip()


def comment_summary(root: Path, module: str, node: ast.AST) -> str:
    """The ``#:`` comment lines directly above an assignment, joined."""
    path = module_file(root, module)
    if path is None or not hasattr(node, "lineno"):
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()
    collected: list[str] = []
    index = node.lineno - 2  # type: ignore[attr-defined]
    while index >= 0 and lines[index].strip().startswith("#:"):
        collected.insert(0, lines[index].strip()[2:].strip())
        index -= 1
    return first_line(" ".join(collected)) if collected else ""


def one_line(text: str) -> str:
    return " ".join(text.split())


def function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef, *, drop_first: bool = False) -> str:
    args = node.args
    if drop_first:
        positional = args.posonlyargs or args.args
        if positional:
            args = ast.arguments(
                posonlyargs=args.posonlyargs[1:] if args.posonlyargs else [],
                args=args.args if args.posonlyargs else args.args[1:],
                vararg=args.vararg,
                kwonlyargs=args.kwonlyargs,
                kw_defaults=args.kw_defaults,
                kwarg=args.kwarg,
                defaults=args.defaults,
            )
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return one_line(f"{prefix} {node.name}({ast.unparse(args)}){returns}")


def decorator_names(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> set[str]:
    names = set()
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        names.add(target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", ""))
    return names


def class_members(node: ast.ClassDef) -> tuple[Member, ...]:
    """Public methods, properties and annotated fields written in the class body itself."""
    members: dict[str, Member] = {}
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith("_"):
            decorators = decorator_names(item)
            if "overload" in decorators:
                continue
            summary = first_line(ast.get_docstring(item))
            if "property" in decorators or "cached_property" in decorators:
                returns = f": {ast.unparse(item.returns)}" if item.returns else ""
                members[item.name] = Member(one_line(f"property {item.name}{returns}"), summary)
                continue
            kind = "staticmethod " if "staticmethod" in decorators else "classmethod " if "classmethod" in decorators else ""
            signature = function_signature(item, drop_first="staticmethod" not in decorators)
            members[item.name] = Member(kind + signature, summary)
        elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) and not item.target.id.startswith("_"):
            value = f" = {_short(ast.unparse(item.value))}" if item.value is not None else ""
            members[item.target.id] = Member(one_line(f"{item.target.id}: {ast.unparse(item.annotation)}{value}"), "")
    return tuple(members.values())


def _short(text: str) -> str:
    text = one_line(text)
    return text if len(text) <= VALUE_LIMIT else text[: VALUE_LIMIT - 1] + "…"


def describe(root: Path, package: str, name: str) -> Entry:
    module, node = resolve(root, package, name)
    if node is None:
        path = module_file(root, module)
        assert path is not None
        return Entry(name, "module", f"module {module}", first_line(ast.get_docstring(parse(path))), module)
    if isinstance(node, ThirdParty):
        return Entry(
            name,
            "re-export",
            f"from {node.module} import {node.name}",
            f"Re-exported unchanged from `{node.module}`; see that library's documentation.",
            node.module,
        )
    if isinstance(node, ast.TypeAlias):
        return Entry(name, "type alias", one_line(f"type {name} = {ast.unparse(node.value)}"), comment_summary(root, module, node), module)
    if isinstance(node, ast.ClassDef):
        bases = [ast.unparse(base) for base in node.bases] + [ast.unparse(keyword) for keyword in node.keywords]
        signature = f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"
        constructor = ""
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                constructor = function_signature(item, drop_first=True).replace("def __init__", node.name, 1)
        return Entry(name, "class", one_line(signature), first_line(ast.get_docstring(node)), module, constructor, class_members(node))
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.name == "__getattr__" and name != "__getattr__":
            return Entry(name, "lazy attribute", name, f"Provided on first access by `{module}.__getattr__`.", module)
        return Entry(name, "function", function_signature(node), first_line(ast.get_docstring(node)), module)
    if isinstance(node, ast.AnnAssign):
        value = f" = {_short(ast.unparse(node.value))}" if node.value is not None else ""
        signature = f"{name}: {ast.unparse(node.annotation)}{value}"
    else:
        assert isinstance(node, ast.Assign)
        signature = f"{name} = {_short(ast.unparse(node.value))}"
    return Entry(name, "value", one_line(signature), comment_summary(root, module, node), module)


def _ordered(names: list[str]) -> list[str]:
    return sorted(set(names), key=lambda name: (name.lower(), name))


def _docstring(root: Path, module: str) -> str:
    path = module_file(root, module)
    assert path is not None
    return first_line(ast.get_docstring(parse(path)))


def collect(root: Path) -> list[Package]:
    modules = public_modules(root)
    packages = {name for name in modules if is_package(root, name)}
    sections: dict[str, list[Section]] = {}
    for module in sorted(name for name in modules if name not in packages):
        prefixes = [".".join(module.split(".")[:end]) for end in range(1, module.count(".") + 1)]
        enclosing = [prefix for prefix in prefixes if prefix in packages]
        own = []
        for name in _ordered(modules[module]):
            definition = resolve(root, module, name)
            if any(name in modules[package] and resolve(root, package, name) == definition for package in enclosing):
                continue
            own.append(describe(root, module, name))
        if own:
            parent = module.rpartition(".")[0]
            sections.setdefault(parent, []).append(Section(module, _docstring(root, module), tuple(own)))
    result = []
    for name in sorted(packages | sections.keys()):
        entries = tuple(describe(root, name, export) for export in _ordered(modules.get(name, [])))
        result.append(Package(name, _docstring(root, name), entries, tuple(sections.get(name, ()))))
    return result


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def render_readme(packages: list[Package]) -> str:
    lines = [
        "# Oldman public API index",
        "",
        f"Generated from the source of this version by `{GENERATOR}`; do not edit by hand.",
        "",
        "A name is public when a package or module listed here exports it in `__all__`; import it from that",
        "package or module exactly as its page shows. Anything not listed is internal and may change without",
        "notice. Open a page for signatures, docstring summaries and class members.",
        "",
        "| Package | Names | Summary |",
        "| --- | --- | --- |",
    ]
    for package in packages:
        lines.append(f"| [`{package.name}`]({package.name}.md) | {package.size} | {_cell(package.summary)} |")
    return "\n".join(lines) + "\n"


def render_package(package: Package) -> str:
    lines = [
        f"# `{package.name}`",
        "",
        f"Generated from the source by `{GENERATOR}`; do not edit by hand. [All packages](README.md)",
        "",
    ]
    if package.summary:
        lines += [package.summary, ""]
    if package.entries:
        lines += [f"Import with `from {package.name} import <name>`.", ""]
        for entry in package.entries:
            lines += render_entry(entry, "##")
    else:
        lines += ["The package itself exports nothing; import from the modules below.", ""]
    for section in package.sections:
        lines += [f"## Module `{section.module}`", ""]
        if section.summary:
            lines += [section.summary, ""]
        lines += [f"Import with `from {section.module} import <name>`.", ""]
        for entry in section.entries:
            lines += render_entry(entry, "###")
    return "\n".join(lines).rstrip("\n") + "\n"


def render_entry(entry: Entry, heading: str) -> list[str]:
    lines = [f"{heading} `{entry.name}`", "", f"{entry.kind} · defined in `{entry.defined_in}`", ""]
    lines += ["```python", entry.signature, "```", ""]
    if entry.summary:
        lines += [entry.summary, ""]
    if entry.constructor:
        lines += ["Constructor:", "", "```python", entry.constructor, "```", ""]
    if entry.members:
        lines += ["Members:", ""]
        for member in entry.members:
            summary = f" — {member.summary}" if member.summary else ""
            lines.append(f"- `{member.signature}`{summary}")
        lines.append("")
    return lines


def render(root: Path) -> dict[Path, str]:
    """Every page of the index, keyed by its path relative to ``root``."""
    packages = collect(root)
    pages = {OUTPUT / "README.md": render_readme(packages)}
    for package in packages:
        pages[OUTPUT / f"{package.name}.md"] = render_package(package)
    return pages


def stale_pages(root: Path, pages: dict[Path, str]) -> list[str]:
    """Paths that differ from what the source generates, including pages that should not exist."""
    problems = [str(path) for path, text in pages.items() if not (root / path).is_file() or (root / path).read_text(encoding="utf-8") != text]
    directory = root / OUTPUT
    if directory.is_dir():
        problems += [str(path.relative_to(root)) for path in sorted(directory.glob("*.md")) if path.relative_to(root) not in pages]
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--write", action="store_true", help="regenerate the index pages")
    args = parser.parse_args()
    root: Path = args.root
    pages = render(root)
    if args.write:
        directory = root / OUTPUT
        directory.mkdir(parents=True, exist_ok=True)
        for path in directory.glob("*.md"):
            if path.relative_to(root) not in pages:
                path.unlink()
        for path, text in pages.items():
            (root / path).write_text(text, encoding="utf-8")
        print(f"API index written: {len(pages) - 1} packages under {OUTPUT}.")
        return 0
    stale = stale_pages(root, pages)
    if stale:
        print(f"API index is out of date; run `python {GENERATOR} --write`:", file=sys.stderr)
        for path in stale:
            print(f"  {path}", file=sys.stderr)
        return 1
    print(f"API index is current: {len(pages) - 1} packages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
