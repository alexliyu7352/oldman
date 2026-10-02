# `oldman.i18n`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Runtime-independent internationalization API.

Import with `from oldman.i18n import <name>`.

## `_`

value · defined in `oldman.i18n`

```python
_ = gettext_lazy
```

## `bind_translations`

function · defined in `oldman.i18n.translations`

```python
def bind_translations(catalog: TranslationCatalog) -> Token[TranslationCatalog | None]
```

Bind a request catalog without importing a Web runtime from this module.

## `canonical_language_code`

function · defined in `oldman.i18n.utils`

```python
def canonical_language_code(value: str) -> str
```

Return the public canonical form of one configured language code.

## `CatalogLoader`

class · defined in `oldman.i18n.catalogs`

```python
class CatalogLoader
```

Load and merge gettext catalogs from explicit high-to-low priority roots.

Constructor:

```python
CatalogLoader(roots: Iterable[str | Path], *, domains: Iterable[str]=('messages', 'countries')) -> None
```

Members:

- `def load(locale: str) -> Translations` — Load one locale, allowing higher-priority roots to override lower ones.

## `gettext`

function · defined in `oldman.i18n.translations`

```python
def gettext(message: str, request: Any | None=None, **variables: Any) -> str
```

Translate a singular message, falling back to the source string outside Web requests.

## `gettext_lazy`

function · defined in `oldman.i18n.translations`

```python
def gettext_lazy(message: str, **variables: Any) -> LazyTranslation
```

Create a lazy singular translation.

## `gettext_noop`

function · defined in `oldman.i18n.translations`

```python
def gettext_noop(message: str) -> str
```

Mark deferred source text for extraction without translating it.

## `language_code_variants`

function · defined in `oldman.i18n.registry`

```python
def language_code_variants(value: str) -> tuple[str, ...]
```

Return canonical and case-insensitive lookup forms for one language value.

## `LanguageDefinition`

class · defined in `oldman.i18n.registry`

```python
class LanguageDefinition
```

One canonical project language and its accepted external aliases.

Members:

- `code: str`
- `aliases: tuple[str, ...]`
- `name: str`
- `flag: str`
- `property babel_locale: str` — Return the derived gettext filesystem identifier.
- `classmethod def from_config(code: str, config: object) -> LanguageDefinition` — Merge generic metadata, an optional built-in profile, and user overrides.

## `LanguageRegistry`

class · defined in `oldman.i18n.registry`

```python
class LanguageRegistry
```

Resolve configured codes, locales, and aliases to canonical project languages.

Constructor:

```python
LanguageRegistry(languages: Mapping[str, object]) -> None
```

Members:

- `property codes: tuple[str, ...]` — Return canonical language codes in configuration order.
- `def resolve(value: str | None) -> str` — Resolve a code, locale, or configured alias to one canonical code.
- `def definition(value: str) -> LanguageDefinition` — Return the definition for a code, locale, or alias.
- `def babel_locale_for(value: str) -> str` — Return the Babel/gettext locale for a configured language.

## `LazyTranslation`

class · defined in `oldman.i18n.translations`

```python
class LazyTranslation
```

Resolve a message only when converted to text.

Constructor:

```python
LazyTranslation(singular: str, plural: str | None=None, n: int | None=None, **variables: Any) -> None
```

## `N_`

value · defined in `oldman.i18n`

```python
N_ = ngettext_lazy
```

## `ngettext`

function · defined in `oldman.i18n.translations`

```python
def ngettext(singular: str, plural: str, n: int, request: Any | None=None, **variables: Any) -> str
```

Translate a plural message, falling back to the matching source string.

## `ngettext_lazy`

function · defined in `oldman.i18n.translations`

```python
def ngettext_lazy(singular: str, plural: str, n: int, **variables: Any) -> LazyTranslation
```

Create a lazy plural translation.

## `normalize_lang_code`

function · defined in `oldman.i18n.utils`

```python
def normalize_lang_code(lang: str) -> str
```

Validate and return one canonical Babel-supported BCP 47 language tag.

## `pgettext`

function · defined in `oldman.i18n.translations`

```python
def pgettext(context: str, message: str, request: Any | None=None, **variables: Any) -> str
```

Translate a contextual message, falling back to the source string.

## `reset_translations`

function · defined in `oldman.i18n.translations`

