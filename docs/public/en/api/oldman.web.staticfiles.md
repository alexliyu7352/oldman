# `oldman.web.staticfiles`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Static asset bundle registry.

Import with `from oldman.web.staticfiles import <name>`.

## `app_bundle_registry`

function · defined in `oldman.web.staticfiles.bundles`

```python
def app_bundle_registry(app: Any) -> StaticBundleRegistry
```

The registry shared by everything installed on one app, created on first use at `app.ctx.static_bundle_registry`.

## `collect_project_static`

function · defined in `oldman.web.staticfiles.collector`

```python
def collect_project_static(*, project_directory: str | Path, destination: str | Path, clear: bool=False, packaged_sources: Sequence[StaticSource] | None=None) -> StaticCollectionResult
```

Collect the project source followed by all built-in package sources.

## `collect_static`

function · defined in `oldman.web.staticfiles.collector`

```python
def collect_static(sources: Sequence[StaticSource], destination: str | Path, *, clear: bool=False, preserve_existing: bool=False) -> StaticCollectionResult
```

Preflight ordered sources and transactionally publish their public files.

## `collection_manifest_path`

function · defined in `oldman.web.staticfiles.collector`

```python
def collection_manifest_path(destination: str | Path) -> Path
```

Return the private sibling manifest for one public static root.

## `DEV_MODE_ENV`

value · defined in `oldman.web.staticfiles.bundles`

```python
DEV_MODE_ENV = 'OLDMAN_DEV'
```

## `dev_mode_requested`

function · defined in `oldman.web.staticfiles.bundles`

```python
def dev_mode_requested(environ: Mapping[str, str] | None=None) -> bool
```

Whether this process serves frontend assets from the Vite dev server (`OLDMAN_DEV=1/true/yes/on`).

## `framework_static_sources`

function · defined in `oldman.web.staticfiles.finders`

```python
def framework_static_sources() -> tuple[StaticSource, ...]
```

Return all built-in framework static sources in stable priority order.

## `oldman_asset_path`

function · defined in `oldman.web.staticfiles.urls`

```python
def oldman_asset_path(asset_path: str) -> str
```

Return a logical path inside Oldman's collected static namespace.

## `oldman_asset_url`

function · defined in `oldman.web.staticfiles.urls`

```python
def oldman_asset_url(static_url: str, asset_path: str) -> str
```

Build the public URL for one collected Oldman framework asset.

## `OLDMAN_STATIC_NAMESPACE`

value · defined in `oldman.web.staticfiles.urls`

```python
OLDMAN_STATIC_NAMESPACE = 'oldman'
```

## `project_static_source`

function · defined in `oldman.web.staticfiles.finders`

```python
def project_static_source(directory: str | Path) -> StaticSource
```

Return the project-owned static source with highest collection priority.

## `register_project_bundle`

function · defined in `oldman.web.staticfiles.bundles`

```python
def register_project_bundle(registry: StaticBundleRegistry, *, name: str, entry_path: str, static_root: str | Path | None, static_url: str, dev_mode: bool, dev_server_url: str='', dist_dir: str='dist', passthrough_prefixes: tuple[str, ...]=()) -> StaticBundle
```

Register a project's Vite bundle.

## `static_asset_url`

function · defined in `oldman.web.staticfiles.urls`

```python
def static_asset_url(static_url: str, asset_path: str) -> str
```

Join one validated logical asset path to the configured public prefix.

## `StaticBundle`

class · defined in `oldman.web.staticfiles.bundles`

```python
class StaticBundle
```

A named frontend bundle backed by a manifest or a dev server.

Members:

- `name: str`
- `entry_path: str`
- `manifest_path: Path`
- `static_url: str`
- `dev_server_url: str = ''`
- `dev_mode: bool = False`
- `passthrough_prefixes: tuple[str, ...] = ()`
- `def normalized_static_url() -> str` — Return static URL without trailing slash.
- `def normalized_dev_server_url() -> str` — Return dev server URL without trailing slash.

## `StaticBundleRegistry`

class · defined in `oldman.web.staticfiles.bundles`

```python
class StaticBundleRegistry
```

Registry for named frontend bundles.

Constructor:

```python
StaticBundleRegistry() -> None
```

Members:

- `def register(bundle: StaticBundle) -> None` — Register or replace a bundle.
- `def get(bundle_name: str) -> StaticBundle` — Return a registered bundle.
- `def load_manifest(bundle_name: str) -> dict[str, dict[str, Any]]` — Load the current bundle manifest from disk.
- `def ensure_build_available(bundle_name: str, entry_path: str | None=None) -> None` — Fail fast when a production bundle manifest or entry is missing.
- `def asset_root(bundle_name: str) -> Path` — Return the directory `oldman <service> static collect` published this bundle into.
- `def asset_base_url(bundle_name: str) -> str` — Return the base URL used by frontend runtime asset loading.
- `def asset_url(bundle_name: str, asset_path: str) -> str` — Resolve a static asset URL for a bundle.
- `def client_tags(bundle_name: str) -> Markup` — Render dev client tags for a bundle.
- `def styles_tags(bundle_name: str, entry_path: str | None=None) -> Markup` — Render stylesheet tags for an entry.
- `def modulepreload_tags(bundle_name: str, entry_path: str | None=None) -> Markup` — Render modulepreload tags for an entry.
- `def script_tags(bundle_name: str, entry_path: str | None=None) -> Markup` — Render module script tags for an entry.
- `def install_template_globals(environment: Any) -> None` — Expose the tag helpers to templates as the `bundle_*` globals every shell base uses.
- `def entry_tags(bundle_name: str, entry_path: str | None=None, include_dev_client: bool=False) -> Markup` — Render client, modulepreload, CSS and script tags for an entry.

## `StaticCollectionConflict`

class · defined in `oldman.web.staticfiles.collector`

```python
class StaticCollectionConflict
```

One duplicate logical path ignored because an earlier source won.

Members:

- `relative_path: str`
- `winner: str`
- `ignored: str`

## `StaticCollectionResult`

class · defined in `oldman.web.staticfiles.collector`

```python
class StaticCollectionResult
```

Summary returned by a deterministic static collection run.

Members:

- `copied: int`
- `unchanged: int`
- `removed: int`
- `conflicts: tuple[StaticCollectionConflict, ...]`
- `destination: Path`

## `StaticSource`

class · defined in `oldman.web.staticfiles.finders`

```python
class StaticSource
```

One ordered static source consumed by the collection process.

Members:

- `name: str`
- `root: Traversable`
- `package_owned: bool = False`
- `def iter_files() -> Iterator[StaticSourceFile]` — Yield source files in stable logical-path order.

## `StaticSourceFile`

class · defined in `oldman.web.staticfiles.finders`

```python
class StaticSourceFile
```

One readable source file and its public path inside the collection root.

Members:

- `source_name: str`
- `relative_path: PurePosixPath`
- `resource: Traversable`
- `def read_bytes() -> bytes` — Read the source through the Traversable API used by installed wheels.
