"""Discover project and packaged static files without exposing source directories."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, slots=True)
class StaticSource:
    """One ordered static source consumed by the collection process."""

    name: str
    root: Traversable
    package_owned: bool = False

    def iter_files(self) -> Iterator[StaticSourceFile]:
        """Yield source files in stable logical-path order."""
        if _is_symlink(self.root):
            raise ValueError(f"static source {self.name} must not be a symbolic link")
        yield from _walk_static_files(self, self.root, PurePosixPath())


@dataclass(frozen=True, slots=True)
class StaticSourceFile:
    """One readable source file and its public path inside the collection root."""

    source_name: str
    relative_path: PurePosixPath
    resource: Traversable

    def read_bytes(self) -> bytes:
        """Read the source through the Traversable API used by installed wheels."""
        return self.resource.read_bytes()


def project_static_source(directory: str | Path) -> StaticSource:
    """Return the project-owned static source with highest collection priority."""
    return StaticSource(name="project", root=Path(directory))


def framework_static_sources() -> tuple[StaticSource, ...]:
    """Return all built-in framework static sources in stable priority order."""
    return (
        StaticSource(
            name="oldman.web",
            root=resources.files("oldman.web").joinpath("static"),
            package_owned=True,
        ),
        StaticSource(
            name="oldman.apps.admin",
            root=resources.files("oldman.apps").joinpath("admin", "static"),
            package_owned=True,
        ),
    )


def _walk_static_files(
    source: StaticSource,
    directory: Traversable,
    relative_directory: PurePosixPath,
) -> Iterator[StaticSourceFile]:
    """Walk one Traversable tree while rejecting Python files in package assets."""
    if not directory.is_dir():
        return

    for child in sorted(directory.iterdir(), key=lambda item: item.name):
        relative_path = relative_directory / child.name
        if _is_symlink(child):
            raise ValueError(
                f"static source {source.name} contains symbolic link "
                f"{relative_path.as_posix()!r}"
            )
        if child.is_dir():
            if child.name == "__pycache__":
                continue
            yield from _walk_static_files(source, child, relative_path)
            continue
        if not child.is_file():
            continue
        if source.package_owned and child.name.endswith((".py", ".pyc", ".pyo")):
            raise ValueError(
                f"package static source {source.name} contains Python file "
                f"{relative_path.as_posix()!r}"
            )
        yield StaticSourceFile(
            source_name=source.name,
            relative_path=relative_path,
            resource=child,
        )


def _is_symlink(resource: Traversable) -> bool:
    """Return whether a filesystem-like resource explicitly reports a symlink."""
    is_symlink = getattr(resource, "is_symlink", None)
    return bool(is_symlink()) if callable(is_symlink) else False


__all__ = [
    "StaticSource",
    "StaticSourceFile",
    "framework_static_sources",
    "project_static_source",
]
