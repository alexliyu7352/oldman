"""把“这段代码在别处已经有了”变成一条测试，而不是靠人记得。

三种最常见的重复各有一个检查：

* `duplicate_functions()`：两棵源码树里同名且函数体结构相同的函数。复制粘贴通常保留函数名，所以
  同名 + 归一化后的 AST 相同，误报很少。
* `identical_files()`：内容逐字节相同的文件（复制过来的脚本、模板、类型声明）。
* `forbidden_imports()` / `forbidden_attributes()`：绕过公开 API 的写法，例如从 `oldman.apps.admin`
  里 import 与 Admin 业务无关的东西，或者直接摸 `app.ext.environment`。

只读源码，不导入被检查的模块，所以对任何仓库都安全；语法错误或者不是 UTF-8 的文件直接跳过，
守卫的职责是报告重复，不是替别人的编码决定。

它抓的是"真复制"：同名同结构的函数、逐字节相同的文件。改过名字的副本（同一段逻辑换个函数名和局部
变量名）抓不到，靠的是评审时逐条比对差异，不能因为守卫是绿的就认为没有重复。
"""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        ".worktrees",
        "__pycache__",
        "build",
        "dist",
        "migrations",
        "node_modules",
        "site-packages",
    }
)


@dataclass(frozen=True, slots=True)
class DuplicateFunction:
    """同一个函数名在两棵源码树里有结构相同的实现。"""

    name: str
    left: Path
    right: Path
    lines: int

    def describe(self, *, left_root: Path | None = None, right_root: Path | None = None) -> str:
        """一行可读描述，供断言失败时直接打印。"""
        left = self.left.relative_to(left_root) if left_root else self.left
        right = self.right.relative_to(right_root) if right_root else self.right
        return f"{self.name} ({self.lines} lines): {left} == {right}"


@dataclass(frozen=True, slots=True)
class IdenticalFile:
    """两棵源码树里内容完全相同的文件。"""

    left: Path
    right: Path

    def describe(self, *, left_root: Path | None = None, right_root: Path | None = None) -> str:
        left = self.left.relative_to(left_root) if left_root else self.left
        right = self.right.relative_to(right_root) if right_root else self.right
        return f"{left} == {right}"


@dataclass(frozen=True, slots=True)
class SourceReference:
    """一处不该出现的 import 或属性访问。"""

    path: Path
    line: int
    text: str

    def describe(self, *, root: Path | None = None) -> str:
        path = self.path.relative_to(root) if root else self.path
        return f"{path}:{self.line}: {self.text}"


def iter_python_files(root: Path, *, exclude_directories: Iterable[str] = ()) -> Iterator[Path]:
    """遍历一棵源码树里的 .py 文件，跳过缓存、虚拟环境和迁移目录。"""
    excluded = DEFAULT_EXCLUDED_DIRECTORIES | set(exclude_directories)
    for path in sorted(root.rglob("*.py")):
        if any(part in excluded for part in path.relative_to(root).parts):
            continue
        yield path


