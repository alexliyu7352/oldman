"""Packaged message metadata shared by Python and ``oldman-web``."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

_MANIFEST_PATH = "data/oldman_web_messages.json"
_CONTEXT_SEPARATOR = "\x04"
_PLURAL_RULE_PATTERN = re.compile(r"plural\s*=\s*([^;]+)")


@dataclass(frozen=True, slots=True)
class FrontendMessageLocation:
    """Repository-relative location of one frontend translation call."""

    path: str
    line: int


@dataclass(frozen=True, slots=True)
class FrontendMessage:
    """One unique frontend gettext identity and all of its source locations."""

    id: str
    context: str | None
    plural: str | None
    locations: tuple[FrontendMessageLocation, ...]

    @property
    def catalog_key(self) -> str:
        """Return the key used by the browser translation catalog."""
        if self.context is None:
            return self.id
        return f"{self.context}{_CONTEXT_SEPARATOR}{self.id}"

    @property
    def babel_id(self) -> str | tuple[str, str]:
        """Return the singular or plural ID accepted by Babel's Catalog."""
        if self.plural is None:
            return self.id
        return (self.id, self.plural)


@cache
def oldman_web_messages() -> tuple[FrontendMessage, ...]:
    """Load and validate the generated ``oldman-web`` message manifest."""
    resource = files("oldman.i18n").joinpath(_MANIFEST_PATH)
    payload = json.loads(resource.read_text(encoding="utf-8"))
    return frontend_messages_from_manifest(payload)


def frontend_messages_from_manifest(
    payload: object,
) -> tuple[FrontendMessage, ...]:
    """Validate one AST extractor manifest and return typed message identities."""
    if not isinstance(payload, Mapping) or payload.get("version") != 1:
        raise ValueError("frontend message manifest has an unsupported format")
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, list) or not all(
        isinstance(source, str) and source.strip()
        for source in raw_sources
    ):
        raise ValueError("frontend message manifest sources must be a string list")
    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, list):
        raise ValueError("frontend message manifest messages must be a list")

    messages = tuple(_load_message(raw_message) for raw_message in raw_messages)
    identities = [(message.context, message.id, message.plural) for message in messages]
    if len(identities) != len(set(identities)):
        raise ValueError("frontend message manifest contains duplicate identities")
    if identities != sorted(identities, key=_identity_sort_key):
        raise ValueError("frontend message manifest messages are not stably sorted")
    catalog_keys = [message.catalog_key for message in messages]
    if len(catalog_keys) != len(set(catalog_keys)):
        raise ValueError(
            "frontend message manifest contains incompatible singular/plural identities"
        )
    return messages


