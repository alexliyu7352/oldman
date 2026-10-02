# `oldman.auth`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Framework authentication models and identity services.

Import with `from oldman.auth import <name>`.

## `AbstractUser`

class · defined in `oldman.auth.base`

```python
class AbstractUser(DatabaseModel)
```

Provide the standard User schema without registering a concrete table.

Members:

- `id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)`
- `username: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)`
- `email: Mapped[str | None] = mapped_column(String(254), unique=True, nullable=True)`
- `password_hash: Mapped[str] = mapped_column(String(255), nullable=False)`
- `display_name: Mapped[str | None] = mapped_column(String(150), nullable=True)`
- `is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)`
- `is_staff: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)`
- `is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, index=True)`
- `last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)`
- `created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())`
- `updated_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())`
- `def set_password(raw_password: str) -> None` — Hash and store a raw password.
- `def check_password(raw_password: str) -> bool` — Return whether a raw password matches this User.
- `property label: str` — Return the preferred human-readable identity label.

## `authenticate_user`

function · defined in `oldman.auth.services`

```python
async def authenticate_user(username: str, password: str, *, auth_settings: AuthSettings | None=None, db_manager: DatabaseManager | None=None) -> AbstractUser | None
```

Authenticate one active User without applying staff authorization.

## `AuthSettings`

class · defined in `oldman.auth.settings`

```python
class AuthSettings(BaseModel)
```

Select the sole concrete User model used by one service.

Members:

- `user_model: str = Field(default='oldman.auth.models.User', min_length=1, description='Import path of the configured U…`
- `password_reset: PasswordResetSettings = Field(default_factory=PasswordResetSettings, description='Password reset link lifetime and request …`
- `login: LoginSettings = Field(default_factory=LoginSettings, description='Failed sign-in limits per client address and per …`
- `classmethod def normalize_user_model_path(value: str) -> str` — Strip the import path and require a module attribute.

## `change_user_password`

function · defined in `oldman.auth.services`

```python
async def change_user_password(user_id: int, raw_password: str, *, auth_settings: AuthSettings | None=None, db_manager: DatabaseManager | None=None) -> AbstractUser | None
```

Change one configured User password in a single write transaction.

## `declare_permission`

function · defined in `oldman.auth.permissions`

```python
def declare_permission(namespace: str, codename: str, label: Any) -> Permission
```

Declare one permission by name, for code that builds them — the Admin does, per model.

## `declared_permissions`

function · defined in `oldman.auth.permissions`

```python
def declared_permissions() -> tuple[Permission, ...]
```

Every declared permission, ordered by name.

## `decode_user_id`

function · defined in `oldman.auth.password_reset`

```python
def decode_user_id(value: str) -> int | None
```

Reverse `encode_user_id`; None for anything that is not one of its outputs.

## `default_token_generator`

value · defined in `oldman.auth.password_reset`

```python
default_token_generator = PasswordResetTokenGenerator()
```

## `encode_user_id`

function · defined in `oldman.auth.password_reset`

```python
def encode_user_id(user_id: int) -> str
```

