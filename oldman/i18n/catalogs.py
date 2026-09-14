"""Runtime-independent Babel catalog loading."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from babel.support import Translations


class CatalogLoader:
    """Load and merge gettext catalogs from explicit high-to-low priority roots."""

    def __init__(
        self,
        roots: Iterable[str | Path],
        *,
        domains: Iterable[str] = ("messages", "countries"),
    ) -> None:
        """Freeze unique roots and domains while preserving caller order."""
        self.roots = tuple(dict.fromkeys(Path(root).expanduser().resolve(strict=False) for root in roots))
        self.domains = tuple(dict.fromkeys(str(domain) for domain in domains if str(domain)))

    def load(self, locale: str) -> Translations:
        """Load one locale, allowing higher-priority roots to override lower ones."""
        catalog: Translations | None = None

        # ``Translations.merge`` lets the incoming catalog win, so load roots
        # from lowest to highest priority.
        for root in reversed(self.roots):
            for domain in self.domains:
                loaded = Translations.load(
                    root,
                    locales=[locale],
                    domain=domain,
                )
                if not isinstance(loaded, Translations):
                    continue
                if catalog is None:
                    catalog = loaded
                else:
                    catalog.merge(loaded)

        return catalog if catalog is not None else Translations()


__all__ = ["CatalogLoader"]
