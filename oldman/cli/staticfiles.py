"""Lazy CLI adapter for the public staticfiles collector."""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

from oldman.cli.settings import SettingsCliError, get_settings_manager
from oldman.i18n import gettext_noop
from oldman.runtime.discovery import ServiceDefinition


def collect_static_files(
    service_definition: ServiceDefinition,
    config_file: Path | None = None,
    *,
    clear: bool = False,
) -> Any:
    """Collect Web and installed-App assets for one cold service definition."""
    manager = get_settings_manager(service_definition, config_file)
    settings = manager.load()
    web = getattr(settings, "web", None)
    static = getattr(web, "static", None)
    if static is None:
        raise SettingsCliError(gettext_noop("The project settings profile does not include static files."))
    if not static.root:
        raise SettingsCliError(gettext_noop("settings.web.static.root is empty; static files cannot be collected."))

    # Importing oldman.web is intentionally confined to this command.
    from oldman.web.staticfiles import StaticSource, collect_project_static

    packaged_sources = [
        StaticSource(
            name="oldman.web",
            root=resources.files("oldman.web").joinpath("static"),
            package_owned=True,
        )
    ]
    for package in manager.registry.packages:
        static_root = resources.files(package).joinpath("static")
        if static_root.is_dir():
            packaged_sources.append(
                StaticSource(
                    name=package,
                    root=static_root,
                    package_owned=True,
                )
            )

    return collect_project_static(
        project_directory=static.dir,
        destination=static.root,
        clear=clear,
        packaged_sources=tuple(packaged_sources),
    )


__all__ = ["collect_static_files"]
