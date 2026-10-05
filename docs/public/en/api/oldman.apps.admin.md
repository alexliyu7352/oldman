# `oldman.apps.admin`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Built-in Admin application.

Import with `from oldman.apps.admin import <name>`.

## `AdminSite`

class · defined in `oldman.apps.admin.site`

```python
class AdminSite
```

Registry and route installer for the built-in Admin site.

Constructor:

```python
AdminSite(name: str='oldman_admin', *, app_registry: AppRegistry | None=None) -> None
```

Members:

- `def bind_app_registry(registry: AppRegistry) -> None` — Bind the current service Registry without rebuilding registered Admins.
- `def get_model_metadata(model: type[Any]) -> ModelMetadata | None` — Return current service metadata, or None for standalone AdminSite use.
- `def register(model: type[Any], admin_class: type[ModelAdmin] | None=None) -> ModelAdmin` — Register a model with an optional ModelAdmin class.
- `def is_registered(model: type[Any]) -> bool` — Whether the model has a ModelAdmin on this site.
- `def unregister(model: type[Any]) -> None` — Unregister a model.
- `def register_user_model(model: type[Any]) -> ModelAdmin` — Register the configured Admin user model as the sole user manager.
- `def get_model_admin(model: type[Any]) -> ModelAdmin` — Return admin for model.
- `def each_model_admin() -> list[RegisteredModelAdmin]` — Return registered admins in menu order.
- `async def menu_items(request: Any) -> list[dict[str, Any]]` — Return neutral menu metadata for the models this request may view, under the installed prefix.
- `async def menu_groups(request: Any) -> list[dict[str, Any]]` — Group the models this request may view under their menu group's App for sidebar rendering.
- `def register_routes(app: WebApp, *, db_manager: DatabaseManager | None=None, auth_settings: AuthSettings | None=None, admin_settings: AdminSettings | None=None, notification_routes: NotificationRoutes | None=None, password_reset_rate_limiter: RateLimiter | None=None, login_rate_limit: LoginRateLimit | None=None) -> str | None` — Install neutral Admin CRUD routes into a Sanic app, under `admin_settings.prefix`.

## `AdminUserManagementError`

class · defined in `oldman.auth.services`

```python
class UserManagementError(ValueError)
```

A rejected user-management operation (self-disable, deleting a superuser, ...).

## `AdminUserModelAdmin`

class · defined in `oldman.apps.admin.model_admin`

```python
class AdminUserModelAdmin(ModelAdmin)
```

Complete user manager for the configured Admin user model protocol.

Constructor:

```python
AdminUserModelAdmin(model: type[Any], site: Any=None) -> None
```

Members:

- `property verbose_name: str` — Keep the source user-manager singular label independent of model class name.
- `property verbose_name_plural: str` — Keep the source user-manager plural label independent of model class name.
- `def permission(action: str) -> Permission` — User management checks the auth App's permissions, not Admin model permissions.
- `def get_list_card_title() -> str` — Keep the source user list card title extractable as one message.
- `def get_add_button_label() -> str` — Keep the source user add action extractable as one message.
- `def get_delete_label() -> str` — Keep the source user delete action extractable as one message.
- `def get_form_page_title(instance: Any | None) -> str` — Mirror the source create/edit page heading.
- `def get_form_submit_label(instance: Any | None) -> str` — Keep the source user form's shared default submit copy.
- `def get_list_display() -> tuple[str, ...]` — Restore the source user profile and status columns.
- `def get_search_fields() -> tuple[str, ...]` — Search the source user identity and profile fields.
- `def get_table_columns() -> tuple[object, ...]` — Keep the source user-management header contract.
- `def build_filter_form(request: Any) -> Any | None` — Bind the shared Admin user filter form to the list query.
- `def build_form(request: Any, *, instance: Any | None=None, session: Any=None)` — Use dedicated create/edit forms without exposing password hashes.
- `def build_password_form(request: Any, *, session: Any=None)` — Bind the shared password-policy form.
- `def get_form_success_payload(instance: Any, *, created: bool, admin_prefix: str) -> dict[str, Any]` — Preserve the source user Form redirect, toast and notification contract.
- `def table_cell_value(instance: Any, field_name: str, *, admin_prefix: str) -> Any` — Render source-compatible identity links, status badges and login state.
- `def table_action_html(instance: Any, *, admin_prefix: str) -> Markup` — Expose edit, password, status and delete through the shared Dropdown.
- `def change_password(instance: Any, raw_password: str) -> None` — Replace a password through the configured user model protocol.
- `def set_active(instance: Any, is_active: bool, *, current_user_id: int | None) -> None` — Apply the source self-disable protection.
- `def validate_delete(instance: Any, *, current_user_id: int | None) -> None` — Protect the current user and every superuser from deletion.

## `install_admin`

function · defined in `oldman.apps.admin.runtime`

```python
def install_admin(app: Any, *, db_manager: DatabaseManager | None=None, admin_site: AdminSite | None=None, dev_mode: bool=False, dev_server_url: str='', extension_bundle_name: str | None=None, auth_settings: AuthSettings | None=None, admin_settings: AdminSettings | None=None, password_reset_rate_limiter: RateLimiter | None=None, login_rate_limit: LoginRateLimit | None=None) -> AdminSite
```

