# `oldman.web.components.selects`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Backend Oldman Select/Autocomplete component entry point.

Import with `from oldman.web.components.selects import <name>`.

## `DataSelectProvider`

class · defined in `oldman.web.components.selects.providers`

```python
class DataSelectProvider(SelectProvider)
```

Select/Autocomplete provider for structured data.

Members:

- `async def get_choices(request: Any, context: SelectContext) -> Sequence[object]` — Return structured candidate data.
- `async def search(request: Any, context: SelectContext, *, term: str, depends: dict[str, str], page: int, page_size: int) -> SelectResult` — Search and paginate structured data in Python.
- `async def filter_queryset(request: Any, context: SelectContext, choices: Sequence[object], term: str, depends: dict[str, str]) -> Sequence[object]` — Search text labels case-insensitively by default.
- `async def get_initial(request: Any, context: SelectContext, values: list[str], depends: dict[str, str]) -> list[SelectChoice]` — Display currently visible candidates in supplied values order.
- `def get_option(obj: object) -> SelectChoice` — Support value/label pairs, dicts, and ordinary objects by default.

## `ModelSelectProvider`

class · defined in `oldman.web.components.selects.providers`

```python
class ModelSelectProvider(SelectProvider)
```

Base class for SQLAlchemy Select/Autocomplete providers.

Members:

- `database_manager: DatabaseManager = default_db_manager`
- `model: type[Any] | None = None`
- `search_fields: tuple[str, ...] | list[str] = ()`
- `label_field: str = 'name'`
- `value_field: str = 'id'`
- `async def handle_request(request: Any, *, context: SelectContext) -> dict[str, Any]` — Handle database-provider requests within one read-only session.
- `async def get_queryset(request: Any, context: SelectContext)` — Return the base SQLAlchemy query.
- `async def search(request: Any, context: SelectContext, *, term: str, depends: dict[str, str], page: int, page_size: int) -> SelectResult` — Run a paginated database search.
- `async def filter_queryset(request: Any, context: SelectContext, query: Any, term: str, depends: dict[str, str])` — Build default SQL LIKE searches from search_fields.
- `async def get_initial(request: Any, context: SelectContext, values: list[str], depends: dict[str, str]) -> list[SelectChoice]` — Read initial-value candidates in input order.
- `def get_option(obj: object) -> SelectChoice` — Convert a SQLAlchemy model instance to SelectChoice.
- `def require_db_session() -> AsyncSession` — Return the request-scoped SQLAlchemy session.

## `select_registry`

value · defined in `oldman.web.components.selects.registry`

```python
select_registry = SelectRegistry()
```

## `SelectBindError`

class · defined in `oldman.web.components.selects.signing`

```python
class SelectBindError(ValueError)
```

Invalid remote-selector binding signature.

## `SelectChoice`

class · defined in `oldman.web.components.selects.choices`

```python
class SelectChoice
```

A backend selector choice.

Members:

- `id: Any`
- `text: str`
- `html: Markup | str | None = None`
- `selected: bool = False`
- `disabled: bool = False`
- `data: dict[str, object] | None = None`
- `def to_option(*, label_mode: Literal['text', 'html']='text') -> dict[str, object]` — Convert to browser SelectOption JSON.

## `SelectContext`

class · defined in `oldman.web.components.selects.signing`

```python
class SelectContext
```

Signed remote-selector binding context.

Members:

- `provider: str`
- `field_name: str`
- `multiple: bool`
- `dependent_fields: tuple[str, ...]`
- `page_size: int`
- `value_field: str`
- `label_mode: Literal['text', 'html']`

## `SelectProvider`

class · defined in `oldman.web.components.selects.providers`

```python
class SelectProvider
```

Base class for Select/Autocomplete providers.

Members:

- `page_size: int = 20`
- `max_page_size: int = 100`
- `db_session: AsyncSession | None = None`
- `async def handle_request(request: Any, *, context: SelectContext) -> dict[str, Any]` — Handle requests and convert provider business errors to common API payloads.
- `async def handle_valid_request(request: Any, *, context: SelectContext) -> dict[str, Any]` — Handle paginated searches or initial-value display requests.
- `async def check_auth(request: Any, context: SelectContext) -> bool` — Check whether the current request may access the provider.
- `async def search(request: Any, context: SelectContext, *, term: str, depends: dict[str, str], page: int, page_size: int) -> SelectResult` — Run a paginated search query.
- `async def get_initial(request: Any, context: SelectContext, values: list[str], depends: dict[str, str]) -> list[SelectChoice]` — Return visible initial-value candidates in input order.
- `def get_option(obj: object) -> SelectChoice` — Convert a candidate object to SelectChoice.
- `def read_depends(request: Any, context: SelectContext) -> dict[str, str]` — Read and validate allowlisted dependent fields.
- `def read_initial_values(request: Any) -> list[str]` — Read initial single value or multiple values.
- `def resolve_page_size(request: Any, context: SelectContext) -> int` — Parse page size and apply provider and signed-context limits.

## `SelectProviderConfigError`

class · defined in `oldman.web.components.selects.providers`

```python
class SelectProviderConfigError(RuntimeError)
```

Provider configuration error.

## `SelectProviderView`

class · defined in `oldman.web.components.selects.views`

```python
class SelectProviderView(HTTPMethodView)
```

Central Select/Autocomplete provider endpoint.

Constructor:

```python
SelectProviderView(*, registry: SelectRegistry=select_registry, secret_key: str) -> None
```

Members:

- `async def get(request: Any, provider_name: str)` — Validate bind and dispatch to the provider.

## `SelectRegistry`

class · defined in `oldman.web.components.selects.registry`

```python
class SelectRegistry
```

A lightweight mapping from provider names to provider classes.

Constructor:

```python
SelectRegistry() -> None
```

Members:

- `def register(name: str)` — Register a provider class, failing on name conflicts.
- `def get(name: str) -> type | None` — Return the named provider class.
- `def names() -> tuple[str, ...]` — Return registered provider names for gates and debugging.

## `SelectResult`

class · defined in `oldman.web.components.selects.choices`

```python
class SelectResult
```

Canonical remote Select/Autocomplete JSON response.

Members:

- `results: list[SelectChoice]`
- `more: bool = False`
- `def to_json(*, label_mode: Literal['text', 'html']='text') -> dict[str, object]` — Convert to the canonical browser JSON protocol.

## `sign_select_context`

function · defined in `oldman.web.components.selects.signing`

```python
def sign_select_context(context: SelectContext, *, secret_key: str) -> str
```

Sign a remote-selector context and return the browser bind value.

## `verify_select_context`

function · defined in `oldman.web.components.selects.signing`

```python
def verify_select_context(bind: str, *, secret_key: str) -> SelectContext
```

Verify the bind signature and restore SelectContext.