def extract_project_frontend_messages(
    project_root: Path,
    *,
    compiler_command: Sequence[str] | None = None,
) -> tuple[FrontendMessage, ...]:
    """Extract one project's ``frontend/src`` with the published AST tool."""
    project_root = project_root.resolve()
    source_root = project_root / "frontend" / "src"
    if not source_root.is_dir():
        return ()

    command = (
        tuple(compiler_command)
        if compiler_command is not None
        else _frontend_i18n_command(project_root)
    )
    completed = subprocess.run(
        [
            *command,
            "extract",
            "--project-root",
            str(project_root),
            "--source-root",
            str(source_root),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(
            f"oldman-web-i18n failed to extract frontend messages: {detail}"
        )
    try:
        payload = json.loads(completed.stdout)
        return frontend_messages_from_manifest(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            "oldman-web-i18n returned an invalid frontend message manifest."
        ) from exc


def compile_project_frontend_catalog(
    project_root: Path,
    po_file: Path,
    *,
    fallback_locale: str,
    compiler_command: Sequence[str] | None = None,
) -> dict[str, object]:
    """Compile and filter one project's browser catalog from ``messages.po``."""
    project_root = project_root.resolve()
    if not po_file.is_file():
        raise FileNotFoundError(f"Translation catalog does not exist: {po_file}")
    if not isinstance(fallback_locale, str) or not fallback_locale.strip():
        raise ValueError("fallback_locale must be a non-blank string")

    command = (
        tuple(compiler_command)
        if compiler_command is not None
        else _frontend_i18n_command(project_root)
    )
    messages = (
        *oldman_web_messages(),
        *extract_project_frontend_messages(
            project_root,
            compiler_command=command,
        ),
    )
    completed = subprocess.run(
        [*command, "compile-po", "--fallback-locale", fallback_locale],
        input=po_file.read_text(encoding="utf-8"),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(
            f"oldman-web-i18n failed to compile {po_file}: {detail}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "oldman-web-i18n returned an invalid browser catalog."
        ) from exc
    return filter_frontend_catalog_payload(payload, messages)


def filter_frontend_catalog_payload(
    payload: object,
    messages: Iterable[FrontendMessage],
) -> dict[str, object]:
    """Keep only AST-discovered identities in one compiled browser catalog."""
    if not isinstance(payload, Mapping):
        raise ValueError("frontend catalog payload must be an object")
    locale = _required_string(payload.get("locale"), "catalog locale")
    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, Mapping):
        raise ValueError("frontend catalog messages must be an object")
    compiled_messages = {
        _required_string(key, "catalog message key"): _catalog_value(value, key)
        for key, value in raw_messages.items()
    }
    frontend_keys = {message.catalog_key for message in messages}
    filtered_messages = {
        key: compiled_messages[key]
        for key in sorted(frontend_keys)
        if key in compiled_messages
    }
    filtered: dict[str, object] = {
        "locale": locale,
        "messages": filtered_messages,
    }
    plural_rule = payload.get("pluralRule")
    if plural_rule is not None:
        filtered["pluralRule"] = _required_string(
            plural_rule,
            "catalog pluralRule",
        )
    return filtered


def frontend_catalog_messages(catalog: Any) -> dict[str, str | list[str]]:
    """Translate all packaged frontend messages with one Babel catalog."""
    translated: dict[str, str | list[str]] = {}
    for message in oldman_web_messages():
        if message.plural is None:
            translated[message.catalog_key] = _translate_singular(catalog, message)
        else:
            translated[message.catalog_key] = _translate_plural(catalog, message)
    return translated


def frontend_catalog_payload(catalog: Any, locale: str) -> dict[str, object]:
    """Build one browser catalog with translated messages and its plural rule."""
    if not isinstance(locale, str) or not locale.strip():
        raise ValueError("frontend catalog locale must be a non-blank string")
    payload: dict[str, object] = {
        "locale": locale,
        "messages": frontend_catalog_messages(catalog),
    }
    plural_rule = _catalog_plural_rule(catalog)
    if plural_rule is not None:
        payload["pluralRule"] = plural_rule
    return payload


def _load_message(raw_message: object) -> FrontendMessage:
    """Validate one generated manifest entry before exposing it to runtime code."""
    if not isinstance(raw_message, Mapping):
        raise ValueError("frontend message manifest entry must be an object")
    message_id = _required_string(raw_message.get("id"), "id")
    context = _optional_string(raw_message.get("context"), "context")
    plural = _optional_string(raw_message.get("plural"), "plural")
    raw_locations = raw_message.get("locations")
    if not isinstance(raw_locations, list) or not raw_locations:
        raise ValueError(f"frontend message {message_id!r} must have source locations")
    locations = tuple(_load_location(item, message_id) for item in raw_locations)
    if list(locations) != sorted(locations, key=lambda item: (item.path, item.line)):
        raise ValueError(f"frontend message {message_id!r} locations are not sorted")
    return FrontendMessage(
        id=message_id,
        context=context,
        plural=plural,
        locations=locations,
    )


def _load_location(raw_location: object, message_id: str) -> FrontendMessageLocation:
    """Validate one repository-relative source location."""
    if not isinstance(raw_location, Mapping):
        raise ValueError(f"frontend message {message_id!r} has an invalid location")
    path = _required_string(raw_location.get("path"), "location.path")
    line = raw_location.get("line")
    if path.startswith(("/", "../")) or "\\" in path:
        raise ValueError(f"frontend message {message_id!r} location must be repository-relative")
    if not isinstance(line, int) or isinstance(line, bool) or line < 1:
        raise ValueError(f"frontend message {message_id!r} location line must be positive")
    return FrontendMessageLocation(path=path, line=line)


def _frontend_i18n_command(project_root: Path) -> tuple[str, ...]:
    """Resolve the project's installed ``oldman-web-i18n`` executable."""
    frontend_root = project_root / "frontend"
    package_extractor = (
        frontend_root
        / "node_modules"
        / "oldman-web"
        / "bin"
        / "oldman-web-i18n.mjs"
    )
    if package_extractor.is_file():
        node = shutil.which("node")
        if node is None:
            raise RuntimeError(
                "Node.js is required to process frontend translation messages."
            )
        return (node, str(package_extractor))

    local_extractor = (
        frontend_root / "node_modules" / ".bin" / "oldman-web-i18n"
    )
    if local_extractor.is_file():
        return (str(local_extractor),)

    installed_extractor = shutil.which("oldman-web-i18n")
    if installed_extractor is not None:
        return (installed_extractor,)
    raise RuntimeError(
        "oldman-web-i18n is unavailable; install the frontend dependencies first."
    )


def _catalog_value(value: object, key: object) -> str | list[str]:
    """Validate one value produced by ``oldman-web-i18n compile-po``."""
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and all(
        isinstance(item, str) for item in value
    ):
        return value
    raise ValueError(f"frontend catalog message {key!r} has an invalid value")


def _required_string(value: object, field: str) -> str:
    """Return one required non-blank manifest string."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"frontend message manifest {field} must be a non-blank string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    """Return one nullable, non-blank manifest string."""
    if value is None:
        return None
    return _required_string(value, field)


def _identity_sort_key(identity: tuple[str | None, str, str | None]) -> tuple[str, str, str]:
    """Match the generator's stable context, ID, and plural ordering."""
    context, message_id, plural = identity
    return (context or "", message_id, plural or "")


def _translate_singular(catalog: Any, message: FrontendMessage) -> str:
    """Translate one singular message, preserving gettext source fallback."""
    if message.context is not None:
        pgettext = getattr(catalog, "pgettext", None)
        if callable(pgettext):
            return str(pgettext(message.context, message.id))
    gettext = getattr(catalog, "gettext", None)
    return str(gettext(message.id)) if callable(gettext) else message.id


def _translate_plural(catalog: Any, message: FrontendMessage) -> list[str]:
    """Return every translated plural form available in a Babel catalog."""
    assert message.plural is not None
    raw_catalog = getattr(catalog, "_catalog", None)
    if isinstance(raw_catalog, Mapping):
        values = tuple(_catalog_plural_values(raw_catalog, message))
        if values:
            return list(values)
    return [message.id, message.plural]


def _catalog_plural_values(
    catalog: Mapping[object, object],
    message: FrontendMessage,
) -> Iterator[str]:
    """Read Babel/GNUTranslations indexed plural entries in numeric order."""
    assert message.plural is not None
    base_key = message.catalog_key
    index = 0
    while (base_key, index) in catalog:
        value = catalog[(base_key, index)]
        fallback = message.id if index == 0 else message.plural
        yield value if isinstance(value, str) and value else fallback
        index += 1


def _catalog_plural_rule(catalog: Any) -> str | None:
    """Extract the JavaScript-compatible expression from a gettext header."""
    info = getattr(catalog, "_info", None)
    if not isinstance(info, Mapping):
        return None
    plural_forms = info.get("plural-forms")
    if not isinstance(plural_forms, str):
        return None
    match = _PLURAL_RULE_PATTERN.search(plural_forms)
    if match is None:
        return None
    rule = match.group(1).strip()
    return rule or None


__all__ = [
    "FrontendMessage",
    "FrontendMessageLocation",
    "compile_project_frontend_catalog",
    "extract_project_frontend_messages",
    "filter_frontend_catalog_payload",
    "frontend_catalog_messages",
    "frontend_catalog_payload",
    "frontend_messages_from_manifest",
    "oldman_web_messages",
]
