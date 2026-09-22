"""Collect project and framework static sources into one public root."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from oldman.web.staticfiles.finders import (
    StaticSource,
    StaticSourceFile,
    framework_static_sources,
    project_static_source,
)

_MANIFEST_VERSION = 1


@dataclass(frozen=True, slots=True)
class StaticCollectionConflict:
    """One duplicate logical path ignored because an earlier source won."""

    relative_path: str
    winner: str
    ignored: str


@dataclass(frozen=True, slots=True)
class StaticCollectionResult:
    """Summary returned by a deterministic static collection run."""

    copied: int
    unchanged: int
    removed: int
    conflicts: tuple[StaticCollectionConflict, ...]
    destination: Path


@dataclass(frozen=True, slots=True)
class _PlannedStaticFile:
    """One completely read source payload ready for transactional publication."""

    source_file: StaticSourceFile
    payload: bytes
    digest: str


def collect_project_static(
    *,
    project_directory: str | Path,
    destination: str | Path,
    clear: bool = False,
    packaged_sources: Sequence[StaticSource] | None = None,
) -> StaticCollectionResult:
    """Collect the project source followed by all built-in package sources."""
    unresolved_project_root = Path(project_directory).expanduser()
    if unresolved_project_root.is_symlink():
        raise ValueError("static source project must not be a symbolic link")
    project_root = unresolved_project_root.resolve()
    public_root = _resolve_public_root(destination)
    same_project_root = project_root == public_root
    _validate_collection_roots(project_root, public_root)

    sources: list[StaticSource] = []
    if not same_project_root:
        sources.append(project_static_source(project_root))
    sources.extend(
        framework_static_sources()
        if packaged_sources is None
        else packaged_sources
    )
    return collect_static(
        sources,
        public_root,
        clear=clear,
        preserve_existing=same_project_root,
    )


def collect_static(
    sources: Sequence[StaticSource],
    destination: str | Path,
    *,
    clear: bool = False,
    preserve_existing: bool = False,
) -> StaticCollectionResult:
    """Preflight ordered sources and transactionally publish their public files."""
    public_root = _resolve_public_root(destination)
    _validate_static_sources(sources, public_root)
    manifest_path = collection_manifest_path(public_root)
    previous_manifest = _read_manifest(manifest_path)

    # Every source is enumerated and read before staging or deleting output.
    planned_files, conflicts = _build_collection_plan(sources)
    public_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=public_root.parent,
        prefix=f".{public_root.name}.oldman-static-",
    ) as temporary_directory:
        transaction_root = Path(temporary_directory)
        staged_root = transaction_root / "output"
        removed = _stage_existing_output(
            public_root,
            staged_root,
            previous_manifest,
            clear=clear,
            preserve_existing=preserve_existing,
        )
        active_manifest = {} if clear else previous_manifest
        copied, unchanged, next_manifest = _apply_collection_plan(
            planned_files,
            staged_root,
            active_manifest,
            conflicts,
            preserve_existing=preserve_existing,
        )

        staged_manifest = transaction_root / "manifest.json"
        _write_manifest(staged_manifest, next_manifest)
        _publish_staged_collection(
            staged_root,
            public_root,
            staged_manifest,
            manifest_path,
            transaction_root,
        )

    return StaticCollectionResult(
        copied=copied,
        unchanged=unchanged,
        removed=removed,
        conflicts=tuple(conflicts),
        destination=public_root,
    )


def collection_manifest_path(destination: str | Path) -> Path:
    """Return the private sibling manifest for one public static root."""
    public_root = Path(destination).resolve()
    return public_root.parent / f".{public_root.name}.oldman-static.json"


def _resolve_public_root(destination: str | Path) -> Path:
    """Resolve and validate a destination before any filesystem mutation."""
    unresolved_root = Path(destination).expanduser()
    if unresolved_root.is_symlink():
        raise ValueError("settings.web.static.root must not be a symbolic link")
    public_root = unresolved_root.resolve()
    if public_root == Path(public_root.anchor):
        raise ValueError("refusing to use a filesystem root as settings.web.static.root")
    if public_root.exists() and not public_root.is_dir():
        raise ValueError("settings.web.static.root must be a directory")
    return public_root


def _validate_collection_roots(project_root: Path, public_root: Path) -> None:
    """Reject recursive layouts while retaining the equal-root contract."""
    if project_root != public_root and (
        public_root.is_relative_to(project_root)
        or project_root.is_relative_to(public_root)
    ):
        raise ValueError(
            "settings.web.static.dir and settings.web.static.root must not overlap"
        )


def _validate_static_sources(
    sources: Sequence[StaticSource],
    public_root: Path,
) -> None:
    """Reject filesystem sources that overlap the public destination."""
    for source in sources:
        if not isinstance(source.root, Path):
            continue
        if source.root.is_symlink():
            raise ValueError(
                f"static source {source.name} must not be a symbolic link"
            )
        source_root = source.root.resolve()
        if (
            source_root == public_root
            or source_root.is_relative_to(public_root)
            or public_root.is_relative_to(source_root)
        ):
            raise ValueError(
                f"static source {source.name} and destination must not overlap"
            )


def _build_collection_plan(
    sources: Iterable[StaticSource],
) -> tuple[
    dict[PurePosixPath, _PlannedStaticFile],
    list[StaticCollectionConflict],
]:
    """Read every source payload, then resolve public path priority."""
    winners: dict[PurePosixPath, _PlannedStaticFile] = {}
    conflicts: list[StaticCollectionConflict] = []
    for source in sources:
        for source_file in source.iter_files():
            logical_path = _validated_source_path(source_file)
            payload = source_file.read_bytes()
            planned_file = _PlannedStaticFile(
                source_file=source_file,
                payload=payload,
                digest=_digest(payload),
            )
            current = winners.get(logical_path)
            if current is None:
                current = _prefix_conflict_winner(logical_path, winners)
            if current is None:
                winners[logical_path] = planned_file
                continue
            conflicts.append(
                StaticCollectionConflict(
                    relative_path=logical_path.as_posix(),
                    winner=current.source_file.source_name,
                    ignored=source_file.source_name,
                )
            )
    return winners, conflicts


def _validated_source_path(source_file: StaticSourceFile) -> PurePosixPath:
    """Reject custom Traversable paths that could escape the public root."""
    logical_path = source_file.relative_path
    serialized = logical_path.as_posix()
    if (
        not logical_path.parts
        or logical_path.is_absolute()
        or ".." in logical_path.parts
        or "\\" in serialized
    ):
        raise ValueError(
            f"invalid static source path from {source_file.source_name}: "
            f"{serialized!r}"
        )
    return logical_path


def _prefix_conflict_winner(
    logical_path: PurePosixPath,
    winners: dict[PurePosixPath, _PlannedStaticFile],
) -> _PlannedStaticFile | None:
    """Return the earlier file that blocks a parent or descendant public path."""
    for part_count in range(1, len(logical_path.parts)):
        ancestor = PurePosixPath(*logical_path.parts[:part_count])
        current = winners.get(ancestor)
        if current is not None:
            return current
    for existing_path, current in winners.items():
        if existing_path.is_relative_to(logical_path):
            return current
    return None


def _stage_existing_output(
    public_root: Path,
    staged_root: Path,
    previous_manifest: dict[str, dict[str, str]],
    *,
    clear: bool,
    preserve_existing: bool,
) -> int:
    """Create a complete staging tree without changing the current public root."""
    should_copy_existing = public_root.exists() and (
        not clear or preserve_existing
    )
    if should_copy_existing:
        _reject_tree_symlinks(public_root)
        shutil.copytree(public_root, staged_root)
    else:
        staged_root.mkdir(parents=True)

    if not clear:
        return 0
    if not preserve_existing:
        return _count_files(public_root)
    return _remove_managed_files(staged_root, previous_manifest)


def _reject_tree_symlinks(root: Path) -> None:
    """Reject inherited public symlinks before copying an incremental tree."""
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(
                f"settings.web.static.root contains symbolic link: "
                f"{path.relative_to(root).as_posix()}"
            )


def _count_files(root: Path) -> int:
    """Count files removed by a clear publication without following directories."""
    if not root.is_dir():
        return 0
    return sum(
        1
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    )


def _remove_managed_files(
    staged_root: Path,
    previous_manifest: dict[str, dict[str, str]],
) -> int:
    """Remove only unchanged managed files from an equal source/output staging tree."""
    removed = 0
    for relative_path, entry in previous_manifest.items():
        output_file = staged_root.joinpath(
            *PurePosixPath(relative_path).parts
        )
        if not output_file.is_file():
            continue
        expected_digest = entry.get("digest")
        if not expected_digest or _file_digest(output_file) != expected_digest:
            continue
        output_file.unlink()
        removed += 1
        _remove_empty_parents(output_file.parent, staged_root)
    return removed


def _apply_collection_plan(
    planned_files: dict[PurePosixPath, _PlannedStaticFile],
    staged_root: Path,
    previous_manifest: dict[str, dict[str, str]],
    conflicts: list[StaticCollectionConflict],
    *,
    preserve_existing: bool,
) -> tuple[int, int, dict[str, dict[str, str]]]:
    """Overlay one complete plan onto staging and return its new manifest."""
    copied = 0
    unchanged = 0
    next_manifest: dict[str, dict[str, str]] = {
        path: entry
        for path, entry in previous_manifest.items()
        if (staged_root / PurePosixPath(path)).is_file()
    }

    for logical_path, planned_file in planned_files.items():
        output_file = staged_root.joinpath(*logical_path.parts)
        protected_path = _prepare_output_path(
            output_file,
            staged_root,
            logical_path,
            next_manifest,
            preserve_existing=preserve_existing,
        )
        if protected_path is not None:
            conflicts.append(
                StaticCollectionConflict(
                    relative_path=logical_path.as_posix(),
                    winner="existing project file",
                    ignored=planned_file.source_file.source_name,
                )
            )
            _drop_manifest_paths(next_manifest, protected_path)
            continue

        previous = previous_manifest.get(logical_path.as_posix())
        if _must_preserve_existing(
            output_file,
            previous,
            preserve_existing=preserve_existing,
        ):
            conflicts.append(
                StaticCollectionConflict(
                    relative_path=logical_path.as_posix(),
                    winner="existing project file",
                    ignored=planned_file.source_file.source_name,
                )
            )
            next_manifest.pop(logical_path.as_posix(), None)
            continue

        if (
            output_file.is_file()
            and _file_digest(output_file) == planned_file.digest
        ):
            unchanged += 1
        else:
            _atomic_write(output_file, planned_file.payload)
            copied += 1
        next_manifest[logical_path.as_posix()] = {
            "digest": planned_file.digest,
            "source": planned_file.source_file.source_name,
        }
    return copied, unchanged, next_manifest


def _prepare_output_path(
    output_file: Path,
    staged_root: Path,
    logical_path: PurePosixPath,
    manifest: dict[str, dict[str, str]],
    *,
    preserve_existing: bool,
) -> PurePosixPath | None:
    """Prepare parents and return a project-owned path blocking publication."""
    current = staged_root
    for part in logical_path.parts[:-1]:
        current /= part
        if current.is_file():
            relative_current = PurePosixPath(
                *current.relative_to(staged_root).parts
            )
            if preserve_existing and not _is_unchanged_managed_file(
                current,
                relative_current,
                manifest,
            ):
                return relative_current
            current.unlink()
            _drop_manifest_paths(manifest, relative_current)
        current.mkdir(exist_ok=True)

    if output_file.is_dir():
        if preserve_existing and not _contains_only_unchanged_managed_files(
            output_file,
            staged_root,
            manifest,
        ):
            return logical_path
        shutil.rmtree(output_file)
        _drop_manifest_paths(manifest, logical_path)
    return None


def _is_unchanged_managed_file(
    path: Path,
    logical_path: PurePosixPath,
    manifest: dict[str, dict[str, str]],
) -> bool:
    """Return whether a path is still identical to its managed manifest entry."""
    entry = manifest.get(logical_path.as_posix())
    expected_digest = entry.get("digest") if entry is not None else None
    return bool(
        expected_digest
        and path.is_file()
        and _file_digest(path) == expected_digest
    )


def _contains_only_unchanged_managed_files(
    directory: Path,
    staged_root: Path,
    manifest: dict[str, dict[str, str]],
) -> bool:
    """Return whether replacing a directory cannot remove project-owned files."""
    files = [path for path in directory.rglob("*") if path.is_file()]
    if not files:
        return False
    return all(
        _is_unchanged_managed_file(
            path,
            PurePosixPath(*path.relative_to(staged_root).parts),
            manifest,
        )
        for path in files
    )


def _drop_manifest_paths(
    manifest: dict[str, dict[str, str]],
    logical_path: PurePosixPath,
) -> None:
    """Remove manifest entries at or below one replaced filesystem path."""
    for relative_path in tuple(manifest):
        candidate = PurePosixPath(relative_path)
        if candidate == logical_path or candidate.is_relative_to(logical_path):
            manifest.pop(relative_path, None)


def _must_preserve_existing(
    output_file: Path,
    previous: dict[str, str] | None,
    *,
    preserve_existing: bool,
) -> bool:
    """Protect project files when source and collection roots are identical."""
    if not preserve_existing or not output_file.is_file():
        return False
    if previous is None:
        return True
    previous_digest = previous.get("digest")
    return not previous_digest or _file_digest(output_file) != previous_digest


def _publish_staged_collection(
    staged_root: Path,
    public_root: Path,
    staged_manifest: Path,
    manifest_path: Path,
    transaction_root: Path,
) -> None:
    """Publish output then manifest, restoring both if the final step fails."""
    backup_root = transaction_root / "previous-output"
    backup_manifest = transaction_root / "previous-manifest.json"
    had_public_root = public_root.exists()
    had_manifest = manifest_path.is_file()
    if had_manifest:
        shutil.copy2(manifest_path, backup_manifest)

    if had_public_root:
        _replace_path(public_root, backup_root)
    try:
        _replace_path(staged_root, public_root)
        _replace_path(staged_manifest, manifest_path)
    except Exception:
        if public_root.exists():
            shutil.rmtree(public_root)
        if had_public_root and backup_root.exists():
            _replace_path(backup_root, public_root)
        if had_manifest and backup_manifest.exists():
            _replace_path(backup_manifest, manifest_path)
        elif manifest_path.is_file():
            manifest_path.unlink()
        raise


def _replace_path(source: Path, destination: Path) -> None:
    """Replace one path; isolated for deterministic publication-failure tests."""
    source.replace(destination)


def _remove_empty_parents(directory: Path, stop: Path) -> None:
    """Remove empty managed directories without crossing the staged root."""
    current = directory
    while current != stop and current.is_relative_to(stop):
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _read_manifest(path: Path) -> dict[str, dict[str, str]]:
    """Load a validated private collection manifest or ignore an absent one."""
    if path.is_symlink():
        raise RuntimeError(
            f"static collection manifest must not be a symbolic link: {path}"
        )
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid static collection manifest: {path}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("version") != _MANIFEST_VERSION
    ):
        raise RuntimeError(f"unsupported static collection manifest: {path}")
    raw_files = payload.get("files")
    if not isinstance(raw_files, dict):
        raise RuntimeError(
            f"invalid static collection manifest files: {path}"
        )

    files: dict[str, dict[str, str]] = {}
    for relative_path, raw_entry in raw_files.items():
        if (
            not isinstance(relative_path, str)
            or not isinstance(raw_entry, dict)
        ):
            raise RuntimeError(
                f"invalid static collection manifest entry: {path}"
            )
        _validate_manifest_relative_path(relative_path, path)
        digest = raw_entry.get("digest")
        source = raw_entry.get("source")
        if (
            not isinstance(digest, str)
            or len(digest) != hashlib.sha256().digest_size * 2
            or any(character not in "0123456789abcdef" for character in digest)
            or not isinstance(source, str)
        ):
            raise RuntimeError(
                f"invalid static collection manifest entry: {path}"
            )
        files[relative_path] = {"digest": digest, "source": source}
    return files


def _validate_manifest_relative_path(
    relative_path: str,
    manifest: Path,
) -> None:
    """Reject manifest entries that could escape the configured static root."""
    logical_path = PurePosixPath(relative_path)
    if (
        not logical_path.parts
        or logical_path.is_absolute()
        or ".." in logical_path.parts
        or "\\" in relative_path
    ):
        raise RuntimeError(
            f"invalid static collection manifest path: {manifest}"
        )


def _write_manifest(
    path: Path,
    files: dict[str, dict[str, str]],
) -> None:
    """Atomically publish a stable private collection manifest."""
    payload: dict[str, Any] = {
        "version": _MANIFEST_VERSION,
        "files": dict(sorted(files.items())),
    }
    # 这里刻意用 stdlib：没有 ensure_ascii=False，非 ASCII 会被转义成 \uXXXX，
    # 而 orjson 永远输出原样 UTF-8 且没有这个选项。清单是发布产物并受打包门禁比对，
    # 换了会改变文件内容。
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    _atomic_write(path, serialized.encode("utf-8"))


def _atomic_write(path: Path, payload: bytes) -> None:
    """Replace one output only after its complete payload reaches disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _digest(payload: bytes) -> str:
    """Return the content identity used by incremental collection."""
    return hashlib.sha256(payload).hexdigest()


def _file_digest(path: Path) -> str:
    """Return the content identity of an existing collected file."""
    return _digest(path.read_bytes())


__all__ = [
    "StaticCollectionConflict",
    "StaticCollectionResult",
    "collect_project_static",
    "collect_static",
    "collection_manifest_path",
]
