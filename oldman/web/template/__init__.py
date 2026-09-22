"""Template integration."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from sanic_ext import render as render_template

import oldman.conf as conf
from oldman.i18n import gettext
from oldman.web.html import html_attrs
from oldman.web.package_data import package_template_dir
from oldman.web.template.i18n_extension import I18nExtension

_TEMPLATE_LOADERS_MARKER = "_oldman_template_loaders_installed"
_SYNC_ENVIRONMENT_MARKER = "_oldman_sync_template_environment"


def project_template_dir() -> Path:
    """Return configured project template directory."""
    try:
        return Path(conf.settings.web.template.dir)
    except RuntimeError:
        return package_template_dir()


def build_template_loader(project_dir: str | Path | None = None) -> ChoiceLoader:
    """Build loader with project templates taking priority over package templates."""
    loaders = []
    resolved_project_dir = Path(project_dir) if project_dir is not None else project_template_dir()
    loaders.append(FileSystemLoader(str(resolved_project_dir)))
    loaders.append(FileSystemLoader(str(package_template_dir())))
    return ChoiceLoader(loaders)


def install_template_loaders(environment: Environment, project_dir: str | Path | None = None) -> Environment:
    """Install Oldman project/package template lookup on an existing environment."""
    installed_loader = getattr(environment, _TEMPLATE_LOADERS_MARKER, None)
    if installed_loader is not None and installed_loader is environment.loader:
        register_component_filters(environment)
        return environment

    loaders = []
    if project_dir is not None:
        loaders.append(FileSystemLoader(str(Path(project_dir))))
    if environment.loader is not None:
        loaders.append(environment.loader)
    elif project_dir is None:
        loaders.append(FileSystemLoader(str(project_template_dir())))
    loaders.append(FileSystemLoader(str(package_template_dir())))
    environment.loader = ChoiceLoader(loaders)
    register_component_filters(environment)
    setattr(environment, _TEMPLATE_LOADERS_MARKER, environment.loader)
    return environment


def get_template_environment(owner: Any = None) -> Environment:
    """Return a template environment usable by server-rendered components."""
    request = getattr(owner, "request", None)
    app = getattr(request, "app", None)
    ext = getattr(app, "ext", None)
    environment = getattr(ext, "environment", None)
    if environment is None:
        environment = default_template_environment()
    elif getattr(environment, _TEMPLATE_LOADERS_MARKER, None) is not environment.loader:
        install_template_loaders(environment)
    register_component_filters(environment)
    return environment


@lru_cache(maxsize=1)
def default_template_environment() -> Environment:
    """Create async component template environment for tests and no-app rendering."""
    environment = Environment(
        loader=build_template_loader(),
        autoescape=select_autoescape(["html", "xml"]),
        enable_async=True,
    )
    register_component_filters(environment)
    return environment


@lru_cache(maxsize=1)
def sync_template_environment() -> Environment:
    """Create sync component template environment."""
    environment = Environment(
        loader=build_template_loader(),
        autoescape=select_autoescape(["html", "xml"]),
        enable_async=False,
    )
    register_component_filters(environment)
    return environment


def current_year() -> int:
    """Return the calendar year for footers; evaluated per render so long-running processes stay right."""
    return datetime.now().year


def register_component_filters(environment: Environment) -> None:
    """Register globals and filters required by component templates."""
    environment.filters.setdefault("html_attrs", html_attrs)
    environment.globals.setdefault("_", gettext)
    environment.globals.setdefault("current_year", current_year)
    # Shell partials read the language and CSRF state through these; imported lazily (they import settings).
    from oldman.web.i18n.translation import current_language, language_menu_items
    from oldman.web.security.csrf.csrf_extension import CsrfExtension
    from oldman.web.security.csrf.manager import csrf_token_for

    environment.globals.setdefault("current_language", current_language)
    environment.globals.setdefault("language_menu_items", language_menu_items)
    environment.globals.setdefault("csrf_token_for", csrf_token_for)
    # 框架自带的表单片段用 `{% csrf_token %}`（web.md 里记的那个写法），所以这个标签必须跟着组件
    # 环境一起到位，而不是只在装了 CSRF manager 的 app 上可用。标签本身只读 request.ctx，没有别的依赖。
    environment.add_extension(CsrfExtension)


async def render_component_template(owner: Any, template_name: str, context: dict[str, Any]) -> Markup:
    """Render component template asynchronously when supported."""
    template = get_template_environment(owner).get_template(template_name)
    if getattr(template.environment, "is_async", False):
        return Markup(await template.render_async(**context))
    return Markup(template.render(**context))


async def render_fragment(request: Any, template_name: str, **context: Any) -> Markup:
    """Render one HTML fragment (a modal body, a result panel) through the app's installed environment.

    `request` joins the context so partials can read the session, locale or CSRF token; the caller
    decides what to do with the markup (a JSON modal payload, a ReplaceHtml action, a 422 fragment).
    """
    context.setdefault("request", request)
    # 和兄弟函数走同一条路：装上框架自己的模板目录并注册组件 filter/global，
    # 否则只有已经装过 loader 的 app 能渲染框架自带的片段。
    environment = get_template_environment(SimpleNamespace(request=request))
    template = environment.get_template(template_name)
    if getattr(environment, "is_async", False):
        return Markup(await template.render_async(**context))
    return Markup(template.render(**context))


def render_component_template_sync(owner: Any, template_name: str, context: dict[str, Any]) -> Markup:
    """Render component template synchronously."""
    environment = get_template_environment(owner)
    if getattr(environment, "is_async", False):
        environment = sync_component_environment(environment)
    template = environment.get_template(template_name)
    return Markup(template.render(**context))


def sync_component_environment(environment: Environment) -> Environment:
    """Return a sync overlay retaining one configured app environment."""
    cached = getattr(environment, _SYNC_ENVIRONMENT_MARKER, None)
    if not isinstance(cached, Environment) or getattr(cached, "linked_to", None) is not environment:
        cached = environment.overlay(bytecode_cache=None)
        cached.is_async = False
        setattr(environment, _SYNC_ENVIRONMENT_MARKER, cached)
    return cached


__all__ = [
    "I18nExtension",
    "build_template_loader",
    "default_template_environment",
    "get_template_environment",
    "install_template_loaders",
    "register_component_filters",
    "render_template",
    "render_component_template",
    "render_component_template_sync",
    "render_fragment",
    "sync_template_environment",
]
