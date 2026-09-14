#!/usr/bin/env python3
"""Verify the repository and oldman-web ownership boundaries."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_PACKAGE_ROOT = ROOT / "frontend" / "packages" / "oldman-web"
ADMIN_APP_ROOT = ROOT / "frontend" / "apps" / "admin"


@dataclass(frozen=True)
class BoundaryEntry:
    """A stable top-level ownership boundary."""

    path: str
    owner: str
    published_as: str


BOUNDARIES = (
    BoundaryEntry("oldman/", "Python 框架", "PyPI 包 oldman"),
    BoundaryEntry("frontend/packages/oldman-web/", "浏览器框架", "npm 包 oldman-web"),
    BoundaryEntry("frontend/apps/admin/", "内置 Admin 前端", "编译进 oldman wheel"),
    BoundaryEntry("tests/", "框架测试", "不发布"),
    BoundaryEntry("scripts/", "框架开发与发布门禁", "不发布"),
)

FORBIDDEN_ROOT_PATHS = (
    "apps",
    "config",
    "core",
    "services",
    "templates",
    "main.py",
    "frontend/src",
    "frontend/package.json",
    "frontend/packages/ui",
)

FORBIDDEN_WEB_TOKENS = (
    "@app/",
    "DashboardOverview",
    "NotificationsCenter",
    "programme-trend-chart",
    "feed-status-chart",
    "logo-quality-chart",
    "channels-epg",
    "match-decisions",
    "logo-assets",
    "component-coverage",
)

def source_files(root: Path) -> list[Path]:
    """Return production frontend source files below *root*."""
    suffixes = {".css", ".js", ".jsx", ".scss", ".ts", ".tsx"}
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in suffixes
        and not any(part in {"__tests__", "test", "tests"} for part in path.relative_to(root).parts[:-1])
        and not any(path.name.endswith(f".{marker}{suffix}") for marker in ("test", "spec") for suffix in suffixes)
    )


def verify_repository_boundaries() -> list[str]:
    """Verify filesystem ownership and consumer import rules."""
    errors: list[str] = []

    for entry in BOUNDARIES:
        if not (ROOT / entry.path).exists():
            errors.append(f"缺少边界目录: {entry.path}")

    for relative_path in FORBIDDEN_ROOT_PATHS:
        if (ROOT / relative_path).exists():
            errors.append(f"仓库根仍包含旧业务/重复路径: {relative_path}")

    package_json_path = WEB_PACKAGE_ROOT / "package.json"
    if not package_json_path.exists():
        errors.append("缺少 frontend/packages/oldman-web/package.json")
    else:
        package_json = json.loads(package_json_path.read_text(encoding="utf-8"))
        if package_json.get("name") != "oldman-web":
            errors.append("可发布 npm 包必须命名为 oldman-web")
        if package_json.get("private") is True:
            errors.append("oldman-web 不能标记为 private")

    for path in source_files(WEB_PACKAGE_ROOT / "src"):
        source = path.read_text(encoding="utf-8", errors="ignore")
        for token in FORBIDDEN_WEB_TOKENS:
            if token in source:
                errors.append(f"{path.relative_to(ROOT)} 包含业务边界标识 {token}")

    for path in source_files(ADMIN_APP_ROOT / "src"):
        source = path.read_text(encoding="utf-8", errors="ignore")
        if "frontend/packages/oldman-web" in source or "../../../packages/oldman-web" in source:
            errors.append(f"{path.relative_to(ROOT)} 绕过 oldman-web 公开入口")
        if "@oldman/" in source:
            errors.append(f"{path.relative_to(ROOT)} 仍使用旧 @oldman/* 别名")

    return errors


def main() -> int:
    """Run the boundary verifier."""
    if len(sys.argv) != 1:
        print("This verifier is read-only and accepts no arguments.", file=sys.stderr)
        return 2

    errors = verify_repository_boundaries()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Oldman repository and oldman-web boundaries are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
