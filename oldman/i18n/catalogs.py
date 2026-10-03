"""Runtime-independent Babel catalog loading."""

from __future__ import annotations

from collections.abc import Iterable
from importlib.util import find_spec
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


def package_locale_root(package_name: str) -> Path | None:
    """One importable package's ``locales`` directory, found without importing the package; None when it has none."""
    spec = find_spec(package_name)
    if spec is None or not spec.submodule_search_locations:
        return None
    locale_root = Path(next(iter(spec.submodule_search_locations))) / "locales"
    return locale_root if locale_root.is_dir() else None


def translation_roots(project_root: Path, app_packages: Iterable[str]) -> tuple[Path, ...]:
    """Where a service looks up translations, highest priority first.

    The project's ``locales``, then each installed App's that has one, then the framework's own
    catalog (``oldman/locales``), which every framework message is in: a project that turns on a
    language the framework ships gets the framework's text in it without translating anything.
    """
    roots = [project_root / "locales"]
    for package_name in app_packages:
        locale_root = package_locale_root(package_name)
        if locale_root is not None:
            roots.append(locale_root)
    framework_root = package_locale_root("oldman")
    if framework_root is not None:
        roots.append(framework_root)
    return tuple(dict.fromkeys(roots))


__all__ = ["CatalogLoader", "package_locale_root", "translation_roots"]
