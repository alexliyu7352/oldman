"""Vite-style static bundle registry.

The registry is framework code: it does not know about project settings, apps,
or service modules. Consumers register concrete bundles from their application
startup code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

from markupsafe import Markup


@dataclass(frozen=True)
class StaticBundle:
    """A named frontend bundle backed by a manifest or a dev server."""

    name: str
    entry_path: str
    manifest_path: Path
    static_url: str
    dev_server_url: str = ""
    dev_mode: bool = False
    passthrough_prefixes: tuple[str, ...] = ()

    def normalized_static_url(self) -> str:
        """Return static URL without trailing slash."""
        return self.static_url.rstrip("/")

    def normalized_dev_server_url(self) -> str:
        """Return dev server URL without trailing slash."""
        return self.dev_server_url.rstrip("/")


class StaticBundleRegistry:
    """Registry for named frontend bundles."""

    def __init__(self) -> None:
        self._bundles: dict[str, StaticBundle] = {}

    def register(self, bundle: StaticBundle) -> None:
        """Register or replace a bundle."""
        self._bundles[bundle.name] = bundle

    def get(self, bundle_name: str) -> StaticBundle:
        """Return a registered bundle."""
        try:
            return self._bundles[bundle_name]
        except KeyError as exc:
            raise KeyError(f"Unknown static bundle: {bundle_name}") from exc

    def load_manifest(self, bundle_name: str) -> dict[str, dict[str, Any]]:
        """Load the current bundle manifest from disk."""
        bundle = self.get(bundle_name)
        if not bundle.manifest_path.exists():
            return {}

        with bundle.manifest_path.open("r", encoding="utf-8") as manifest_file:
            return json.load(manifest_file)

    def ensure_build_available(self, bundle_name: str, entry_path: str | None = None) -> None:
        """Fail fast when a production bundle manifest or entry is missing."""
        bundle = self.get(bundle_name)
        if bundle.dev_mode:
            return

        if not bundle.manifest_path.exists():
            raise RuntimeError(f"Vite manifest for bundle {bundle_name} not found at {bundle.manifest_path}. Run pnpm build before web start.")

        entry = entry_path or bundle.entry_path
        asset = self.load_manifest(bundle_name).get(entry)
        if not asset or not asset.get("file"):
            raise RuntimeError(f"Vite manifest for bundle {bundle_name} does not contain entry {entry}. Run pnpm build before web start.")

    def asset_base_url(self, bundle_name: str) -> str:
        """Return the base URL used by frontend runtime asset loading."""
        bundle = self.get(bundle_name)
        if bundle.dev_mode:
            return f"{bundle.normalized_dev_server_url()}/"
        return f"{bundle.normalized_static_url()}/"

    def asset_url(self, bundle_name: str, asset_path: str) -> str:
        """Resolve a static asset URL for a bundle."""
        bundle = self.get(bundle_name)
        normalized_asset_path = asset_path.lstrip("/")

        if bundle.dev_mode:
            return f"{bundle.normalized_dev_server_url()}/{normalized_asset_path}"

        if normalized_asset_path.startswith(bundle.passthrough_prefixes):
            return f"{bundle.normalized_static_url()}/{normalized_asset_path}"

        asset = self.load_manifest(bundle_name).get(normalized_asset_path)
        if not asset or not asset.get("file"):
            return ""

        return f"{bundle.normalized_static_url()}/{str(asset['file']).lstrip('/')}"

    def client_tags(self, bundle_name: str) -> Markup:
        """Render dev client tags for a bundle."""
        bundle = self.get(bundle_name)
        if not bundle.dev_mode:
            return Markup("")
        return Markup(module_script(f"{bundle.normalized_dev_server_url()}/@vite/client"))

    def styles_tags(self, bundle_name: str, entry_path: str | None = None) -> Markup:
        """Render stylesheet tags for an entry."""
        bundle = self.get(bundle_name)
        entry = entry_path or bundle.entry_path
        if bundle.dev_mode:
            if is_css_asset_path(entry):
                return Markup(stylesheet_link(self.asset_url(bundle_name, entry)))
            return Markup("")

        manifest = self.load_manifest(bundle_name)
        asset = manifest.get(entry)
        if not asset:
            return Markup("")

        css_paths = collect_vite_css(manifest, asset)
        output_file = str(asset.get("file", ""))
        if is_css_asset_path(output_file) and output_file not in css_paths:
            css_paths.append(output_file)
        tags = [stylesheet_link(f"{bundle.normalized_static_url()}/{css_path.lstrip('/')}") for css_path in css_paths]
        return Markup("\n".join(tags))

    def modulepreload_tags(self, bundle_name: str, entry_path: str | None = None) -> Markup:
        """Render modulepreload tags for an entry."""
        bundle = self.get(bundle_name)
        entry = entry_path or bundle.entry_path
        if is_css_asset_path(entry):
            return Markup("")
        if bundle.dev_mode:
            return Markup("")

        manifest = self.load_manifest(bundle_name)
        asset = manifest.get(entry)
        if not asset:
            return Markup("")

        tags = []
        for import_path in collect_vite_imports(manifest, asset):
            imported = manifest.get(import_path)
            if imported and imported.get("file"):
                tags.append(modulepreload_link(f"{bundle.normalized_static_url()}/{str(imported['file']).lstrip('/')}"))
        return Markup("\n".join(tags))

    def script_tags(self, bundle_name: str, entry_path: str | None = None) -> Markup:
        """Render module script tags for an entry."""
        bundle = self.get(bundle_name)
        entry = entry_path or bundle.entry_path
        if is_css_asset_path(entry):
            return Markup("")
        if bundle.dev_mode:
            return Markup(module_script(self.asset_url(bundle_name, entry)))

        asset = self.load_manifest(bundle_name).get(entry)
        if not asset or not asset.get("file"):
            return Markup("")
        if is_css_asset_path(asset["file"]):
            return Markup("")

        return Markup(module_script(f"{bundle.normalized_static_url()}/{str(asset['file']).lstrip('/')}"))

    def entry_tags(self, bundle_name: str, entry_path: str | None = None, include_dev_client: bool = False) -> Markup:
        """Render client, modulepreload, CSS and script tags for an entry."""
        tags = []
        if include_dev_client:
            client = self.client_tags(bundle_name)
            if client:
                tags.append(str(client))

        for tag_group in (
            self.modulepreload_tags(bundle_name, entry_path),
            self.styles_tags(bundle_name, entry_path),
            self.script_tags(bundle_name, entry_path),
        ):
            if tag_group:
                tags.append(str(tag_group))

        return Markup("\n".join(tags))


def is_css_asset_path(path: object) -> bool:
    """Return whether a Vite entry or output path is a CSS asset."""
    return str(path).split("?", 1)[0].lower().endswith(".css")


def collect_vite_imports(manifest: dict[str, dict[str, Any]], asset: dict[str, Any]) -> list[str]:
    """Collect Vite import chunks in dependency order."""
    imports: list[str] = []
    seen: set[str] = set()

    def visit_imports(current_asset: dict[str, Any]) -> None:
        for import_path in current_asset.get("imports", []):
            if import_path in seen:
                continue
            seen.add(import_path)
            imports.append(import_path)
            imported = manifest.get(import_path)
            if imported:
                visit_imports(imported)

    visit_imports(asset)
    return imports


def collect_vite_css(manifest: dict[str, dict[str, Any]], asset: dict[str, Any]) -> list[str]:
    """Collect CSS files for an entry and its import chunks."""
    css_files: list[str] = []
    seen: set[str] = set()

    def append_css(current_asset: dict[str, Any]) -> None:
        for css_path in current_asset.get("css", []):
            if css_path in seen:
                continue
            seen.add(css_path)
            css_files.append(css_path)

    for import_path in collect_vite_imports(manifest, asset):
        imported = manifest.get(import_path)
        if imported:
            append_css(imported)
    append_css(asset)
    return css_files


def tag_attributes(attributes: dict[str, Any]) -> str:
    """Render HTML tag attributes."""
    rendered: list[str] = []
    for name, value in attributes.items():
        if value is None or value is False:
            continue

        escaped_name = escape(str(name), quote=True)
        if value is True:
            rendered.append(f" {escaped_name}")
            continue

        rendered.append(f' {escaped_name}="{escape(str(value), quote=True)}"')
    return "".join(rendered)


def module_script(src: str) -> str:
    """Render a module script tag."""
    return f"<script{tag_attributes({'type': 'module', 'src': src})}></script>"


def stylesheet_link(href: str) -> str:
    """Render a stylesheet link tag."""
    return f"<link{tag_attributes({'rel': 'stylesheet', 'href': href})}>"


def modulepreload_link(href: str) -> str:
    """Render a modulepreload link tag."""
    return f"<link{tag_attributes({'rel': 'modulepreload', 'href': href})}>"