Install Admin routes, templates and the collected frontend bundle under `AdminSettings.prefix`.

## `ModelAdmin`

class · defined in `oldman.apps.admin.model_admin`

```python
class ModelAdmin
```

SQLAlchemy metadata-driven Admin CRUD controller.

Constructor:

```python
ModelAdmin(model: type[Any], site: Any=None) -> None
```

Members:

- `list_display: Sequence[str] = ()`
- `search_fields: Sequence[str] = ()`
- `readonly_fields: Sequence[str] = ()`
- `ordering: Sequence[str] = ()`
- `exclude: Sequence[str] = ()`
- `table_toolbar: Sequence[str] = ('columns', 'density', 'export')`
- `export_formats: Sequence[str] = ('csv',)`
- `form_back_label: str | None = None`
- `menu_group: str | None = None`
- `property model_name: str` — Return model class name.
- `def get_model_metadata() -> ModelMetadata | None` — Return Registry metadata when this AdminSite has a bound App Registry.
- `property verbose_name: Any` — Return human-readable singular name.
- `property verbose_name_plural: Any` — Return human-readable plural name.
- `property model_path: str` — Return URL-safe model path.
- `def get_primary_key_column() -> Column[Any]` — Return the single-column primary key used by built-in CRUD.
- `def get_columns() -> list[Column[Any]]` — Return mapped table columns.
- `def get_list_display() -> tuple[str, ...]` — Return columns shown in list pages.
- `def get_search_fields() -> tuple[str, ...]` — Return searchable text fields.
- `def get_table_columns() -> tuple[object, ...]` — Return shared Table column declarations for the list page.
- `def get_readonly_fields() -> tuple[str, ...]` — Return readonly fields.
- `def get_ordering() -> tuple[str, ...]` — Return default ordering.
- `def get_form_class(*, create: bool=True, dialect: Any=None) -> type[Any]` — Return a generated form class backed by the shared Oldman renderer.
- `def build_form(request: Any, *, instance: Any | None=None, session: Any=None)` — Bind the generated shared ModelForm to an Admin request.
- `def get_edit_extra_buttons(instance: Any, admin_prefix: str) -> Markup` — Return optional shared Form action controls for an edit page.
- `def get_list_card_title() -> str` — Return the list card title as one translatable message.
- `def get_add_button_label() -> str` — Return the add button label as one translatable message.
- `def get_delete_label() -> str` — Return the delete page action label as one translatable message.
- `def get_form_document_title(instance: Any | None) -> str` — Return the document title for the ordinary create/edit page.
- `def get_form_page_title(instance: Any | None) -> str` — Return the visible heading for the ordinary create/edit page.
- `def get_form_card_title(instance: Any | None) -> str` — Return the optional form-card heading.
- `def get_form_submit_label(instance: Any | None) -> str` — Return the ordinary create/edit submit label.
- `def row_value(instance: Any, field_name: str) -> Any` — Return a display value for a list cell.
- `def table_cell_value(instance: Any, field_name: str, *, admin_prefix: str) -> Any` — Return a field display value for the shared Admin Table.
- `def table_action_html(instance: Any, *, admin_prefix: str) -> Markup` — Return row actions for the shared Admin Table.
- `def object_pk(instance: Any) -> Any` — Return the object primary key value.
- `def get_object_url(instance: Any, *, admin_prefix: str, action: str | None=None) -> str` — Build a canonical Admin URL from an object's encoded primary-key segment.
- `async def get_object(session: AsyncSession, object_id: Any) -> Any | None` — Return one object by primary key.
- `async def save_model(session: AsyncSession, instance: Any) -> Any` — Persist a model instance.
- `async def delete_model(session: AsyncSession, instance: Any) -> None` — Delete a model instance.
- `async def after_save(request: Any, instance: Any, *, created: bool) -> None` — Called once the transaction that saved the object has committed; does nothing by default.
- `async def after_delete(request: Any, instance: Any) -> None` — Called once the transaction that deleted the object has committed; does nothing by default.
- `def permission(action: str) -> Permission` — This model's permission for one action: ``admin.<app label>.<model>.<action>``.
- `async def has_view_permission(request: Any, obj: Any=None) -> bool` — Whether the request may view this model, or this object when one is given.
- `async def has_add_permission(request: Any) -> bool` — Whether the request may add rows of this model.
- `async def has_change_permission(request: Any, obj: Any=None) -> bool` — Whether the request may change this model, or this object when one is given.
- `async def has_delete_permission(request: Any, obj: Any=None) -> bool` — Whether the request may delete from this model, or this object when one is given.

## `site`

value · defined in `oldman.apps.admin.site`

```python
site = AdminSite()
```

## Module `oldman.apps.admin.apps`

Installable Admin application metadata.

Import with `from oldman.apps.admin.apps import <name>`.

### `AdminAppConfig`

class · defined in `oldman.apps.admin.apps`

```python
class AdminAppConfig(AppConfig[AdminSettings])
```

Describe the built-in Admin application and its settings owner.

