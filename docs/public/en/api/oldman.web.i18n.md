# `oldman.web.i18n`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Web internationalization service.

Import with `from oldman.web.i18n import <name>`.

## `build_i18n_url`

function · defined in `oldman.web.i18n.translation`

```python
def build_i18n_url(app: WebApp, route_name: str, current_lang: str, target_lang: str | None=None, _lang: str | None=None, **kwargs: Any) -> str
```

Build an i18n URL through the configured process-level service.

## `build_i18n_url_with_request`

function · defined in `oldman.web.i18n.translation`

```python
def build_i18n_url_with_request(route: str, **kwargs: Any) -> str
```

Build an i18n URL from the current Sanic request.

## `current_language`

function · defined in `oldman.web.i18n.translation`

```python
def current_language(request: Any=None) -> str
```

The canonical language of a request: its resolved locale, then the language cookies, then the default.

## `ensure_frontend_catalogs`

function · defined in `oldman.web.i18n.assets`

```python
def ensure_frontend_catalogs(registry: StaticBundleRegistry, bundle_name: str, *, source_dir: Path | None=None) -> None
```

Fail fast when a configured language has no published browser catalog.

## `language_menu_items`

function · defined in `oldman.web.i18n.translation`

```python
def language_menu_items(request: Any=None) -> list[dict[str, Any]]
```

The language menu entries: code, locale, aliases, name, flag, flagUrl, is_current and url.

## `language_registry`

function · defined in `oldman.web.i18n.translation`

```python
def language_registry(request: Any=None) -> LanguageRegistry
```

The project's language registry: the initialized service's, else the settings', never empty.

## `language_switch_url`

function · defined in `oldman.web.i18n.translation`

```python
def language_switch_url(request: Any, language: str, *, default_language: str, use_i18n_path: bool) -> str
```

The current page in `language`: a path prefix when i18n paths are on, never a stale ?lang= override.

## `translation`

value · defined in `oldman.web.i18n.translation`

```python
translation = TranslationService()
```

## `TranslationService`

class · defined in `oldman.web.i18n.translation`

```python
class TranslationService
```

Own one project's immutable language registry and lazy catalog cache.

Constructor:

```python
TranslationService() -> None
```

Members:

- `property definitions: tuple[LanguageDefinition, ...]` — Return configured languages in stable project order.
- `def initialize(app: WebApp, config: I18nSettings, *, catalog_roots: Sequence[str | Path], public_domain: str='', static_url: str='') -> None` — Initialize the unique Sanic/Jinja environment exactly once.
- `def resolve_language(value: str | None) -> str` — Resolve a request value to a canonical configured code.
- `def get_translations(language: str) -> Translations` — Return the lazily loaded catalog for a code, locale, or alias.
- `def get_locale(request: Request, *, auto_detect: bool=True) -> str` — Select a canonical request language using the migrated priority order.
- `def build_url(app: WebApp, route_name: str, current_language: str, *, target_language: str | None=None, **kwargs: Any) -> str` — Build a route URL with a non-default canonical language prefix.

## Module `oldman.web.i18n.assets`

Published browser i18n assets: language flags, and the catalogs the frontend expects.

Import with `from oldman.web.i18n.assets import <name>`.

### `BUILTIN_FLAG_ASSETS`

value · defined in `oldman.web.i18n.assets`

```python
BUILTIN_FLAG_ASSETS: Final = MappingProxyType({'cn': oldman_asset_path('images/flags/cn.svg'), 'tw': oldman_asset_path('images/f…
```

### `direct_flag_url`

function · defined in `oldman.web.i18n.assets`

```python
def direct_flag_url(value: str, *, static_url: str) -> str
```

Resolve one language flag against the configured public static prefix.

## Module `oldman.web.i18n.frontend_build`

从统一的 gettext 目录生成浏览器用的 JSON 语言包与语言清单。

Import with `from oldman.web.i18n.frontend_build import <name>`.

### `build_frontend_i18n`

function · defined in `oldman.web.i18n.frontend_build`

```python
def build_frontend_i18n(output_dir: Path, locales_dir: Path, settings_file: Path, languages_output: Path, *, compiler_command: Sequence[str] | None=None, project_root: Path=Path.cwd()) -> None
```

按项目配置编译、校验并原子发布一整套浏览器语言包与清单。

### `build_language_aliases`

function · defined in `oldman.web.i18n.frontend_build`

```python
def build_language_aliases(languages: list[dict[str, object]]) -> dict[str, str]
```

Generate canonical browser aliases from the settings registry.

### `catalog_filename`

function · defined in `oldman.web.i18n.frontend_build`

```python
def catalog_filename(language_code: str) -> str
```

Convert one canonical language code into its catalog filename.

### `project_frontend_paths`

function · defined in `oldman.web.i18n.frontend_build`

```python
def project_frontend_paths(project_root: Path, *, service: str='web') -> dict[str, Path]
```

项目约定的四个位置：settings、locales、浏览器目录输出、语言清单输出。

### `read_i18n_contract`

function · defined in `oldman.web.i18n.frontend_build`

```python
def read_i18n_contract(settings_file: Path) -> tuple[str, list[dict[str, object]], str, str]
```

Read one consistent snapshot: default language, languages, static URL, language preference endpoint.

### `validate_catalog_directory`

function · defined in `oldman.web.i18n.frontend_build`

```python
def validate_catalog_directory(output_dir: Path, configured_languages: list[dict[str, object]]) -> None
```

Ensure staging contains exactly one valid catalog per configured language.

### `write_language_catalogs`

function · defined in `oldman.web.i18n.frontend_build`

```python
def write_language_catalogs(output_dir: Path, locales_dir: Path, configured_languages: list[dict[str, object]], *, compiler_command: Sequence[str] | None=None, project_root: Path=Path.cwd()) -> None
```

Compile the complete configured set from unified ``messages.po`` files.

### `write_language_manifest`

function · defined in `oldman.web.i18n.frontend_build`

```python
def write_language_manifest(output_file: Path, settings_file: Path) -> None
```

Generate the browser language index without duplicating locale identity.

### `write_language_manifest_data`

function · defined in `oldman.web.i18n.frontend_build`

```python
def write_language_manifest_data(output_file: Path, default_language: str, languages: list[dict[str, object]], *, static_url: str, preference_url: str) -> None
```

Write a manifest from the same validated settings snapshot as catalogs.

## Module `oldman.web.i18n.request`

Sanic Request subclass for language-prefixed routes.

Import with `from oldman.web.i18n.request import <name>`.

### `I18nRequest`

class · defined in `oldman.web.i18n.request`

```python
class I18nRequest(SanicRequest)
```

Strip a configured language prefix before Sanic route matching.

Constructor:

```python
I18nRequest(*args: Any, **kwargs: Any) -> None
```

## Module `oldman.web.i18n.translation`

Process-level Web translation service.

Import with `from oldman.web.i18n.translation import <name>`.

### `I18nSettings`

class · defined in `oldman.web.i18n.translation`

```python
class I18nSettings(Protocol)
```

Settings fields required by the Web translation service.

Members:

- `property default_language: str` — Return the configured default language value.
- `property languages: Mapping[str, object]` — Return canonical project language definitions.
- `property use_i18n_path: bool` — Return whether language-prefixed routes are enabled.
