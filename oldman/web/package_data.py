"""Package data helpers."""

from __future__ import annotations

from pathlib import Path


def package_root() -> Path:
    """Return oldman.web package root on the local filesystem."""
    return Path(__file__).resolve().parent


def package_template_dir() -> Path:
    """Return bundled template directory."""
    return package_root() / "templates"


__all__ = ["package_root", "package_template_dir"]
