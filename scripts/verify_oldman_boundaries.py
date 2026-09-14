"""Oldman package boundary verifier."""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLDMAN_ROOT = ROOT / "oldman"

REQUIRED_FILES = (
    "oldman/__init__.py",
    "oldman/apps/config.py",
    "oldman/apps/registry.py",
    "oldman/apps/admin/apps.py",
    "oldman/auth/apps.py",
    "oldman/auth/models.py",
    "oldman/cli/__init__.py",
    "oldman/cli/discovery.py",
    "oldman/conf/__init__.py",
    "oldman/conf/manager.py",
    "oldman/conf/schemas.py",
    "oldman/runtime/__init__.py",
    "oldman/runtime/base.py",
    "oldman/runtime/bootstrap.py",
    "oldman/runtime/discovery.py",
    "oldman/runtime/simple.py",
    "oldman/runtime/web.py",
    "oldman/i18n/__init__.py",
    "oldman/i18n/registry.py",
    "oldman/i18n/translations.py",
    "oldman/cache/__init__.py",
    "oldman/cache/base.py",
    "oldman/cache/backends/memory.py",
    "oldman/cache/backends/redis.py",
    "oldman/db/__init__.py",
    "oldman/db/migrations/commands.py",
    "oldman/db/migrations/project.py",
    "oldman/db/models.py",
    "oldman/db/schemas.py",
    "oldman/db/services.py",
    "oldman/db/session.py",
    "oldman/processes/__init__.py",
    "oldman/providers/nats/__init__.py",
    "oldman/providers/redis/__init__.py",
    "oldman/storage/__init__.py",
    "oldman/tasks/__init__.py",
    "oldman/web/__init__.py",
    "oldman/web/request.py",
    "oldman/web/response.py",
    "oldman/web/session/__init__.py",
    "oldman/web/messages/__init__.py",
    "oldman/web/sse/__init__.py",
    "oldman/web/websocket/__init__.py",
    "oldman/web/template/__init__.py",
    "oldman/web/security/__init__.py",
    "oldman/web/security/csrf/__init__.py",
    "oldman/web/staticfiles/__init__.py",
    "oldman/web/components/forms/__init__.py",
    "oldman/web/components/tables/__init__.py",
    "oldman/web/components/selects/__init__.py",
    "oldman/web/components/charts/__init__.py",
    "oldman/serializers/__init__.py",
    "oldman/utils/__init__.py",
)
FORBIDDEN_MISPLACED_FILES = (
    "oldman/application",
    "oldman/admin",
    "oldman/messaging",
    "oldman/media",
    "oldman/conf/config.py",
    "oldman/web/csrf",
    "oldman/web/forms",
    "oldman/web/tables",
    "oldman/web/selects",
    "oldman/web/charts",
    "oldman/web/permissions.py",
    "oldman/web/runtime/middlewares",
)
FORBIDDEN_CONSUMER_PREFIXES = ("apps", "services", "config")
LAYER_IMPORT_RULES = (
    (
        "oldman/core/",
        ("aiocache", "oldman.admin", "oldman.cache", "oldman.web", "redis", "sanic", "sanic_ext"),
    ),
    (
        "oldman/conf/",
        ("aiocache", "oldman.admin", "oldman.cache", "oldman.web", "redis", "sanic", "sanic_ext"),
    ),
    (
        "oldman/i18n/",
        ("aiocache", "oldman.admin", "oldman.cache", "oldman.web", "redis", "sanic", "sanic_ext"),
    ),
    (
        "oldman/utils/",
        ("PIL", "aiocache", "oldman.admin", "oldman.cache", "oldman.media", "oldman.web", "redis", "sanic", "sanic_ext"),
    ),
)
IMPORT_SIDE_EFFECT_CALLS = {
    "connect",
    "create_engine",
    "create_async_engine",
    "from_url",
    "run",
    "serve",
    "start",
}
IMPORT_SIDE_EFFECT_NAMES = {
    "Redis",
    "FastStream",
    "NatsBroker",
    "Sanic",
}


@dataclass(frozen=True)
class PythonFile:
    path: Path
    tree: ast.Module

    @property
    def rel(self) -> str:
        return self.path.relative_to(ROOT).as_posix()

    @property
    def package(self) -> str:
        """Return the containing Python package used to resolve relative imports."""
        return ".".join(self.path.parent.relative_to(ROOT).parts)


