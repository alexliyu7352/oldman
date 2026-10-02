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
