"""Copy the framework's templates into a project, where the project can change them.

The templates a service can use come from `oldman/web/templates` and from the `templates` directory
of each installed framework App (the built-in Admin's, when the service installs it), the same way
`static collect` finds each App's `static`. A copy keeps its path under `templates/`, so it replaces
the framework's file of the same name; upgrading the framework later does not change it.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path


@dataclass(frozen=True)
class TemplateSource:
    """One directory of templates and the package it ships with."""

    package: str
    root: Path


@dataclass(frozen=True)
class TemplateCopyPlan:
    """What copying would do: new files, files the project has changed, files already the same."""

    destination: Path
    new: tuple[tuple[Path, Path], ...]
    changed: tuple[tuple[Path, Path], ...]
    unchanged: int


def framework_template_sources(installed_packages: Iterable[str]) -> tuple[TemplateSource, ...]:
    """`oldman/web/templates`, then the `templates` directory of each installed framework App that has one."""
    # Importing oldman.web is confined to the command, as for `static collect`.
    from oldman.web.package_data import package_template_dir

    sources = [TemplateSource("oldman.web", package_template_dir())]
    for package in installed_packages:
        # Only the framework's: a project's own Apps keep their templates in the project already.
        if not package.startswith("oldman."):
            continue
        root = Path(str(resources.files(package).joinpath("templates")))
        if root.is_dir():
            sources.append(TemplateSource(package, root))
    return tuple(sources)


def plan_template_copy(sources: Iterable[TemplateSource], destination: Path) -> TemplateCopyPlan:
    """Sort every framework template into new, changed in the project, or already the same.

    When two sources have a file at the same path, the first wins: it is also the one a service finds first.
    """
    new: list[tuple[Path, Path]] = []
    changed: list[tuple[Path, Path]] = []
    unchanged = 0
    seen: set[Path] = set()
    for source in sources:
        for path in sorted(source.root.rglob("*")):
            relative = path.relative_to(source.root)
            if not path.is_file() or relative in seen or "__pycache__" in relative.parts:
                continue
            seen.add(relative)
            target = destination / relative
            if not target.exists():
                new.append((path, target))
            elif target.read_bytes() == path.read_bytes():
                unchanged += 1
            else:
                changed.append((path, target))
    return TemplateCopyPlan(destination=destination, new=tuple(new), changed=tuple(changed), unchanged=unchanged)


def apply_template_copy(plan: TemplateCopyPlan, *, overwrite: bool) -> int:
    """Write the new files, and the changed ones only with `overwrite`; return how many files were written."""
    copies = [*plan.new, *(plan.changed if overwrite else ())]
    for source, target in copies:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return len(copies)


__all__ = [
    "TemplateCopyPlan",
    "TemplateSource",
    "apply_template_copy",
    "framework_template_sources",
    "plan_template_copy",
]
