"""Built-in Admin template integration."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader

from oldman.web.template import add_framework_template_dir


def admin_template_dir() -> Path:
    """Return the templates shipped with the Admin package."""
    return Path(str(resources.files("oldman.apps").joinpath("admin", "templates")))


def install_admin_template_loader(environment: Environment) -> Environment:
    """Add Admin templates after the consumer's override-capable loader, and under `framework:` names.

    A project overriding `admin/login.html` can then extend `framework:admin/login.html` and change one block.
    """
    admin_loader = FileSystemLoader(str(admin_template_dir()))
    current_loader = environment.loader
    environment.loader = ChoiceLoader([current_loader, admin_loader]) if current_loader is not None else admin_loader
    add_framework_template_dir(environment, admin_template_dir())
    return environment


__all__ = ["admin_template_dir", "install_admin_template_loader"]
