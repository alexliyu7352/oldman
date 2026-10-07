# `oldman.apps.roles`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Roles: named sets of permissions that users hold.

The package itself exports nothing; import from the modules below.

## Module `oldman.apps.roles.apps`

Installable roles application metadata.

Import with `from oldman.apps.roles.apps import <name>`.

### `app`

value · defined in `oldman.apps.roles.apps`

```python
app = RolesAppConfig()
```

### `RolesAppConfig`

class · defined in `oldman.apps.roles.apps`

```python
class RolesAppConfig(AppConfig)
```

Roles and who holds them: the data behind permission checks.

## Module `oldman.apps.roles.forms`

Editing a role: its name, description and the permissions it grants.

Import with `from oldman.apps.roles.forms import <name>`.

### `permission_choices`

function · defined in `oldman.apps.roles.forms`

```python
def permission_choices(request: Any) -> dict[Any, list[tuple[str, Any]]]
```

Every declared permission, grouped under the App that declares it.

### `RoleForm`

class · defined in `oldman.apps.roles.forms`

```python
class RoleForm(TailwindModelForm)
```

A role's name, description and permissions; the permissions are the declared ones, grouped by App.

Constructor:

```python
RoleForm(*args: Any, **kwargs: Any) -> None
```

Members:

- `async def clean_name() -> str` — Names are unique; say so before the database constraint does.
- `async def clean_permissions() -> list[str]` — Sorted without repeats. What is checked must be declared here; what this service does not declare is kept.

## Module `oldman.apps.roles.management`

Managing roles: the steps every role page takes, and a dashboard's role pages.

Import with `from oldman.apps.roles.management import <name>`.

### `delete_role`

function · defined in `oldman.apps.roles.management`

```python
async def delete_role(session: Any, role: Role) -> None
```

Drop the role's cache key, then delete its row, inside the caller's transaction.

### `forget_deleted_role`

function · defined in `oldman.apps.roles.management`

```python
async def forget_deleted_role(role_id: int) -> None
```

Drop the key once more after the delete has committed.

### `publish_saved_role`

function · defined in `oldman.apps.roles.management`

```python
async def publish_saved_role(role: Role) -> None
```

Write the saved permissions to the role's cache key; call it once the save has committed.

### `RoleManagementFlow`

class · defined in `oldman.apps.roles.management`

```python
class RoleManagementFlow
```

A dashboard's role pages: list, create, edit and delete.

Members:

- `base_path: str`
- `login_path: str`
- `db_manager: DatabaseManager | None = None`
- `def database() -> DatabaseManager` — Where the roles live, the process's database by default.
- `def object_url(role: Any, action: str) -> str` — `edit`, `delete-modal` or `delete` for one role.
- `def table_class(name_prefix: str='') -> type[RoleTable]` — The role table data endpoint at `<base_path>/table`; `RoleTable` itself asks for `roles.view`.
- `def register_routes(app: Sanic | Router | None=None, *, render: PageRenderer | None=None, template_prefix: str | None=None, name_prefix: str='') -> None` — Install the pages, the table data endpoint, the delete modal and its submit under `base_path`.

### `RoleTable`

class · defined in `oldman.apps.roles.management`

```python
class RoleTable(SQLAlchemyTableView)
```

The role list as a table data endpoint; a site sets `route_name`, `route_path` and `object_url()`.

Members:

- `async def check_permission(request: Any, *, method_name: str, route_kwargs: dict[str, object]) -> tuple[bool, str | None]` — `roles.view`, checked before the query runs.
- `def object_url(row: Any, action: str) -> str` — Map "edit" and "delete-modal" to this site's routes for `row`.
- `async def get_queryset()`
- `def get_column_name_data(row: Any, **_: object)`
- `def get_column_action_data(row: Any, **_: object) -> tuple[Markup, str]`

## Module `oldman.apps.roles.models`

A role is a named set of permissions; users hold roles.

Import with `from oldman.apps.roles.models import <name>`.

### `Role`

class · defined in `oldman.apps.roles.models`

```python
class Role(DatabaseModel)
```

A named set of permission names.

Members:

- `id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)`
- `name: Mapped[str] = mapped_column(String(150), nullable=False)`
- `description: Mapped[str | None] = mapped_column(String(255), nullable=True)`
- `permissions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)`

### `UserRole`

class · defined in `oldman.apps.roles.models`

```python
class UserRole(DatabaseModel)
```

One user holding one role.

Members:

- `user_id: Mapped[int] = mapped_column(Integer, ForeignKey('oldman_user.id', ondelete='CASCADE'), primary_key=True)`
- `role_id: Mapped[int] = mapped_column(Integer, ForeignKey('oldman_role.id', ondelete='CASCADE'), primary_key=True)`

## Module `oldman.apps.roles.permissions`

The permissions the roles App declares: managing roles.

Import with `from oldman.apps.roles.permissions import <name>`.

### `ADD_ROLES`

value · defined in `oldman.apps.roles.permissions`

```python
ADD_ROLES = declare_permission('roles', 'add', _('Add roles'))
```

### `CHANGE_ROLES`

value · defined in `oldman.apps.roles.permissions`

```python
CHANGE_ROLES = declare_permission('roles', 'change', _('Change roles'))
```

### `DELETE_ROLES`

value · defined in `oldman.apps.roles.permissions`

```python
DELETE_ROLES = declare_permission('roles', 'delete', _('Delete roles'))
```

### `VIEW_ROLES`

value · defined in `oldman.apps.roles.permissions`

```python
VIEW_ROLES = declare_permission('roles', 'view', _('View roles'))
```

## Module `oldman.apps.roles.store`

Which roles a user holds, and which permissions a role grants — the latter also kept in Redis.

Import with `from oldman.apps.roles.store import <name>`.

### `checked_permission_names`

function · defined in `oldman.apps.roles.store`

```python
def checked_permission_names(names: Iterable[str]) -> list[str]
```

The names sorted without repeats; a name no App declares is refused.

### `forget_role`

function · defined in `oldman.apps.roles.store`

```python
async def forget_role(role_id: int) -> None
```

Drop a role's cache key: before deleting the row, in its transaction, and again after the commit.

### `publish_role`

function · defined in `oldman.apps.roles.store`

```python
async def publish_role(role: Role) -> None
```

Copy a saved role's permissions to its cache key. Call it after the commit.

### `replace_user_roles`

function · defined in `oldman.apps.roles.store`

```python
async def replace_user_roles(session: Any, user_id: int, role_ids: Iterable[int]) -> bool
```

Make a user hold exactly these roles, inside the caller's transaction; report whether anything changed.

### `role_permissions`

function · defined in `oldman.apps.roles.store`

```python
async def role_permissions(role_ids: Iterable[int], *, db_manager: DatabaseManager | None=None) -> frozenset[str]
```

Every permission name the given roles grant, read from Redis and, for missing keys, the database.

### `user_role_ids`

function · defined in `oldman.apps.roles.store`

```python
async def user_role_ids(user_id: int, *, db_manager: DatabaseManager | None=None) -> tuple[int, ...]
```

The ids of the roles a user holds, ascending.
