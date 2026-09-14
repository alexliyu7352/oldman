#!/usr/bin/env python3
"""Build browser catalogs from the project's unified gettext translations."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from ruamel.yaml import YAML

from oldman.conf.schemas import I18nConfig, StaticConfig
from oldman.i18n import LanguageRegistry
from oldman.i18n.frontend import compile_project_frontend_catalog
from oldman.web.i18n.assets import direct_flag_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_FILE = PROJECT_ROOT / "data" / "{{ service_name }}_settings.yaml"
LOCALES_DIR = PROJECT_ROOT / "locales"
OUTPUT_DIR = PROJECT_ROOT / "frontend" / "public" / "i18n"


def build_frontend_i18n() -> None:
    """Stage and atomically publish every configured browser catalog."""
    data = YAML(typ="safe", pure=True).load(
        SETTINGS_FILE.read_text(encoding="utf-8")
    ) or {}
    i18n = I18nConfig.model_validate(data.get("i18n") or {})
    web = data.get("web") or {}
    static = StaticConfig.model_validate(web.get("static") or {})
    registry = LanguageRegistry(i18n.languages)
    default_language = registry.resolve(i18n.default_language)
    if not default_language:
        raise ValueError(
            "i18n.default_language must resolve to one configured language"
        )

    OUTPUT_DIR.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        prefix=".oldman-frontend-i18n-",
        dir=OUTPUT_DIR.parent,
    ) as temporary_directory:
        temporary_root = Path(temporary_directory)
        staged = temporary_root / "i18n"
        staged.mkdir()
        languages: list[dict[str, object]] = []

        for definition in registry:
            filename = f"{definition.code.lower()}.json"
            po_file = (
                LOCALES_DIR
                / definition.babel_locale
                / "LC_MESSAGES"
                / "messages.po"
            )
            catalog = (
                compile_project_frontend_catalog(
                    PROJECT_ROOT,
                    po_file,
                    fallback_locale=definition.code,
                )
                if po_file.is_file()
                else {"locale": definition.code, "messages": {}}
            )
            catalog["locale"] = definition.code
            _write_json(staged / filename, catalog)
            languages.append(
                {
                    "aliases": list(definition.aliases),
                    "catalogPath": f"i18n/{filename}",
                    "code": definition.code,
                    "flag": definition.flag,
                    "flagUrl": direct_flag_url(
                        definition.flag,
                        static_url=static.url,
                    ),
                    "locale": definition.code,
                    "name": definition.name,
                }
            )

        _write_json(
            staged / "languages.json",
            {
                "defaultLanguage": default_language,
                "languages": languages,
            },
        )
        _publish(staged, OUTPUT_DIR, temporary_root / "previous-i18n")


def _write_json(path: Path, payload: object) -> None:
    """Write one deterministic UTF-8 JSON asset into the staging directory."""
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _publish(staged: Path, output: Path, backup: Path) -> None:
    """Replace the catalog set as one directory and restore it on failure."""
    had_previous = output.exists()
    if had_previous and not output.is_dir():
        raise RuntimeError(f"frontend i18n output is not a directory: {output}")
    if had_previous:
        output.replace(backup)
    try:
        staged.replace(output)
    except Exception:
        if output.exists():
            shutil.rmtree(output)
        if had_previous:
            backup.replace(output)
        raise


if __name__ == "__main__":
    build_frontend_i18n()