URL-safe form of a user id for the reset link (base64 without padding, like Django's uidb64).

## `ensure_superuser`

function · defined in `oldman.auth.services`

```python
async def ensure_superuser(username: str, password: str, email: str | None=None, *, auth_settings: AuthSettings | None=None, db_manager: DatabaseManager | None=None) -> AbstractUser
```

Create or update one configured User as an active superuser.

## `get_permission`

function · defined in `oldman.auth.permissions`

```python
def get_permission(name: str) -> Permission | None
```

The declared permission with this name, or None.

## `get_user_by_email`

function · defined in `oldman.auth.password_reset`

```python
async def get_user_by_email(email: str, *, auth_settings: AuthSettings | None=None, db_manager: DatabaseManager | None=None) -> AbstractUser | None
```

The user whose email matches, case-insensitively; None for blank input or no match.

## `get_user_by_id`

function · defined in `oldman.auth.services`

```python
async def get_user_by_id(user_id: int, *, auth_settings: AuthSettings | None=None, db_manager: DatabaseManager | None=None) -> AbstractUser | None
```

Return the configured User for one integer database identity.

## `get_user_by_username`

function · defined in `oldman.auth.services`

```python
async def get_user_by_username(username: str, *, auth_settings: AuthSettings | None=None, db_manager: DatabaseManager | None=None) -> AbstractUser | None
```

Return the configured User matching a normalized username.

## `get_user_model`

function · defined in `oldman.auth.registry`

```python
def get_user_model(auth_settings: AuthSettings | None=None) -> type[AbstractUser]
```

Resolve and validate the User model selected by the Auth configuration.

## `has_staff_access`

function · defined in `oldman.auth.services`

```python
def has_staff_access(user: Any | None, *, require_superuser: bool=False) -> bool
```

Return whether an active User satisfies the reusable staff policy.

## `is_ordinary_user`

function · defined in `oldman.auth.services`

```python
def is_ordinary_user(user: Any) -> bool
```

Neither staff nor superuser: the only accounts someone who is not a superuser may manage.

## `LoginSettings`

class · defined in `oldman.auth.settings`

```python
class LoginSettings(BaseModel)
```

How many failed sign-ins one caller or one account may spend before it has to wait.

Members:

- `ip_limit: int = Field(default=20, ge=0, description='Failed sign-ins one IP may make per ip_window; more get a 429.…`
- `ip_window: int = Field(default=60 * 15, gt=0, description='Window in seconds for ip_limit')`
- `username_limit: int = Field(default=5, ge=0, description='Failed sign-ins one username may collect per username_window; m…`
- `username_window: int = Field(default=60 * 15, gt=0, description='Window in seconds for username_limit')`

## `normalize_email`

function · defined in `oldman.auth.services`

```python
def normalize_email(value: str | None) -> str | None
```

One spelling per address: stripped and lowercased; blank becomes None. Every writer of User.email uses it.

## `PasswordResetSettings`

class · defined in `oldman.auth.settings`

```python
class PasswordResetSettings(BaseModel)
```

How long a reset link lives and how often one client may ask for one.

Members:

- `expiry: int = Field(default=60 * 60 * 24, gt=0, description='Seconds a password reset link stays valid')`
- `ip_limit: int = Field(default=5, ge=0, description='Reset requests one IP may make per ip_window; more get a 429')`
- `ip_window: int = Field(default=60 * 15, gt=0, description='Window in seconds for ip_limit')`
- `email_limit: int = Field(default=3, ge=0, description='Reset mails one address may receive per email_window; more are …`
- `email_window: int = Field(default=60 * 60, gt=0, description='Window in seconds for email_limit')`

## `PasswordResetTokenGenerator`

class · defined in `oldman.auth.password_reset`

```python
class PasswordResetTokenGenerator
```

Make and check reset tokens for one user; `expiry` seconds after issue they are dead.

Constructor:

```python
PasswordResetTokenGenerator(secret: str | bytes | None=None, *, expiry: int | None=None, now: Callable[[], dt.datetime] | None=None) -> None
```

Members:

- `property secret: bytes`
- `property expiry: int`
- `def make_token(user: Any) -> str` — Token for `user` issued now.
- `def check_token(user: Any, token: str | None) -> bool` — True when `token` was made for the user's current state and has not expired.

## `Permission`

class · defined in `oldman.auth.permissions`

```python
class Permission
```

One permission. Declare it as an attribute of a PermissionSet, or through declare_permission().

Constructor:

```python
Permission(label: Any) -> None
```

Members:

- `property name: str` — The stored name, ``<namespace>.<codename>``; empty until the permission is declared.

## `PermissionSet`

class · defined in `oldman.auth.permissions`

```python
class PermissionSet
```

A group of permissions under one namespace: each Permission attribute is declared as ``<namespace>.<attribute>``.

Members:

- `namespace: ClassVar[str] = ''`

## `set_user_active`

function · defined in `oldman.auth.services`

```python
def set_user_active(user: Any, is_active: bool, *, current_user_id: int | None) -> None
```

Change the active state without letting the current User disable itself.

## `touch_last_login`

function · defined in `oldman.auth.services`

```python
async def touch_last_login(user_id: int, *, auth_settings: AuthSettings | None=None, db_manager: DatabaseManager | None=None) -> None
```

Persist the current UTC time for one configured User identity.

## `user_access_flags`

function · defined in `oldman.auth.services`

```python
def user_access_flags(user: Any) -> tuple[bool, ...]
```

The flags a login copies when it opens: sessions and access tokens carry them.

## `user_identity`

function · defined in `oldman.auth.services`

```python
def user_identity(user: AbstractUser) -> int
```

Return one persisted User's integer primary-key value unchanged.

## `user_identity_matches`

function · defined in `oldman.auth.services`

```python
def user_identity_matches(user: Any, user_id: int | None) -> bool
```

Compare one mapped User with the current integer Session identity.

## `UserIdentityError`

class · defined in `oldman.auth.services`

```python
class UserIdentityError(ValueError)
```

Report an unavailable or unsupported configured User identity.

## `UserManagementError`

class · defined in `oldman.auth.services`

```python
class UserManagementError(ValueError)
```

A rejected user-management operation (self-disable, deleting a superuser, ...).

## `UserModelContractError`

class · defined in `oldman.auth.contracts`

```python
class UserModelContractError(TypeError)
```

Raised when a concrete User changes the stable database identity.

## `validate_user_delete`

function · defined in `oldman.auth.services`

```python
def validate_user_delete(user: Any, *, current_user_id: int | None) -> None
```

Reject deleting the current User or any superuser.

## `validate_user_model`

function · defined in `oldman.auth.registry`

```python
def validate_user_model(model: Any) -> type[AbstractUser]
```

Require the selected mapper to inherit the fixed AbstractUser contract.

## Module `oldman.auth.apps`

Installable Auth application metadata.

Import with `from oldman.auth.apps import <name>`.

### `app`

value · defined in `oldman.auth.apps`

```python
app = AuthAppConfig()
```

### `AuthAppConfig`

class · defined in `oldman.auth.apps`

```python
class AuthAppConfig(AppConfig[AuthSettings])
```

Describe the framework Auth application and its settings owner.

## Module `oldman.auth.backends`

Login backends: check a credential at sign-in and return the User it signs in.

Import with `from oldman.auth.backends import <name>`.

### `authenticate_with`

function · defined in `oldman.auth.backends`

```python
async def authenticate_with(backends: tuple[LoginBackend, ...], request: Any, **credentials: Any) -> AbstractUser | None
```

Ask each backend in turn; the first to accept the credential decides.

### `BUILTIN_LOGIN_BACKENDS`

value · defined in `oldman.auth.backends`

```python
BUILTIN_LOGIN_BACKENDS: dict[str, type[LoginBackend]] = {'users': UserTableBackend}
```

Backends a service names by a bare word in ``web.auth.login_backends``.

### `LoginBackend`

class · defined in `oldman.auth.backends`

```python
class LoginBackend(Protocol)
```

One kind of credential a service accepts at sign-in.

Members:

- `name: str`
- `async def authenticate(request: Any, **credentials: Any) -> AbstractUser | None`

### `resolve_login_backends`

function · defined in `oldman.auth.backends`

```python
def resolve_login_backends(names: tuple[str, ...]) -> tuple[LoginBackend, ...]
```

Build the backends a service tries, in the order they are listed.

### `UserTableBackend`

class · defined in `oldman.auth.backends`

```python
class UserTableBackend
```

A username and password checked against the configured User table.

Members:

- `async def authenticate(request: Any, *, username: Any=None, password: Any=None, auth_settings: Any=None, db_manager: Any=None, **credentials: Any) -> AbstractUser | None`

## Module `oldman.auth.base`

Unmapped base model for project-defined User models.

Import with `from oldman.auth.base import <name>`.

### `assign_user_model_ownership`

function · defined in `oldman.auth.base`

```python
def assign_user_model_ownership(model: type[AbstractUser], user_app_label: str) -> None
```

Record Auth's table ownership and the selected extension App once.

### `normalize_user_staff_flags`

function · defined in `oldman.auth.base`

```python
def normalize_user_staff_flags(user: AbstractUser) -> None
```

Keep the invariant that every superuser is also a staff user.

### `USER_APP_LABEL_INFO_KEY`

value · defined in `oldman.auth.base`

```python
USER_APP_LABEL_INFO_KEY = 'oldman_user_app_label'
```

### `USER_CORE_FIELDS_INFO_KEY`

value · defined in `oldman.auth.base`

```python
USER_CORE_FIELDS_INFO_KEY = 'oldman_user_core_fields'
```

### `USER_TABLE_OWNER_LABEL`

value · defined in `oldman.auth.base`

```python
USER_TABLE_OWNER_LABEL = 'auth'
```

## Module `oldman.auth.contracts`

Stable database contract shared by every concrete User model.

Import with `from oldman.auth.contracts import <name>`.

### `USER_CORE_CHECK_CONSTRAINTS`

value · defined in `oldman.auth.contracts`

```python
USER_CORE_CHECK_CONSTRAINTS = {USER_SUPERUSER_STAFF_CONSTRAINT: 'NOT is_superuser OR is_staff'}
```

### `USER_CORE_FIELD_NAMES`

value · defined in `oldman.auth.contracts`

```python
USER_CORE_FIELD_NAMES = ('id', 'username', 'email', 'password_hash', 'display_name', 'is_active', 'is_staff', 'is_superuser…
```

### `USER_CORE_INDEXES`

value · defined in `oldman.auth.contracts`

```python
USER_CORE_INDEXES = {'ix_oldman_user_username': (('username',), True), 'ix_oldman_user_is_active': (('is_active',), Fal…
```

### `USER_CORE_UNIQUE_COLUMN_SETS`

value · defined in `oldman.auth.contracts`

```python
USER_CORE_UNIQUE_COLUMN_SETS = (('email',),)
```

### `USER_PRIMARY_KEY_NAME`

value · defined in `oldman.auth.contracts`

```python
USER_PRIMARY_KEY_NAME = 'id'
```

### `USER_SUPERUSER_STAFF_CONSTRAINT`

value · defined in `oldman.auth.contracts`

```python
USER_SUPERUSER_STAFF_CONSTRAINT = 'ck_oldman_user_superuser_is_staff'
```

### `USER_TABLE_NAME`

value · defined in `oldman.auth.contracts`

```python
USER_TABLE_NAME = 'oldman_user'
```

### `validate_user_table_contract`

function · defined in `oldman.auth.contracts`

```python
def validate_user_table_contract(model: type[Any]) -> Table
```

Validate and complete one concrete User table during model mapping.

## Module `oldman.auth.models`

Default concrete User model.

Import with `from oldman.auth.models import <name>`.

### `User`

class · defined in `oldman.auth.models`

```python
class User(AbstractUser)
```

Ready-to-use User model selected by the default Auth configuration.

## Module `oldman.auth.password_reset`

Password reset tokens and lookups, after django.contrib.auth.tokens.

Import with `from oldman.auth.password_reset import <name>`.

### `password_reset_settings`

function · defined in `oldman.auth.password_reset`

```python
def password_reset_settings(auth_settings: AuthSettings | None=None) -> PasswordResetSettings
```

The reset settings of the given or the installed Auth app.

## Module `oldman.auth.user_permissions`

The permissions the auth App declares: managing user accounts.

Import with `from oldman.auth.user_permissions import <name>`.

### `ADD_USERS`

value · defined in `oldman.auth.user_permissions`

```python
ADD_USERS = declare_permission('auth', 'users.add', _('Add users'))
```

### `CHANGE_USERS`

value · defined in `oldman.auth.user_permissions`

```python
CHANGE_USERS = declare_permission('auth', 'users.change', _('Change users'))
```

### `DELETE_USERS`

value · defined in `oldman.auth.user_permissions`

```python
DELETE_USERS = declare_permission('auth', 'users.delete', _('Delete users'))
```

### `VIEW_USERS`

value · defined in `oldman.auth.user_permissions`

```python
VIEW_USERS = declare_permission('auth', 'users.view', _('View users'))
```
