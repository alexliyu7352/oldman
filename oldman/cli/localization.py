"""CLI language selection backed by the shared Oldman i18n core."""

from __future__ import annotations

import importlib.util
import json
import locale
import os
import sys
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any, cast

from oldman.i18n import (
    CatalogLoader,
    LanguageRegistry,
    bind_translations,
    gettext,
    gettext_noop,
    reset_translations,
)

CLI_LANGUAGE_ENV = "OLDMAN_CLI_LANGUAGE"
CLI_LANGUAGE_CONFIG = Path("oldman/cli.json")
CLI_LANGUAGE_CODES = ("en", "zh-Hans", "zh-Hant")
CLI_LANGUAGE_REGISTRY = LanguageRegistry({code: {} for code in CLI_LANGUAGE_CODES})
_COMPLETION_OPTIONS = {"--install-completion", "--show-completion"}


@dataclass(frozen=True, slots=True)
class CliWarning:
    """One deferred warning translated after the CLI catalog is bound."""

    message: str
    variables: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CliLanguageState:
    """Resolved effective and persisted language values for one invocation."""

    effective: str
    saved: str | None
    source: str
    warnings: tuple[CliWarning, ...] = ()


def cli_config_path() -> Path:
    """Return the XDG path used only for CLI-local preferences."""
    configured_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    config_home = Path(configured_home).expanduser() if configured_home else Path.home() / ".config"
    return config_home / CLI_LANGUAGE_CONFIG


def read_saved_language(path: Path | None = None) -> tuple[str | None, tuple[CliWarning, ...]]:
    """Read and validate the canonical language stored in the CLI JSON file."""
    config_path = path or cli_config_path()
    if not config_path.exists():
        return None, ()

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, (
            CliWarning(
                gettext_noop("Ignoring invalid CLI language configuration: %(path)s"),
                {"path": config_path},
            ),
        )

    raw_language = payload.get("language") if isinstance(payload, dict) else None
    resolved = CLI_LANGUAGE_REGISTRY.resolve(raw_language) if isinstance(raw_language, str) else ""
    if not resolved:
        return None, (
            CliWarning(
                gettext_noop("Ignoring unsupported language in CLI configuration: %(path)s"),
                {"path": config_path},
            ),
        )
    return resolved, ()