def iter_python_files() -> list[PythonFile]:
    files: list[PythonFile] = []
    for path in sorted(OLDMAN_ROOT.rglob("*.py")):
        files.append(PythonFile(path=path, tree=ast.parse(path.read_text(encoding="utf-8"), filename=str(path))))
    return files


def resolve_import_from(node: ast.ImportFrom, package: str | None) -> str | None:
    """Resolve an ImportFrom module without confusing relative and consumer roots."""
    if node.level == 0:
        return node.module
    if not package:
        return None
    package_parts = package.split(".")
    parent_count = node.level - 1
    if parent_count >= len(package_parts):
        return None
    base_parts = package_parts[: len(package_parts) - parent_count]
    if node.module:
        base_parts.extend(node.module.split("."))
    return ".".join(base_parts)


def imported_modules(tree: ast.Module, *, package: str | None = None) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = resolve_import_from(node, package)
            if module:
                modules.add(module)
    return modules


def top_level_imports(tree: ast.Module, *, package: str | None = None) -> set[str]:
    modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = resolve_import_from(node, package)
            if module:
                modules.add(module)
    return modules


def call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def top_level_calls(tree: ast.Module) -> set[str]:
    calls: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                calls.add(call_name(child))
    return calls


def module_has_prefix(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def validate_boundaries() -> list[str]:
    errors: list[str] = []
    for rel_path in REQUIRED_FILES:
        if not (ROOT / rel_path).is_file():
            errors.append(f"Missing required skeleton file: {rel_path}")
    for rel_path in FORBIDDEN_MISPLACED_FILES:
        if (ROOT / rel_path).exists():
            errors.append(f"Misplaced implementation is forbidden: {rel_path}")

    if (OLDMAN_ROOT / "dashboard").exists():
        errors.append("oldman.dashboard Python package is forbidden")

    cli_discovery = (OLDMAN_ROOT / "cli" / "discovery.py").read_text(encoding="utf-8")
    if "oldman.cli._service_discovery" not in cli_discovery:
        errors.append("oldman.cli discovery must delegate to the canonical cold discovery implementation")
    if "importlib" in cli_discovery or "pkgutil" in cli_discovery:
        errors.append("oldman.cli discovery must not implement a second module scanner")
    if "manifest" in cli_discovery.lower():
        errors.append("oldman.cli discovery must not require a service manifest")
    if "blueprint" in cli_discovery.lower():
        errors.append("Web blueprint discovery must not be exposed by the public oldman.cli adapter")

    runtime_init = (OLDMAN_ROOT / "runtime" / "__init__.py").read_text(encoding="utf-8")
    if '"Sanic' in runtime_init:
        errors.append("oldman.runtime.__init__ must not expose Sanic-named classes")

    for python_file in iter_python_files():
        source = python_file.path.read_text(encoding="utf-8")
        if "oldman.dashboard" in source:
            errors.append(f"{python_file.rel} imports forbidden oldman.dashboard")

        modules = imported_modules(python_file.tree, package=python_file.package)
        for module in modules:
            if any(module_has_prefix(module, prefix) for prefix in FORBIDDEN_CONSUMER_PREFIXES):
                errors.append(f"{python_file.rel} imports consumer module {module}")
            if python_file.rel.startswith("oldman/web/") and module_has_prefix(module, "oldman.admin"):
                errors.append(f"{python_file.rel} imports oldman.admin from oldman.web")
            if python_file.rel.startswith("oldman/messaging/") and (
                module_has_prefix(module, "oldman.web") or module_has_prefix(module, "oldman.admin")
            ):
                errors.append(f"{python_file.rel} imports forbidden messaging dependency {module}")
            if python_file.rel.startswith("oldman/tasks/") and (
                module_has_prefix(module, "oldman.web") or module_has_prefix(module, "oldman.admin")
            ):
                errors.append(f"{python_file.rel} imports forbidden task dependency {module}")
            for layer_prefix, forbidden_prefixes in LAYER_IMPORT_RULES:
                if python_file.rel.startswith(layer_prefix) and any(
                    module_has_prefix(module, prefix) for prefix in forbidden_prefixes
                ):
                    errors.append(f"{python_file.rel} imports forbidden {layer_prefix.removesuffix('/')} dependency {module}")

        side_effects = top_level_calls(python_file.tree) & (IMPORT_SIDE_EFFECT_CALLS | IMPORT_SIDE_EFFECT_NAMES)
        if side_effects:
            errors.append(f"{python_file.rel} has import-time side-effect calls: {', '.join(sorted(side_effects))}")

    return errors


def main() -> int:
    errors = validate_boundaries()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Oldman package boundaries are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
