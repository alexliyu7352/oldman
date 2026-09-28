#!/usr/bin/env python3
"""Assemble the documentation site's content trees from `docs/public/<language>/`.

The repository keeps one directory per language, so both are readable on GitHub at a
sane path. Docusaurus wants something else: one directory for the default locale and
one `i18n/<locale>/docusaurus-plugin-content-docs/current/` per other locale. This
script is the adapter, and it is the only place that knows Docusaurus' shape — the
repository layout never has to follow it.

It also does the thing Docusaurus cannot do for us. Docusaurus falls back per file to
the default locale, but its relative `./x.md` and `../x.md` links do **not** follow
that fallback (facebook/docusaurus#10907, still open), so a page that links across the
translated/untranslated boundary breaks the build. Both staged trees are therefore
**complete**: each locale's own file when it exists, the other language's file when it
does not. No boundary exists, so no link can cross one.

Usage:
    build-docs-site.py check     report gaps and stale translations; exit 1 if any
    build-docs-site.py stage     assemble the staged trees
    build-docs-site.py           stage, reporting gaps without failing
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DOCS = ROOT / "docs" / "public"
WEBSITE = ROOT / "website"

#: Repository directory name -> Docusaurus locale. The repository uses language codes;
#: Docusaurus wants its own locale spelling, and only this map knows the difference.
LANGUAGES = {"en": "en", "zh": "zh-Hans"}
#: The locale served without a URL prefix. English first, per the site's audience.
DEFAULT_LANGUAGE = "en"
#: Language a missing file falls back to. Documents are authored in Chinese and
#: translated, so an untranslated page shows Chinese rather than disappearing.
FALLBACK_LANGUAGE = "zh"


def staged_root(language: str) -> Path:
    """Where Docusaurus expects this language's Markdown to be."""
    if language == DEFAULT_LANGUAGE:
        return WEBSITE / ".staging" / language
    return WEBSITE / "i18n" / LANGUAGES[language] / "docusaurus-plugin-content-docs" / "current"


def source_files(language: str) -> dict[str, Path]:
    """Every Markdown file of one language, keyed by its path relative to that language."""
    base = PUBLIC_DOCS / language
    if not base.is_dir():
        return {}
    return {str(path.relative_to(base)): path for path in sorted(base.rglob("*.md"))}


def git_timestamp(path: Path) -> int:
    """Commit time of the file's last change, or 0 when git does not know it yet."""
    result = subprocess.run(
        ["git", "log", "-1", "--format=%ct", "--", str(path.relative_to(ROOT))],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return int(result.stdout.strip() or 0)


def report(languages: dict[str, dict[str, Path]]) -> list[str]:
    """Describe what a reader of the non-authoring languages would not get.

    Two different gaps, and they fail differently: a missing translation is visible
    (the page shows the other language), a stale one is not (it reads as current).
    """
    problems: list[str] = []
    source = languages[FALLBACK_LANGUAGE]

    for language, files in languages.items():
        if language == FALLBACK_LANGUAGE:
            continue
        missing = sorted(set(source) - set(files))
        for name in missing:
            problems.append(f"missing  {language}/{name}")

        for name in sorted(set(source) & set(files)):
            if git_timestamp(source[name]) > git_timestamp(files[name]):
                problems.append(f"stale    {language}/{name}  ({FALLBACK_LANGUAGE} changed later)")

    extra = sorted(set().union(*(set(f) for f in languages.values())) - set(source))
    for name in extra:
        owner = next(lang for lang, files in languages.items() if name in files)
        problems.append(f"note     {owner}/{name} has no {FALLBACK_LANGUAGE} counterpart")

    return problems


def stage(languages: dict[str, dict[str, Path]]) -> dict[str, int]:
    """Write one complete tree per language, filling gaps from the other languages."""
    every_name = sorted(set().union(*(set(files) for files in languages.values())))
    filled: dict[str, int] = {}

    for language in languages:
        destination = staged_root(language)
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True)
        borrowed = 0

        for name in every_name:
            source = languages[language].get(name)
            if source is None:
                # Prefer the authoring language, then anything that has the page at all.
                order = [FALLBACK_LANGUAGE, *(lang for lang in languages if lang != FALLBACK_LANGUAGE)]
                source = next((languages[lang][name] for lang in order if name in languages[lang]), None)
                if source is None:  # pragma: no cover - name came from the union
                    continue
                borrowed += 1
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

        filled[language] = borrowed

    return filled


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", nargs="?", default="build", choices=("check", "stage", "build"))
    arguments = parser.parse_args()

    languages = {language: source_files(language) for language in LANGUAGES}
    if not languages[FALLBACK_LANGUAGE]:
        print(f"error: {PUBLIC_DOCS / FALLBACK_LANGUAGE} has no Markdown files", file=sys.stderr)
        return 1

    problems = report(languages)
    for problem in problems:
        print(problem)
    counts = ", ".join(f"{language}={len(files)}" for language, files in sorted(languages.items()))
    print(f"source files: {counts}")

    if arguments.action == "check":
        return 1 if any(not p.startswith("note ") for p in problems) else 0

    filled = stage(languages)
    for language, borrowed in sorted(filled.items()):
        print(f"staged {language} -> {staged_root(language).relative_to(ROOT)} ({borrowed} filled from another language)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
