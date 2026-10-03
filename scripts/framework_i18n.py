#!/usr/bin/env python3
"""Maintain the framework's own translation catalog in ``oldman/locales``.

The catalog holds every message the framework ships: its Python and templates (Admin, auth,
web, roles, notifications, the CLI and the migration commands, as ``oldman/i18n/framework-babel.cfg``
lists them) and ``oldman-web``'s frontend messages. It is the last place a service looks a message
up, after the project's own catalog and those of the Apps it installs, so a project that turns on
i18n with only Chinese configured shows the framework's text in Chinese. Browser catalogs take
the frontend messages from it the same way; they never carry the rest.

The template is built by the same extraction a project's ``i18n extract`` uses for the framework's
half, so the two can never cover different messages. Locations are written without line numbers:
moving code does not make the catalog stale, only adding, changing or removing a message does.

Run from the framework root, in this order:

    .venv/bin/python scripts/framework_i18n.py update    # rebuild the template, merge it into each language
    # translate every new or fuzzy entry in oldman/locales/<language>/LC_MESSAGES/messages.po
    .venv/bin/python scripts/framework_i18n.py compile   # write the .mo files the wheel ships

``check`` (no changes) lists what is out of date; ``tests/test_oldman_framework_translations.py``
runs the same check in the test suite.
"""

from __future__ import annotations

import argparse
import sys
from io import BytesIO
from pathlib import Path

from babel.messages.catalog import Catalog
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po, write_po

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "oldman" / "locales"
TEMPLATE = LOCALES / "messages.pot"
LANGUAGES = ("zh_Hans", "zh_Hant")


def catalog_path(language: str, suffix: str) -> Path:
    """One language's ``messages.po`` or ``messages.mo``."""
    return LOCALES / language / "LC_MESSAGES" / f"messages.{suffix}"


def template_bytes(template: Catalog) -> bytes:
    """The template as committed: no header (its dates would change every run) and no line numbers."""
    buffer = BytesIO()
    write_po(buffer, template, omit_header=True, include_lineno=False)
    return buffer.getvalue()


def catalog_bytes(catalog: Catalog) -> bytes:
    """One language's catalog as committed: no line numbers, no obsolete entries."""
    buffer = BytesIO()
    write_po(buffer, catalog, include_lineno=False, ignore_obsolete=True)
    return buffer.getvalue()


def compiled_bytes(catalog: Catalog) -> bytes:
    """The ``.mo`` a language's catalog compiles to; fuzzy entries are left out, as gettext would."""
    buffer = BytesIO()
    write_mo(buffer, catalog, use_fuzzy=False)
    return buffer.getvalue()


def build_template() -> Catalog:
    """Every message the framework ships, extracted from the source in this checkout."""
    from oldman.i18n.commands import framework_template

    return framework_template()


def read_catalog(path: Path, language: str | None = None) -> Catalog:
    with path.open("rb") as stream:
        return read_po(stream, locale=language)


def identities(catalog: Catalog) -> set[tuple[str | None, object]]:
    return {(message.context, message.id) for message in catalog if message.id}


def translated(message: object) -> bool:
    string = getattr(message, "string", "")
    return all(string) if isinstance(string, tuple) else bool(string)


def update() -> None:
    """Rebuild the template and merge it into every language; new and changed messages need translating."""
    template = build_template()
    TEMPLATE.parent.mkdir(parents=True, exist_ok=True)
    TEMPLATE.write_bytes(template_bytes(template))
    for language in LANGUAGES:
        path = catalog_path(language, "po")
        catalog = read_catalog(path, language) if path.exists() else Catalog(locale=language, project="oldman")
        # Similar new messages come back fuzzy with the old translation, for a translator to confirm.
        catalog.update(template, update_creation_date=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(catalog_bytes(catalog))


def compile_catalogs() -> None:
    """Write each language's ``.mo`` from its ``.po``."""
    for language in LANGUAGES:
        catalog_path(language, "mo").write_bytes(compiled_bytes(read_catalog(catalog_path(language, "po"), language)))


def problems() -> list[str]:
    """What is out of date: the template, an untranslated or fuzzy entry, a catalog or ``.mo`` not regenerated."""
    found: list[str] = []
    template = build_template()
    if not TEMPLATE.is_file() or TEMPLATE.read_bytes() != template_bytes(template):
        found.append(f"{TEMPLATE.relative_to(ROOT)} does not match the source; run `scripts/framework_i18n.py update`")
    expected = identities(template)
    for language in LANGUAGES:
        po_path = catalog_path(language, "po")
        if not po_path.is_file():
            found.append(f"{po_path.relative_to(ROOT)} is missing; run `scripts/framework_i18n.py update`")
            continue
        catalog = read_catalog(po_path, language)
        if po_path.read_bytes() != catalog_bytes(catalog) or identities(catalog) != expected:
            found.append(f"{po_path.relative_to(ROOT)} does not match the template; run `scripts/framework_i18n.py update`")
        for message in catalog:
            if not message.id:
                continue
            if not translated(message):
                found.append(f"{po_path.relative_to(ROOT)}: not translated: {message.id!r}")
            elif message.fuzzy:
                found.append(f"{po_path.relative_to(ROOT)}: fuzzy, confirm the translation: {message.id!r}")
        mo_path = catalog_path(language, "mo")
        if not mo_path.is_file() or mo_path.read_bytes() != compiled_bytes(catalog):
            found.append(f"{mo_path.relative_to(ROOT)} does not match its .po; run `scripts/framework_i18n.py compile`")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Maintain the framework's own translation catalog in oldman/locales.")
    parser.add_argument("action", choices=("update", "compile", "check"))
    action = parser.parse_args().action
    if action == "update":
        update()
    elif action == "compile":
        compile_catalogs()
    else:
        found = problems()
        for problem in found:
            print(problem, file=sys.stderr)
        return 1 if found else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