def _function_digest(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """函数体的结构指纹：去掉 docstring 和位置信息后的 AST。"""
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    dumped = "\n".join(ast.dump(statement, annotate_fields=False, include_attributes=False) for statement in body)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def function_digests(
    root: Path,
    *,
    min_lines: int = 6,
    exclude_names: Sequence[str] = (),
    exclude_directories: Iterable[str] = (),
) -> dict[tuple[str, str], list[tuple[Path, int]]]:
    """一棵源码树里每个够长的函数的 (名字, 指纹) → 出现位置。"""
    excluded_names = set(exclude_names)
    digests: dict[tuple[str, str], list[tuple[Path, int]]] = {}
    for path in iter_python_files(root, exclude_directories=exclude_directories):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name in excluded_names:
                continue
            lines = (node.end_lineno or node.lineno) - node.lineno + 1
            if lines < min_lines:
                continue
            digests.setdefault((node.name, _function_digest(node)), []).append((path, lines))
    return digests


def duplicate_functions(
    left_root: Path,
    right_root: Path,
    *,
    min_lines: int = 6,
    exclude_names: Sequence[str] = (),
    exclude_directories: Iterable[str] = (),
) -> list[DuplicateFunction]:
    """两棵源码树里同名且结构相同的函数。"""
    left = function_digests(left_root, min_lines=min_lines, exclude_names=exclude_names, exclude_directories=exclude_directories)
    right = function_digests(right_root, min_lines=min_lines, exclude_names=exclude_names, exclude_directories=exclude_directories)
    duplicates: list[DuplicateFunction] = []
    for key, left_hits in left.items():
        right_hits = right.get(key)
        if not right_hits:
            continue
        name, _digest = key
        left_path, lines = left_hits[0]
        right_path, _right_lines = right_hits[0]
        duplicates.append(DuplicateFunction(name=name, left=left_path, right=right_path, lines=lines))
    return sorted(duplicates, key=lambda item: (-item.lines, item.name))


def identical_files(
    left_root: Path,
    right_root: Path,
    *,
    suffixes: Sequence[str] = (".py", ".ts", ".html"),
    exclude_directories: Iterable[str] = (),
    min_bytes: int = 200,
) -> list[IdenticalFile]:
    """两棵源码树里内容逐字节相同的文件（按同名文件比对）。"""
    excluded = DEFAULT_EXCLUDED_DIRECTORIES | set(exclude_directories)

    def collect(root: Path) -> dict[str, list[tuple[Path, str]]]:
        found: dict[str, list[tuple[Path, str]]] = {}
        for suffix in suffixes:
            for path in sorted(root.rglob(f"*{suffix}")):
                if any(part in excluded for part in path.relative_to(root).parts):
                    continue
                data = path.read_bytes()
                if len(data) < min_bytes:
                    continue
                found.setdefault(path.name, []).append((path, hashlib.sha256(data).hexdigest()))
        return found

    left = collect(left_root)
    right = collect(right_root)
    matches: list[IdenticalFile] = []
    for name, left_entries in left.items():
        for left_path, left_digest in left_entries:
            for right_path, right_digest in right.get(name, ()):
                if left_digest == right_digest:
                    matches.append(IdenticalFile(left=left_path, right=right_path))
    return sorted(matches, key=lambda item: str(item.left))


def forbidden_imports(
    root: Path,
    *,
    modules: Sequence[str],
    allowed_names: Sequence[str] = (),
    exclude_directories: Iterable[str] = (),
) -> list[SourceReference]:
    """找出从指定模块（前缀匹配）导入的地方，`allowed_names` 里的名字放行。"""
    allowed = set(allowed_names)
    references: list[SourceReference] = []
    for path in iter_python_files(root, exclude_directories=exclude_directories):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if not any(node.module == module or node.module.startswith(f"{module}.") for module in modules):
                    continue
                names = [alias.name for alias in node.names if alias.name not in allowed]
                if names:
                    references.append(SourceReference(path=path, line=node.lineno, text=f"from {node.module} import {', '.join(names)}"))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if any(alias.name == module or alias.name.startswith(f"{module}.") for module in modules) and alias.name not in allowed:
                        references.append(SourceReference(path=path, line=node.lineno, text=f"import {alias.name}"))
    return references


def forbidden_attributes(
    root: Path,
    *,
    attributes: Sequence[str],
    exclude_directories: Iterable[str] = (),
) -> list[SourceReference]:
    """找出形如 `a.b.c` 的属性访问链，用来挡住绕开公开入口的写法。"""
    wanted = {tuple(attribute.split(".")): attribute for attribute in attributes}
    references: list[SourceReference] = []
    for path in iter_python_files(root, exclude_directories=exclude_directories):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            chain = _attribute_chain(node)
            if chain is None:
                continue
            for parts, attribute in wanted.items():
                if len(chain) >= len(parts) and tuple(chain[-len(parts):]) == parts:
                    references.append(SourceReference(path=path, line=node.lineno, text=attribute))
                    break
    return references


def _attribute_chain(node: ast.Attribute) -> list[str] | None:
    """`a.b.c` → ["a", "b", "c"]；中间出现调用或下标时返回 None。"""
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return list(reversed(parts))
    return None


__all__ = [
    "DEFAULT_EXCLUDED_DIRECTORIES",
    "DuplicateFunction",
    "IdenticalFile",
    "SourceReference",
    "duplicate_functions",
    "forbidden_attributes",
    "forbidden_imports",
    "function_digests",
    "identical_files",
    "iter_python_files",
]