def save_cli_language(language: str, path: Path | None = None) -> str:
    """Atomically persist one canonical CLI language and return its code."""
    resolved = CLI_LANGUAGE_REGISTRY.resolve(language)
    if not resolved:
        raise ValueError(language)

    config_path = path or cli_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=config_path.parent,
            prefix=f".{config_path.name}.",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump({"language": resolved}, temporary_file, ensure_ascii=False)
            temporary_file.write("\n")
        os.replace(temporary_path, config_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return resolved


def _system_language() -> str:
    """Resolve POSIX locale inputs through the shared language registry."""
    candidates: list[str] = []
    language_env = os.environ.get("LANGUAGE", "")
    if language_env:
        candidates.extend(language_env.split(":"))
    candidates.extend(os.environ.get(name, "") for name in ("LC_ALL", "LC_MESSAGES", "LANG"))
    current_locale = locale.getlocale()[0]
    if current_locale:
        candidates.append(current_locale)

    for candidate in candidates:
        normalized = candidate.strip().split(".", 1)[0].split("@", 1)[0]
        if not normalized or normalized.upper() in {"C", "POSIX"}:
            continue
        # POSIX locale identifiers use underscores; LanguageRegistry accepts
        # canonical BCP 47 codes, so adapt only this operating-system input.
        resolved = CLI_LANGUAGE_REGISTRY.resolve(normalized.replace("_", "-"))
        if resolved:
            return resolved
    return "en"


def _is_completion_invocation(args: list[str]) -> bool:
    """Return whether the invocation must remain non-interactive for completion."""
    if any(option in args for option in _COMPLETION_OPTIONS):
        return True
    return bool(os.environ.get("_OLDMAN_COMPLETE"))


def _should_prompt(args: list[str]) -> bool:
    """Return whether an unconfigured invocation may ask for a language."""
    if args[:1] == ["language"] or _is_completion_invocation(args):
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


def _prompt_for_language(default_language: str) -> str:
    """Prompt without depending on an already selected translation catalog."""
    definitions = tuple(CLI_LANGUAGE_REGISTRY)
    default_index = next(index for index, definition in enumerate(definitions, start=1) if definition.code == default_language)
    while True:
        print("Select CLI language / 请选择 CLI 语言 / 請選擇 CLI 語言")
        for index, definition in enumerate(definitions, start=1):
            print(f"{index}. {definition.name}")
        try:
            answer = input(f"[{default_index}]: ").strip()
        except EOFError:
            return default_language
        if not answer:
            return default_language
        if answer.isdigit():
            selected_index = int(answer)
            if 1 <= selected_index <= len(definitions):
                return definitions[selected_index - 1].code
        resolved = CLI_LANGUAGE_REGISTRY.resolve(answer)
        if resolved:
            return resolved
        print("Invalid selection / 无效选择 / 無效選擇", file=sys.stderr)


def resolve_cli_language(args: list[str]) -> CliLanguageState:
    """Resolve environment, saved, prompt, and system language precedence."""
    saved, saved_warnings = read_saved_language()
    warnings = list(saved_warnings)

    environment_language = os.environ.get(CLI_LANGUAGE_ENV, "").strip()
    if environment_language:
        resolved_environment = CLI_LANGUAGE_REGISTRY.resolve(environment_language)
        if resolved_environment:
            return CliLanguageState(
                effective=resolved_environment,
                saved=saved,
                source="environment",
                warnings=tuple(warnings),
            )
        warnings.append(
            CliWarning(
                gettext_noop("Ignoring unsupported %(variable)s value: %(language)s"),
                {
                    "variable": CLI_LANGUAGE_ENV,
                    "language": environment_language,
                },
            )
        )

    if saved:
        return CliLanguageState(
            effective=saved,
            saved=saved,
            source="saved",
            warnings=tuple(warnings),
        )

    system_language = _system_language()
    if not _should_prompt(args):
        return CliLanguageState(
            effective=system_language,
            saved=None,
            source="system",
            warnings=tuple(warnings),
        )

    selected = _prompt_for_language(system_language)
    try:
        saved_selection = save_cli_language(selected)
    except OSError:
        warnings.append(
            CliWarning(
                gettext_noop("Could not save the CLI language to %(path)s; using it for this invocation only."),
                {"path": cli_config_path()},
            )
        )
        saved_selection = None
    return CliLanguageState(
        effective=selected,
        saved=saved_selection,
        source="prompt",
        warnings=tuple(warnings),
    )


def _package_locale_root(package_name: str) -> Path | None:
    """Return one installed package's locale directory without importing it."""
    spec = importlib.util.find_spec(package_name)
    if spec is None or not spec.submodule_search_locations:
        return None
    locale_root = Path(next(iter(spec.submodule_search_locations))) / "locales"
    return locale_root if locale_root.is_dir() else None


@contextmanager
def use_cli_language(
    language: str,
    *,
    app_packages: Iterable[str] = (),
) -> Iterator[None]:
    """Bind the project, installed-App and framework ``messages`` catalogs."""
    definition = CLI_LANGUAGE_REGISTRY.definition(language)
    locale_name = definition.babel_locale
    from oldman.conf.constants import _find_project_root

    roots = [_find_project_root() / "locales"]
    for package_name in app_packages:
        locale_root = _package_locale_root(package_name)
        if locale_root is not None:
            roots.append(locale_root)

    locales_resource = files("oldman.cli").joinpath("locales")
    with as_file(locales_resource) as locales_root:
        roots.append(locales_root)
        catalog = CatalogLoader(
            roots,
            domains=("messages",),
        ).load(locale_name)
    # Babel's runtime object satisfies the protocol; its stubs use different
    # parameter names and an overly broad pgettext return type.
    token = bind_translations(cast(Any, catalog))
    try:
        yield
    finally:
        reset_translations(token)


@contextmanager
def cli_translation_context(args: list[str]) -> Iterator[CliLanguageState]:
    """Resolve, bind, report warnings, and finally reset one CLI invocation."""
    state = resolve_cli_language(args)
    with use_cli_language(state.effective):
        for warning in state.warnings:
            print(
                gettext(warning.message, **dict(warning.variables)),
                file=sys.stderr,
            )
        yield state


__all__ = [
    "CLI_LANGUAGE_CODES",
    "CLI_LANGUAGE_ENV",
    "CLI_LANGUAGE_REGISTRY",
    "CliLanguageState",
    "cli_config_path",
    "cli_translation_context",
    "read_saved_language",
    "resolve_cli_language",
    "save_cli_language",
    "use_cli_language",
]
