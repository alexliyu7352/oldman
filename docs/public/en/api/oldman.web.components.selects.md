# `oldman.web.components.selects`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Oldman 后端 Select/Autocomplete 组件入口。

Import with `from oldman.web.components.selects import <name>`.

## `DataSelectProvider`

class · defined in `oldman.web.components.selects.providers`

```python
class DataSelectProvider(SelectProvider)
```

结构化数据 Select/Autocomplete provider。

Members:

- `async def get_choices(request: Any, context: SelectContext) -> Sequence[object]` — 返回结构化候选数据。
- `async def search(request: Any, context: SelectContext, *, term: str, depends: dict[str, str], page: int, page_size: int) -> SelectResult` — 在 Python 层完成结构化数据搜索和分页。
- `async def filter_queryset(request: Any, context: SelectContext, choices: Sequence[object], term: str, depends: dict[str, str]) -> Sequence[object]` — 按文本标签执行默认大小写不敏感搜索。
- `async def get_initial(request: Any, context: SelectContext, values: list[str], depends: dict[str, str]) -> list[SelectChoice]` — 按输入 values 顺序回显当前可见候选。
- `def get_option(obj: object) -> SelectChoice` — 默认支持 (value, label)、dict 和普通对象。

## `ModelSelectProvider`

class · defined in `oldman.web.components.selects.providers`

```python
class ModelSelectProvider(SelectProvider)
```

SQLAlchemy Select/Autocomplete provider 基类。

Members:

- `database_manager: DatabaseManager = default_db_manager`
- `model: type[Any] | None = None`
- `search_fields: tuple[str, ...] | list[str] = ()`
- `label_field: str = 'name'`
- `value_field: str = 'id'`
- `async def handle_request(request: Any, *, context: SelectContext) -> dict[str, Any]` — 在同一个只读 session 内处理数据库型 provider 请求。
- `async def get_queryset(request: Any, context: SelectContext)` — 返回基础 SQLAlchemy 查询。
- `async def search(request: Any, context: SelectContext, *, term: str, depends: dict[str, str], page: int, page_size: int) -> SelectResult` — 执行数据库搜索分页查询。
- `async def filter_queryset(request: Any, context: SelectContext, query: Any, term: str, depends: dict[str, str])` — 按 search_fields 生成默认 SQL LIKE 搜索。
- `async def get_initial(request: Any, context: SelectContext, values: list[str], depends: dict[str, str]) -> list[SelectChoice]` — 按输入顺序读取初始值候选。
- `def get_option(obj: object) -> SelectChoice` — 把 SQLAlchemy model 实例转换为 SelectChoice。
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

远程选择器绑定签名无效。

## `SelectChoice`

class · defined in `oldman.web.components.selects.choices`

```python
class SelectChoice
```

后端选择器候选项。

Members:

- `id: Any`
- `text: str`
- `html: Markup | str | None = None`
- `selected: bool = False`
- `disabled: bool = False`
- `data: dict[str, object] | None = None`
- `def to_option(*, label_mode: Literal['text', 'html']='text') -> dict[str, object]` — 转换为前端 SelectOption JSON。

## `SelectContext`

class · defined in `oldman.web.components.selects.signing`

```python
class SelectContext
```

远程选择器签名绑定上下文。

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

Select/Autocomplete provider 基类。

Members:

- `page_size: int = 20`
- `max_page_size: int = 100`
- `db_session: AsyncSession | None = None`
- `async def handle_request(request: Any, *, context: SelectContext) -> dict[str, Any]` — 处理请求并把 provider 级业务错误转换为统一 API payload。
- `async def handle_valid_request(request: Any, *, context: SelectContext) -> dict[str, Any]` — 处理搜索分页或初始值回显请求。
- `async def check_auth(request: Any, context: SelectContext) -> bool` — 检查当前请求是否允许访问 provider。
- `async def search(request: Any, context: SelectContext, *, term: str, depends: dict[str, str], page: int, page_size: int) -> SelectResult` — 执行搜索分页查询。
- `async def get_initial(request: Any, context: SelectContext, values: list[str], depends: dict[str, str]) -> list[SelectChoice]` — 按输入顺序返回初始值可见候选。
- `def get_option(obj: object) -> SelectChoice` — 把候选对象转换为 SelectChoice。
- `def read_depends(request: Any, context: SelectContext) -> dict[str, str]` — 读取并校验白名单依赖字段。
- `def read_initial_values(request: Any) -> list[str]` — 读取单选 value 或多选 values 初始值。
- `def resolve_page_size(request: Any, context: SelectContext) -> int` — 解析分页大小并应用 provider 与签名上下文上限。

## `SelectProviderConfigError`

class · defined in `oldman.web.components.selects.providers`

```python
class SelectProviderConfigError(RuntimeError)
```

Provider 配置错误。

## `SelectProviderView`

class · defined in `oldman.web.components.selects.views`

```python
class SelectProviderView(HTTPMethodView)
```

Select/Autocomplete 中心 provider endpoint。

Constructor:

```python
SelectProviderView(*, registry: SelectRegistry=select_registry, secret_key: str) -> None
```

Members:

- `async def get(request: Any, provider_name: str)` — 验证 bind 并分发 provider。

## `SelectRegistry`

class · defined in `oldman.web.components.selects.registry`

```python
class SelectRegistry
```

保存 provider 名称到 Provider 类的轻量映射。

Constructor:

```python
SelectRegistry() -> None
```

Members:

- `def register(name: str)` — 注册 provider 类，名称冲突时直接失败。
- `def get(name: str) -> type | None` — 按名称返回 provider 类。
- `def names() -> tuple[str, ...]` — 返回已注册 provider 名称，供门禁和调试使用。

## `SelectResult`

class · defined in `oldman.web.components.selects.choices`

```python
class SelectResult
```

远程 Select/Autocomplete 正式 JSON 响应。

Members:

- `results: list[SelectChoice]`
- `more: bool = False`
- `def to_json(*, label_mode: Literal['text', 'html']='text') -> dict[str, object]` — 转换为正式前端协议 JSON。

## `sign_select_context`

function · defined in `oldman.web.components.selects.signing`

```python
def sign_select_context(context: SelectContext, *, secret_key: str) -> str
```

签名远程选择器上下文并返回前端 bind 值。

## `verify_select_context`

function · defined in `oldman.web.components.selects.signing`

```python
def verify_select_context(bind: str, *, secret_key: str) -> SelectContext
```

验证 bind 签名并恢复 SelectContext。
