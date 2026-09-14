"""Hatch hook keeping repository-only VCS metadata out of the source distribution."""

from __future__ import annotations

from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Remove Hatchling's automatically forced `.gitignore` member."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        del version
        force_include = build_data.get("force_include")
        if not isinstance(force_include, dict):
            raise RuntimeError("Hatch sdist force_include build data is malformed")
        for source, destination in tuple(force_include.items()):
            if destination == ".gitignore":
                force_include.pop(source)
