"""Select provider 静态注册表。"""

from __future__ import annotations

from typing import TypeVar

ProviderT = TypeVar("ProviderT", bound=type)


class SelectRegistry:
    """保存 provider 名称到 Provider 类的轻量映射。"""

    def __init__(self) -> None:
        """初始化空注册表。"""
        self._providers: dict[str, type] = {}

    def register(self, name: str):
        """注册 provider 类，名称冲突时直接失败。"""
        normalized = name.strip()
        if not normalized:
            raise ValueError("Select provider name cannot be empty")

        def decorator(provider_cls: ProviderT) -> ProviderT:
            """把 provider 类写入注册表。"""
            if normalized in self._providers:
                raise ValueError(f"Select provider already registered: {normalized}")
            self._providers[normalized] = provider_cls
            return provider_cls

        return decorator

    def get(self, name: str) -> type | None:
        """按名称返回 provider 类。"""
        return self._providers.get(name)

    def names(self) -> tuple[str, ...]:
        """返回已注册 provider 名称，供门禁和调试使用。"""
        return tuple(sorted(self._providers))


select_registry = SelectRegistry()