### `app`

value · defined in `oldman.apps.admin.apps`

```python
app = AdminAppConfig()
```

## Module `oldman.apps.admin.roles`

The Admin page for roles, registered when the service installs ``oldman.apps.roles``.

Import with `from oldman.apps.admin.roles import <name>`.

### `RoleModelAdmin`

class · defined in `oldman.apps.admin.roles`

```python
class RoleModelAdmin(ModelAdmin)
```

Roles edited with the shared RoleForm; each save or delete refreshes the role's cache key.

Members:

- `def get_form_class(*, create: bool=True, dialect: Any=None) -> type[Any]` — Every role is edited through the same form: name, description and grouped permission checkboxes.
- `async def after_save(request: Any, instance: Any, *, created: bool) -> None` — Write the saved permissions to the role's cache key.
- `async def delete_model(session: Any, instance: Any) -> None` — Drop the role's cache key first, inside the transaction, then delete the row.
- `async def after_delete(request: Any, instance: Any) -> None` — Drop the key once more after the commit.

## Module `oldman.apps.admin.settings`

Strongly typed settings owned by the Admin application.

Import with `from oldman.apps.admin.settings import <name>`.

### `AdminSettings`

class · defined in `oldman.apps.admin.settings`

```python
class AdminSettings(BaseModel)
```

Configure access policy specific to the built-in Admin UI.

Members:

- `require_superuser: bool = Field(default=False, description='Require superuser access to Admin')`
- `prefix: str = Field(default='/admin', description='URL path the Admin is mounted under; its own pages (login, sig…`
- `classmethod def validate_prefix(value: str) -> str` — A same-site path below the site root; a trailing slash is dropped so pages join it with one.

## Module `oldman.apps.admin.staticfiles`

Built-in Admin static bundle registration.

Import with `from oldman.apps.admin.staticfiles import <name>`.

### `ADMIN_BUNDLE_NAME`

value · defined in `oldman.apps.admin.staticfiles`

```python
ADMIN_BUNDLE_NAME = 'oldman:admin'
```

### `ADMIN_ENTRY_PATH`

value · defined in `oldman.apps.admin.staticfiles`

```python
ADMIN_ENTRY_PATH = 'src/main.ts'
```

### `ADMIN_STATIC_PATH`

value · defined in `oldman.apps.admin.staticfiles`

```python
ADMIN_STATIC_PATH = oldman_asset_path('admin')
```

### `register_admin_static_bundle`

function · defined in `oldman.apps.admin.staticfiles`

```python
def register_admin_static_bundle(registry: StaticBundleRegistry, *, static_root: str | Path | None=None, static_url: str='', dev_mode: bool=False, dev_server_url: str='') -> StaticBundle
```

Register Admin against collected output or its explicit dev server.

## Module `oldman.apps.admin.table`

Admin adapter for the shared Oldman table component.

Import with `from oldman.apps.admin.table import <name>`.

### `AdminModelTable`

class · defined in `oldman.apps.admin.table`

```python
class AdminModelTable(SQLAlchemyTableView)
```

Expose a ModelAdmin through the framework Table renderer and protocol.

Constructor:

```python
AdminModelTable(request: Any, *, model_admin: ModelAdmin, db_manager: DatabaseManager, admin_prefix: str, permission_denied_response: Callable[[Any], Any] | None=None) -> None
```

Members:

- `async def check_permission(request: Any, *, method_name: str, route_kwargs: dict[str, object]) -> tuple[bool, str | None]` — The model's view permission, which carries the Admin's own floor (staff, or superuser when required).
- `async def on_authentication_required(request: Any, response_mode: Literal['html', 'json'], *, method_name: str) -> Any` — A signed-out request is sent to the Admin's login page, not the site's.
- `def export_filename(export_format: str) -> str` — Name downloads after the model path instead of the internal route name.
- `async def render_permission_denied_response(request: Any, message: str | None=None)` — Preserve the Admin site's authentication and permission response.
- `async def get_queryset()` — Return the registered model query consumed by SQLAlchemyTableView.
- `async def apply_filters(query: Any, /, table_request: Any)` — Reject filters outside this Table adapter's private allowlist.
- `def get_cell_values(row: object, column: Column, context: Mapping[str, object], *, row_index: int, column_index: int, request: Any) -> tuple[CellDisplayValue, CellRawValue]` — Keep ModelAdmin display formatting while sharing the table renderer.
- `def get_column_action_data(row: object, **_: object) -> Markup` — Render ModelAdmin row actions through the shared Table callback.
- `def get_row_id(row: object) -> object` — Use the registered model primary key, including non-id user keys.

## Module `oldman.apps.admin.template`

Built-in Admin template integration.

Import with `from oldman.apps.admin.template import <name>`.

### `admin_template_dir`

function · defined in `oldman.apps.admin.template`

```python
def admin_template_dir() -> Path
```

Return the templates shipped with the Admin package.

### `install_admin_template_loader`

function · defined in `oldman.apps.admin.template`

```python
def install_admin_template_loader(environment: Environment) -> Environment
```

Add Admin templates after the consumer's override-capable loader, and under `framework:` names.
