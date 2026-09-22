"""Static asset bundle registry."""

from oldman.web.staticfiles.bundles import (
    DEV_MODE_ENV,
    StaticBundle,
    StaticBundleRegistry,
    app_bundle_registry,
    dev_mode_requested,
    register_project_bundle,
)
from oldman.web.staticfiles.collector import (
    StaticCollectionConflict,
    StaticCollectionResult,
    collect_project_static,
    collect_static,
    collection_manifest_path,
)
from oldman.web.staticfiles.finders import (
    StaticSource,
    StaticSourceFile,
    framework_static_sources,
    project_static_source,
)
from oldman.web.staticfiles.urls import (
    OLDMAN_STATIC_NAMESPACE,
    oldman_asset_path,
    oldman_asset_url,
    static_asset_url,
)

__all__ = [
    "DEV_MODE_ENV",
    "OLDMAN_STATIC_NAMESPACE",
    "StaticBundle",
    "StaticBundleRegistry",
    "StaticCollectionConflict",
    "StaticCollectionResult",
    "StaticSource",
    "StaticSourceFile",
    "app_bundle_registry",
    "collect_project_static",
    "collect_static",
    "collection_manifest_path",
    "dev_mode_requested",
    "framework_static_sources",
    "oldman_asset_path",
    "oldman_asset_url",
    "project_static_source",
    "register_project_bundle",
    "static_asset_url",
]
