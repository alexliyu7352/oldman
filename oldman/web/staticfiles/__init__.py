"""Static asset bundle registry."""

from oldman.web.staticfiles.bundles import StaticBundle, StaticBundleRegistry
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
    "OLDMAN_STATIC_NAMESPACE",
    "StaticBundle",
    "StaticBundleRegistry",
    "StaticCollectionConflict",
    "StaticCollectionResult",
    "StaticSource",
    "StaticSourceFile",
    "collect_project_static",
    "collect_static",
    "collection_manifest_path",
    "framework_static_sources",
    "oldman_asset_path",
    "oldman_asset_url",
    "project_static_source",
    "static_asset_url",
]