```python
def reset_translations(token: Token[TranslationCatalog | None]) -> None
```

Restore the translation context associated with a completed request.

## `TranslatableMsgspecModel`

class · defined in `oldman.i18n.serialization`

```python
class TranslatableMsgspecModel(MsgspecModel)
```

Strong model whose nested LazyTranslation values survive MessagePack.

Members:

- `def to_dict() -> dict[str, Any]` — Resolve nested lazy translations into frontend-safe builtins.

## Module `oldman.i18n.frontend`

Packaged message metadata shared by Python and ``oldman-web``.

Import with `from oldman.i18n.frontend import <name>`.

### `compile_project_frontend_catalog`

function · defined in `oldman.i18n.frontend`

```python
def compile_project_frontend_catalog(project_root: Path, po_file: Path, *, fallback_locale: str, compiler_command: Sequence[str] | None=None) -> dict[str, object]
```

Compile and filter one project's browser catalog from ``messages.po``.

### `extract_project_frontend_messages`

function · defined in `oldman.i18n.frontend`

```python
def extract_project_frontend_messages(project_root: Path, *, compiler_command: Sequence[str] | None=None) -> tuple[FrontendMessage, ...]
```

Extract one project's ``frontend/src`` with the published AST tool.

### `filter_frontend_catalog_payload`

function · defined in `oldman.i18n.frontend`

```python
def filter_frontend_catalog_payload(payload: object, messages: Iterable[FrontendMessage]) -> dict[str, object]
```

Keep only AST-discovered identities in one compiled browser catalog.

### `frontend_catalog_messages`

function · defined in `oldman.i18n.frontend`

```python
def frontend_catalog_messages(catalog: Any) -> dict[str, str | list[str]]
```

Translate all packaged frontend messages with one Babel catalog.

### `frontend_catalog_payload`

function · defined in `oldman.i18n.frontend`

```python
def frontend_catalog_payload(catalog: Any, locale: str) -> dict[str, object]
```

Build one browser catalog with translated messages and its plural rule.

### `frontend_messages_from_manifest`

function · defined in `oldman.i18n.frontend`

```python
def frontend_messages_from_manifest(payload: object) -> tuple[FrontendMessage, ...]
```

Validate one AST extractor manifest and return typed message identities.

### `FrontendMessage`

class · defined in `oldman.i18n.frontend`

```python
class FrontendMessage
```

One unique frontend gettext identity and all of its source locations.

Members:

- `id: str`
- `context: str | None`
- `plural: str | None`
- `locations: tuple[FrontendMessageLocation, ...]`
- `property catalog_key: str` — Return the key used by the browser translation catalog.
- `property babel_id: str | tuple[str, str]` — Return the singular or plural ID accepted by Babel's Catalog.

### `FrontendMessageLocation`

class · defined in `oldman.i18n.frontend`

```python
class FrontendMessageLocation
```

Repository-relative location of one frontend translation call.

Members:

- `path: str`
- `line: int`

### `oldman_web_messages`

function · defined in `oldman.i18n.frontend`

```python
def oldman_web_messages() -> tuple[FrontendMessage, ...]
```

Load and validate the generated ``oldman-web`` message manifest.

## Module `oldman.i18n.profiles`

Built-in metadata for commonly configured languages.

Import with `from oldman.i18n.profiles import <name>`.

### `BUILTIN_LANGUAGE_PROFILES`

value · defined in `oldman.i18n.profiles`

```python
BUILTIN_LANGUAGE_PROFILES: Final = MappingProxyType({'en': MappingProxyType({'aliases': ('en-US',), 'name': 'English', 'flag': ''}), '…
```

## Module `oldman.i18n.translations`

Core-safe translation functions shared by CLI and Web consumers.

Import with `from oldman.i18n.translations import <name>`.

### `current_translations`

value · defined in `oldman.i18n.translations`

```python
current_translations: ContextVar[TranslationCatalog | None] = ContextVar('current_translations', default=None)
```

### `TranslationCatalog`

class · defined in `oldman.i18n.translations`

```python
class TranslationCatalog(Protocol)
```

Small Babel-compatible catalog contract used by the public helpers.

Members:

- `def gettext(message: str, /) -> str`
- `def ngettext(singular: str, plural: str, n: int, /) -> str`
- `def pgettext(context: str, message: str, /) -> str | object`
