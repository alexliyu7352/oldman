"""Oldman names and helpers for Sanic routing."""

from __future__ import annotations

import importlib
from glob import glob
from importlib import import_module, util
from inspect import getmembers
from pathlib import Path
from types import ModuleType

from sanic import Sanic as WebApp
from sanic.blueprints import Blueprint

get_app = WebApp.get_app


def autodiscover(app: WebApp, *module_names: str | ModuleType, recursive: bool = False) -> None:
    """Discover and register blueprints from one or more modules."""
    package = app.__module__
    blueprints: set[Blueprint] = set()
    imported_paths: set[str] = set()

    def find_blueprints(module: ModuleType) -> None:
        """Collect Blueprint instances defined or imported by one module."""
        for _, member in getmembers(module):
            if isinstance(member, Blueprint):
                blueprints.add(member)

    for module in module_names:
        if isinstance(module, str):
            imported_module = import_module(module, package)
            if imported_module.__file__:
                imported_paths.add(imported_module.__file__)
            module = imported_module
        find_blueprints(module)

        if recursive and module.__file__:
            base = Path(module.__file__).parent
            for path in glob(f"{base}/**/*.py", recursive=True):
                if path in imported_paths:
                    continue
                name = "module"
                if "__init__" in path:
                    *_, name, _ = path.split("/")
                spec = util.spec_from_file_location(name, path)
                if spec and spec.loader:
                    discovered_module = util.module_from_spec(spec)
                    imported_paths.add(path)
                    spec.loader.exec_module(discovered_module)
                    find_blueprints(discovered_module)

    for blueprint in blueprints:
        app.blueprint(blueprint)


def import_app_modules(package_name: str, suffixes: tuple[str, ...] = ("models", "views")) -> None:
    """Import conventional modules from an application package."""
    importlib.import_module(package_name)
    for suffix in suffixes:
        module_name = f"{package_name}.{suffix}"
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name != module_name:
                raise


__all__ = ["WebApp", "autodiscover", "get_app", "import_app_modules"]
