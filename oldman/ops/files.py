"""Edits that server maintenance makes to configuration files, safe to run again and again."""

from __future__ import annotations

import os
import re
from pathlib import Path

from oldman.utils.files import atomic_write


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _write_if_changed(path: Path, before: str | None, after: str, *, follow_symlinks: bool) -> bool:
    if after == before:
        return False
    atomic_write(path, after, follow_symlinks=follow_symlinks)
    return True


def edit_marked_block(
    path: str | os.PathLike[str],
    marker: str,
    content: str,
    *,
    follow_symlinks: bool,
    comment: str = "#",
) -> bool:
    """Put `content` between `{comment} >>> {marker}` and `{comment} <<< {marker}` lines.

    An existing block with that marker is replaced; otherwise the block is appended, and a missing
    file is created. Running it again with the same content changes nothing. Returns whether the
    file changed. `follow_symlinks` is passed to `atomic_write`: say whether a symlink at `path`
    should have its target rewritten or be replaced by a regular file.
    """
    target = Path(path)
    before = _read_text(target)
    existing = before or ""
    block = f"{comment} >>> {marker}\n{content.rstrip()}\n{comment} <<< {marker}\n"
    pattern = re.compile(
        rf"^{re.escape(comment)} >>> {re.escape(marker)}\n.*?^{re.escape(comment)} <<< {re.escape(marker)}(?:\n|\Z)", re.DOTALL | re.MULTILINE
    )
    if pattern.search(existing):
        after = pattern.sub(lambda _match: block, existing, count=1)
    else:
        separator = "" if existing.endswith("\n") or not existing else "\n"
        after = f"{existing}{separator}{block}"
    return _write_if_changed(target, before, after, follow_symlinks=follow_symlinks)


def _directive_pattern(key: str, separator: str, comment: str, *, commented: bool) -> re.Pattern[str]:
    gap = r"[ \t]+" if separator.isspace() else rf"[ \t]*{re.escape(separator.strip())}[ \t]*"
    # A commented-out setting sits right after the comment mark (`#Port 22`); `# Port numbers ...`
    # is prose and must not become a setting.
    lead = rf"[ \t]*(?:{re.escape(comment)})?" if commented else r"[ \t]*"
    return re.compile(rf"^{lead}{re.escape(key)}{gap}(?P<value>.*?)[ \t]*$", re.MULTILINE | re.IGNORECASE)


def set_directive(
    path: str | os.PathLike[str],
    key: str,
    value: str,
    *,
    follow_symlinks: bool,
    separator: str = " ",
    comment: str = "#",
) -> bool:
    """Make `key` read `value` in a `key value` style file such as sshd_config.

    Every line for the key, commented out (`#Port 22`, the mark right before the key) or not,
    becomes `{key}{separator}{value}`, so neither an earlier example line nor a later setting keeps
    another value; without one the line is appended. A comment with a space after the mark is prose
    and stays. Keys match regardless of case. Lines inside conditional sections (sshd `Match`) are
    changed too. Returns whether the file changed; `follow_symlinks` as in `edit_marked_block`.
    """
    target = Path(path)
    before = _read_text(target)
    existing = before or ""
    line = f"{key}{separator}{value}"
    pattern = _directive_pattern(key, separator, comment, commented=True)
    if pattern.search(existing):
        after = pattern.sub(lambda _match: line, existing)
    else:
        newline = "" if existing.endswith("\n") or not existing else "\n"
        after = f"{existing}{newline}{line}\n"
    return _write_if_changed(target, before, after, follow_symlinks=follow_symlinks)


def read_directive(
    path: str | os.PathLike[str],
    key: str,
    default: str | None = None,
    *,
    separator: str = " ",
    comment: str = "#",
) -> str | None:
    """The value of the first line setting `key` that is not commented out, else `default`.

    A missing file gives `default` too; keys match regardless of case.
    """
    text = _read_text(Path(path))
    if text is None:
        return default
    match = _directive_pattern(key, separator, comment, commented=False).search(text)
    return match.group("value") if match else default


_OS_RELEASE_PATHS = (Path("/etc/os-release"), Path("/usr/lib/os-release"))
_OS_RELEASE_LINE = re.compile(r"^(?P<key>[A-Z0-9_]+)=(?P<value>.*)$")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        return re.sub(r"\\(.)", r"\1", inner) if value[0] == '"' else inner
    return value


def os_release(path: str | os.PathLike[str] | None = None) -> dict[str, str]:
    """The operating system's identification, such as `ID`, `VERSION_ID` and `PRETTY_NAME`.

    Without `path` it reads `/etc/os-release`, then `/usr/lib/os-release` (see os-release(5));
    an empty dict when neither exists. Quotes around values are removed.
    """
    candidates = (Path(path),) if path is not None else _OS_RELEASE_PATHS
    for candidate in candidates:
        text = _read_text(candidate)
        if text is None:
            continue
        release: dict[str, str] = {}
        for line in text.splitlines():
            match = _OS_RELEASE_LINE.match(line.strip())
            if match:
                release[match.group("key")] = _unquote(match.group("value"))
        return release
    return {}


__all__ = ["edit_marked_block", "os_release", "read_directive", "set_directive"]
