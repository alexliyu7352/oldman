"""Published browser i18n assets: language flags, and the catalogs the frontend expects."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Final
from urllib.parse import urlparse

import oldman.conf as conf
from oldman.i18n import LanguageRegistry
from oldman.logging import logger
from oldman.web.staticfiles import oldman_asset_path, static_asset_url
from oldman.web.staticfiles.bundles import StaticBundleRegistry

BUILTIN_FLAG_ASSETS: Final = MappingProxyType(
    {
        "cn": oldman_asset_path("images/flags/cn.svg"),
        "tw": oldman_asset_path("images/flags/tw.svg"),
        "us": oldman_asset_path("images/flags/us.svg"),
    }
)


def direct_flag_url(value: str, *, static_url: str) -> str:
    """Resolve one language flag against the configured public static prefix."""
    normalized = value.strip()
    if not normalized:
        return ""

    built_in = BUILTIN_FLAG_ASSETS.get(normalized.casefold())
    if built_in is not None:
        return static_asset_url(static_url, built_in)
    if normalized.startswith("/") or urlparse(normalized).scheme:
        return normalized
    return static_asset_url(static_url, normalized)


__all__ = ["BUILTIN_FLAG_ASSETS", "direct_flag_url"]


def ensure_frontend_catalogs(
    registry: StaticBundleRegistry,
    bundle_name: str,
    *,
    source_dir: Path | None = None,
) -> None:
    """Fail fast when a configured language has no published browser catalog.

    三份语言列表各有各的来源：切换器菜单来自 settings，后端文案来自编译好的 `.mo`，浏览器文案来自
    前端构建产物。只有第一份会在改完配置重启后立刻变化，于是菜单里会出现一种点下去没有翻译的语言。
    这里把它变成启动期的硬失败：配置里的每种语言都必须有一份已发布的目录。

    dev 模式下产物由 Vite 直接从源目录提供，框架看不到它；传了 `source_dir` 就对着源目录告警。
    """
    codes = [definition.code for definition in LanguageRegistry(conf.settings.i18n.languages)]
    if not codes:
        return

    bundle = registry.get(bundle_name)
    if bundle.dev_mode:
        if source_dir is not None:
            missing = _missing_catalogs(source_dir, codes)
            if missing:
                logger.warning(
                    "Frontend catalogs missing for %s in %s; run the frontend i18n build",
                    ", ".join(missing),
                    source_dir,
                )
        return

    catalogs_dir = registry.asset_root(bundle_name) / "i18n"
    missing = _missing_catalogs(catalogs_dir, codes)
    if missing:
        raise RuntimeError(
            f"Frontend catalogs for {', '.join(missing)} are not published under {catalogs_dir}. "
            "Run `oldman i18n compile-frontend`, rebuild the frontend and collect static files before web start."
        )


def _missing_catalogs(catalogs_dir: Path, codes: list[str]) -> list[str]:
    """Return the configured codes without a catalog file in one directory."""
    return [code for code in codes if not (catalogs_dir / f"{code.lower()}.json").is_file()]
