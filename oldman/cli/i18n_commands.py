"""Thin CLI delegation to the framework catalog operations."""

from __future__ import annotations

from pathlib import Path

from oldman.i18n import LanguageRegistry, gettext


def normalize_catalog_locale(language: str) -> tuple[str, str]:
    """Return canonical BCP 47 and Babel locale codes for one language."""
    registry = LanguageRegistry({language: {}})
    definition = next(iter(registry))
    return definition.code, definition.babel_locale


def extract_catalog() -> None:
    """Delegate catalog extraction to the i18n implementation."""
    from oldman.i18n.commands import extract

    extract()


def initialize_catalog(locale_name: str) -> None:
    """Delegate catalog initialization with a Babel locale identifier."""
    from oldman.i18n.commands import init

    init(locale_name)


def update_catalogs() -> None:
    """Delegate catalog update to the i18n implementation."""
    from oldman.i18n.commands import update

    update()


def compile_catalogs() -> None:
    """Delegate catalog compilation to the i18n implementation."""
    from oldman.i18n.commands import compile_translations

    compile_translations()


__all__ = [
    "compile_catalogs",
    "extract_catalog",
    "initialize_catalog",
    "normalize_catalog_locale",
    "update_catalogs",
]


def build_frontend_catalogs(
    *,
    project_root: Path,
    service: str,
    settings_file: Path | None = None,
    locales_dir: Path | None = None,
    output_dir: Path | None = None,
    languages_output: Path | None = None,
) -> None:
    """Delegate the browser catalog and manifest build to the i18n implementation.

    The service settings name the languages, so a missing settings file is a wiring mistake
    worth one clear sentence: the build would otherwise fail deep inside the YAML read.
    """
    from oldman.web.i18n.frontend_build import build_frontend_i18n, project_frontend_paths

    paths = project_frontend_paths(project_root, service=service)
    resolved_settings = settings_file if settings_file is not None else paths["settings_file"]
    if not resolved_settings.is_file():
        raise ValueError(
            gettext(
                "Settings file %(path)s does not exist; create it or pass another service with --service.",
                path=str(resolved_settings),
            )
        )
    build_frontend_i18n(
        output_dir if output_dir is not None else paths["output_dir"],
        locales_dir if locales_dir is not None else paths["locales_dir"],
        resolved_settings,
        languages_output if languages_output is not None else paths["languages_output"],
        project_root=project_root,
    )
