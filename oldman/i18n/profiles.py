"""Built-in metadata for commonly configured languages."""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

BUILTIN_LANGUAGE_PROFILES: Final = MappingProxyType(
    {
        "en": MappingProxyType(
            {
                "aliases": ("en-US",),
                "name": "English",
                "flag": "",
            }
        ),
        "zh-Hans": MappingProxyType(
            {
                "aliases": ("zh-CN", "zh-SG"),
                "name": "简体中文",
                "flag": "",
            }
        ),
        "zh-Hant": MappingProxyType(
            {
                "aliases": ("zh-TW", "zh-HK"),
                "name": "繁體中文",
                "flag": "",
            }
        ),
    }
)


__all__ = ["BUILTIN_LANGUAGE_PROFILES"]
