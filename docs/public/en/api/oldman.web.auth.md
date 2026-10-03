# `oldman.web.auth`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Public Web authentication adapters.

Import with `from oldman.web.auth import <name>`.

## `account_urls`

function · defined in `oldman.web.auth.account`

```python
def account_urls(request: Any=None) -> dict[str, Any]
```

The site's account addresses for templates (a dashboard's topbar and base), from the settings.

## `AccountFlow`

class · defined in `oldman.web.auth.account`

```python
class AccountFlow
```

The pages around one site's signed-in user.

Members:

- `profile_path: str`
- `login_path: str`
- `logout_path: str`
- `language_path: str`
- `notification_routes: NotificationRoutes | None = None`
- `user_events_path: str | None = None`
- `auth_settings: AuthSettings | None = None`
- `db_manager: DatabaseManager | None = None`
- `property password_modal_path: str` — The own-password form, loaded into a modal on the profile page.
- `property password_path: str` — Where the own-password form posts.
- `def register_routes(app: Sanic | Router | None=None, *, render: PageRenderer | None=None, template_prefix: str | None=None, allow: Callable[[Any], bool]=user_is_signed_in, name_prefix: str='') -> str | None` — Install the pages; return the user events path when that stream was installed.

## `api_login_required`

value · defined in `oldman.web.auth.decorators`

```python
api_login_required = method_adaptor(_api_login_required)
```

## `authenticate_credentials`

function · defined in `oldman.web.auth.login`

```python
async def authenticate_credentials(request: Any, **credentials: Any) -> AbstractUser | None
```

Return the User a sign-in credential belongs to, asking the configured login backends.

## `authenticated_by`

value · defined in `oldman.web.auth.decorators`

```python
authenticated_by = method_adaptor(_authenticated_by)
```

## `authenticated_session`

function · defined in `oldman.web.auth.user_session`

```python
def authenticated_session(request: Any) -> SessionData
```

The request's signed-in browser session; a page about "this session" needs one.

## `can_manage_user`

function · defined in `oldman.web.auth.permissions`

```python
def can_manage_user(request: Any, target: Any=None, *, makes_privileged: bool=False) -> bool
```

Whether the request's user may change this account.

## `end_user_logins`

function · defined in `oldman.web.auth.session`

```python
async def end_user_logins(user_id: int) -> None
```

End every session and token one user holds, where there is no request.

## `finish_user_change`

function · defined in `oldman.web.auth.user_management`

```python
async def finish_user_change(request: Any, user_id: int, *, login_url: str) -> Response | None
```

End the account's logins after a change to what it may do; the answer when that was the operator's own.

## `form_value`

function · defined in `oldman.web.auth.login`

```python
def form_value(request: Any, key: str, default: str='') -> str
```

One scalar form field as text (Sanic form values arrive as lists).

## `has_perm`

function · defined in `oldman.web.auth.permissions`

```python
async def has_perm(request: Any, permission: Permission, *, db_manager: DatabaseManager | None=None) -> bool
```

Whether the request's user holds this permission; `db_manager` holds the roles, the process's by default.

## `INVALID_CREDENTIALS`

value · defined in `oldman.web.auth.login`

```python
INVALID_CREDENTIALS = 'invalid_credentials'
```

## `login_error_message`

function · defined in `oldman.web.auth.login`

```python
def login_error_message(error_code: object) -> str
```

The safe message for an error code from the URL; unknown codes show nothing.

## `login_error_url`

function · defined in `oldman.web.auth.login`

```python
def login_error_url(login_path: str, next_url: str, error_code: str) -> str
```

Back to the login page with the error code and the pending next URL (the page re-issues its CSRF token).

## `login_required`

value · defined in `oldman.web.auth.decorators`

```python
login_required = method_adaptor(_login_required)
```

## `login_settings`

function · defined in `oldman.web.auth.login`

```python
def login_settings(auth_settings: AuthSettings | None=None) -> LoginSettings
```

The sign-in limits of the given or the installed Auth app.

## `login_user`

function · defined in `oldman.web.auth.login`

```python
async def login_user(request: Any, user: Any, *, response: Any, remember: bool=False, auth_settings: AuthSettings | None=None, db_manager: DatabaseManager | None=None) -> Any
```

Open the exclusive session for an authenticated user and attach its cookie to `response`.

## `LoginFlow`

class · defined in `oldman.web.auth.login`

```python
class LoginFlow
```

The login page, its submit and sign-out for one site.

Members:

- `login_path: str`
- `logout_path: str`
- `home_path: str`
- `password_reset_path: str | None = None`
- `accept_user: Callable[[AbstractUser], bool] | None = None`
- `rate_limit: LoginRateLimit | None = None`
- `auth_settings: AuthSettings | None = None`
- `db_manager: DatabaseManager | None = None`
- `def limiter() -> LoginRateLimit` — The failed sign-in limits the submit applies.
- `def register_routes(app: Sanic | Router | None=None, *, render: PageRenderer | None=None, template_prefix: str | None=None, is_authenticated: Callable[[Any], bool]=session_is_authenticated, name_prefix: str='') -> None` — Install the login page and its submit at `login_path`, and sign-out at `logout_path`.

## `LoginForm`

class · defined in `oldman.web.auth.forms`

```python
class LoginForm(TailwindForm)
```

Collect login credentials plus the remember-me choice.

## `LoginRateLimit`

class · defined in `oldman.web.auth.login`

```python
class LoginRateLimit
```

Fixed windows over failed sign-ins, counted per client address and per username.

Members:

- `auth_settings: AuthSettings | None = None`
- `counter: WindowCounter | None = None`
- `def window_counter() -> WindowCounter` — The Redis fixed window, under this service's own sign-in namespace.
- `async def retry_after(request: Any, username: str) -> int | None` — Seconds this caller must wait, or None when the attempt may go ahead.
- `async def record_failure(request: Any, username: str) -> None` — Charge one failed attempt to both the client address and the username.

## `logout_user`

function · defined in `oldman.web.auth.login`

```python
async def logout_user(request: Any, redirect_to: str) -> Any
```

End the current session, schedule the cookie removal and redirect.

## `PasswordResetFlow`

class · defined in `oldman.web.auth.password_reset`

```python
class PasswordResetFlow
```

Paths, settings and collaborators for one site's reset flow.

Members:

- `base_path: str`
- `login_path: str`
- `home_path: str | None = None`
- `site_name: str = 'Oldman'`
- `mail_template: str = 'oldman/auth/mail/password_reset'`
- `auth_settings: AuthSettings | None = None`
- `db_manager: DatabaseManager | None = None`
- `token_generator: PasswordResetTokenGenerator | None = None`
- `rate_limiter: RateLimiter | None = None`
- `public_url: str | None = None`
- `property request_path: str` — The request page and its submit.
- `property sent_path: str` — Where a submitted request lands, mail or not.
- `property done_path: str` — Where a new password lands.
- `def confirm_path(uidb64: str, token: str) -> str` — The set-password page one mailed link opens.
- `def generator() -> PasswordResetTokenGenerator` — Token generator bound to this flow's reset settings (lifetime from `auth_settings`).
- `def limiter() -> RateLimiter`
- `async def request_reset(request: Any, email: str, *, language: str | None=None) -> RequestOutcome` — Apply both limits, look the address up and mail the link when there is an active account.
- `def reset_url(user: AbstractUser) -> str` — Absolute link for the mail, on the configured public domain.
- `async def deliver_reset_mail(user: AbstractUser, *, language: str | None=None) -> None` — Background task body: send the mail and log a failure instead of raising it.
- `async def send_reset_mail(user: AbstractUser, *, language: str | None=None) -> int` — Send the templated reset mail to the user's address; raises when the backend fails.
- `async def verify(uidb64: str, token: str) -> AbstractUser | None` — The active user a link belongs to, or None when the id or token does not hold.
- `async def complete(request: Any, user: AbstractUser, raw_password: str) -> None` — Store the new password and end the user's sessions; the used link dies with the hash.
- `def register_routes(app: Sanic | Router | None=None, *, render: PageRenderer | None=None, template_prefix: str | None=None, is_authenticated: Callable[[Any], bool]=session_is_authenticated, name_prefix: str='') -> None` — Install the six views: request page and submit, sent, confirm page and submit, done.

## `PasswordResetForm`

class · defined in `oldman.web.auth.password_reset`

```python
class PasswordResetForm(UserPasswordForm)
```

New password plus confirmation, under the shared password policy.

## `PasswordResetRequestForm`

class · defined in `oldman.web.auth.password_reset`

```python
class PasswordResetRequestForm(TailwindForm)
```

Ask for the account's email address.

## `permissions_not_held`

function · defined in `oldman.web.auth.permissions`

```python
async def permissions_not_held(request: Any, names: Iterable[str], *, db_manager: DatabaseManager | None=None) -> list[str]
```

Which of these permission names the request's user does not hold, sorted; none for a superuser.

## `RATE_LIMITED`

value · defined in `oldman.web.auth.login`

```python
RATE_LIMITED = 'rate_limited'
```

## `remember_me_requested`

function · defined in `oldman.web.auth.login`

```python
def remember_me_requested(request: Any) -> bool
```

Whether the login form asked for the long session lifetime.

## `render_session_password_modal`

function · defined in `oldman.web.auth.user_session`

```python
async def render_session_password_modal(request: Any, *, action: str, auth_settings: AuthSettings | None=None, db_manager: DatabaseManager | None=None)
```

Render the password form for the User identified by this request Session.

## `RequestOutcome`

class · defined in `oldman.web.auth.password_reset`

```python
class RequestOutcome(enum.Enum)
```

What happened to a reset request; SENT and SKIPPED must look the same to the browser.

## `require_perm`

function · defined in `oldman.web.auth.permissions`

```python
async def require_perm(request: Any, permission: Permission, *, db_manager: DatabaseManager | None=None) -> None
```

Refuse the request with 403 unless its user holds this permission.

## `revoke_user_logins`

function · defined in `oldman.web.auth.session`

```python
async def revoke_user_logins(request: Any, user_id: int) -> bool
```

End every session and token one user holds; report whether the caller ended its own.

## `role_ids_for_login`

function · defined in `oldman.web.auth.permissions`

```python
async def role_ids_for_login(request: Any, user_id: int, *, db_manager: DatabaseManager | None=None) -> tuple[int, ...]
```

The role ids to write into a new session or access token: none unless the roles App is installed.

## `roles_installed`

function · defined in `oldman.web.auth.permissions`

```python
def roles_installed(app: Any) -> bool
```

Whether the service installs ``oldman.apps.roles``: without it there are no roles to read or assign.

## `safe_next_url`

function · defined in `oldman.web.auth.redirects`

```python
def safe_next_url(raw_next_url: object, fallback: str='/') -> str
```

Return `raw_next_url` when it is a plain same-site path, otherwise `fallback`.

## `save_language_preference`

function · defined in `oldman.web.auth.user_session`

```python
def save_language_preference(request: Any, *, registry: LanguageRegistry)
```

Normalize and persist one browser language preference in shared cookies.

## `session_data_for_user`

function · defined in `oldman.web.auth.session`

```python
def session_data_for_user(session_model: type[TSessionData], user: Any, *, expiry: int | None=None, login_ip: str='', login_time: int | None=None, role_ids: tuple[int, ...]=()) -> TSessionData
```

Build one base authorization snapshot for an authenticated User.

## `session_profile`

function · defined in `oldman.web.auth.user_session`

```python
def session_profile(session_data: SessionData) -> UserSessionProfile
```

Build the current-session page data without querying the User table.

## `SessionPasswordForm`

class · defined in `oldman.web.auth.forms`

```python
class SessionPasswordForm(UserPasswordForm)
```

A signed-in user changing their own password, which takes the current one as well.

## `SIGN_IN_AGAIN_DELAY_MS`

value · defined in `oldman.web.auth.user_session`

```python
SIGN_IN_AGAIN_DELAY_MS = 1500
```

## `staff_required`

value · defined in `oldman.web.auth.decorators`

```python
staff_required = method_adaptor(_staff_required)
```

## `superuser_required`

value · defined in `oldman.web.auth.decorators`

```python
superuser_required = method_adaptor(_superuser_required)
```

## `TokenFlow`

class · defined in `oldman.web.auth.tokens`

```python
class TokenFlow
```

Who may hold bearer tokens, and the three routes that hand them out, renew and end them.

Members:

- `accept_user: Callable[[AbstractUser], bool]`
- `credential_fields: tuple[str, ...] = ('username', 'password')`
- `auth_settings: AuthSettings | None = None`
- `db_manager: DatabaseManager | None = None`
- `rate_limit: LoginRateLimit | None = None`
- `def limiter() -> LoginRateLimit` — The failed sign-in limits the obtain route applies.
- `def register_routes(app: Sanic | Router | None=None, *, obtain_path: str, refresh_path: str, revoke_path: str, name_prefix: str='') -> None` — Install the three POST routes.

## `update_session_password`

function · defined in `oldman.web.auth.user_session`

```python
async def update_session_password(request: Any, *, login_url: str | None=None, success_actions: Sequence[ResponseAction]=(), auth_settings: AuthSettings | None=None, db_manager: DatabaseManager | None=None)
```

Change the current User password, then sign the user out everywhere.

## `user_cell_value`

function · defined in `oldman.web.auth.tables`

```python
def user_cell_value(user: Any, field_name: str, *, edit_url: str | None=None) -> Any
```

Display value for the standard User columns; None for any other field so the caller can fall back.

## `user_change_text`

function · defined in `oldman.web.auth.user_management`

```python
def user_change_text(change: UserChange, *, username: str, request: Any=None) -> str
```

The sentence the Admin and a dashboard both show after changing an account.

## `user_create_form_class`

function · defined in `oldman.web.auth.forms`

```python
def user_create_form_class(user_model: type[Any], *, session: Any=None, dialect: Any=None) -> type[UserModelForm]
```

A ModelForm for creating a User: profile, flags, password plus confirmation.

## `user_delete_modal_response`

function · defined in `oldman.web.auth.modals`

```python
async def user_delete_modal_response(request: Any, user: AbstractUser | None, *, action: str)
```

Confirm deleting one user; `action` takes the POST.

## `user_edit_form_class`

function · defined in `oldman.web.auth.forms`

```python
def user_edit_form_class(user_model: type[Any]) -> type[UserModelForm]
```

A ModelForm for editing the configured User model's profile and flags.

## `user_row_actions`

function · defined in `oldman.web.auth.tables`

```python
def user_row_actions(user: Any, *, edit_url: str, password_modal_url: str, status_modal_url: str, delete_modal_url: str, label: object | None=None) -> Markup
```

The user row menu: edit, change password, enable/disable and delete (the last three open modals).

## `user_status_modal_response`

function · defined in `oldman.web.auth.modals`

```python
async def user_status_modal_response(request: Any, user: AbstractUser | None, *, action: str)
```

Confirm switching one user between active and disabled; `action` takes the POST.

## `UserFilterForm`

class · defined in `oldman.web.auth.forms`

```python
class UserFilterForm(TailwindTableFilterForm)
```

Filter a configured User table: search, the three flags and a last-login range.

## `UserManagementFlow`

class · defined in `oldman.web.auth.user_management`

```python
class UserManagementFlow
```

A dashboard's user pages: list with filters, create, edit, password, enable or disable, delete.

Members:

- `base_path: str`
- `login_path: str`
- `user_model: type[Any] | None = None`
- `auth_settings: AuthSettings | None = None`
- `db_manager: DatabaseManager | None = None`
- `def model() -> type[Any]` — The User model the pages manage.
- `def database() -> DatabaseManager` — Where the users live, the process's database by default.
- `def object_url(user: Any, action: str) -> str` — `edit`, `password`, `password-modal`, `status`, `status-modal`, `delete` or `delete-modal` for one user.
- `def table_class(name_prefix: str='') -> type[UserTable]` — The user table data endpoint at `<base_path>/table`; `UserTable` itself asks for `auth.users.view`.
- `def activity(request: Any, title: str, description: str, *, tone: str, icon: str) -> DashboardActivityAction` — The topbar's activity entry for one change.
- `def register_routes(app: Sanic | Router | None=None, *, render: PageRenderer | None=None, template_prefix: str | None=None, name_prefix: str='') -> None` — Install the pages, the table data endpoint, the modals and their submits under `base_path`.

## `UserModelForm`

class · defined in `oldman.web.auth.forms`

```python
class UserModelForm(TailwindModelForm)
```

Shared validation and persistence for the configured User model (create and edit).

Constructor:

```python
UserModelForm(*args: Any, **kwargs: Any) -> None
```

Members:

- `current_user_id: int | None = None`
- `confirm_password: Any`
- `email: Any`
- `password: Any`
- `roles: Any`
- `username: Any`
- `async def prepare_async_fields() -> None` — Load the roles to offer and, when showing a saved user, the ones they hold.
- `async def clean_roles() -> list[int]` — The checked roles. A role given anew must grant only what the operator holds, unless they are a superuser.
- `async def clean_username() -> str` — Validate username uniqueness before a database constraint can fail.
- `async def clean_email() -> str | None` — Validate optional email uniqueness before persistence; EmailField already settled the spelling.
- `async def clean_explicit_primary_key() -> Any` — Validate a user-supplied primary key before database persistence.
- `async def clean() -> None` — Keep other operators to ordinary accounts, protect the current user and validate password confirmation.
- `async def save(*, commit: bool=False, session: Any=None) -> Any` — Persist profile fields and hash the create-form password.
- `async def save_roles(session: Any, user: Any) -> bool` — Make the user hold the checked roles, and report whether that changed anything.
- `def is_same_instance(other: Any) -> bool` — Compare rows without assuming the primary key is named ``id``.
- `property mapper` — Return the mapped model metadata used by identity comparisons.

## `UserPasswordForm`

class · defined in `oldman.web.auth.forms`

```python
class UserPasswordForm(TailwindForm)
```

Validate a new password through the shared Web account policy.

Members:

- `async def clean() -> None` — Require the confirmation to match the new password.

## `UserSessionProfile`

class · defined in `oldman.web.auth.user_session`

```python
class UserSessionProfile
```

Template-safe projection of one strongly typed login snapshot.

Members:

- `username: str`
- `display_name: str`
- `login_ip: str`
- `login_time: str`
- `is_active: bool`
- `is_staff: bool`
- `is_superuser: bool`

## `UserTable`

class · defined in `oldman.web.auth.tables`

```python
class UserTable(UserTableFilters, SQLAlchemyTableView)
```

The user list as a table data endpoint; a site sets `route_name`, `route_path` and `object_url()`.

Constructor:

```python
UserTable(request: Any=None, **options: Any) -> None
```

Members:

- `async def check_permission(request: Any, *, method_name: str, route_kwargs: dict[str, object]) -> tuple[bool, str | None]` — `auth.users.view`, checked before the query runs.
- `def object_url(row: Any, action: str) -> str` — Map "edit", "password-modal", "status-modal" and "delete-modal" to this site's routes for `row`.
- `async def get_queryset()`
- `def get_column_username_data(row: Any, **_: object)`
- `def get_column_is_active_data(row: Any, **_: object)`
- `def get_column_is_staff_data(row: Any, **_: object)`
- `def get_column_is_superuser_data(row: Any, **_: object)`
- `def get_column_last_login_at_data(row: Any, **_: object)`
- `def get_column_action_data(row: Any, **_: object)`

## Module `oldman.web.auth.account`

The signed-in user's own pages: profile, own password, language choice, notifications and user events.

Import with `from oldman.web.auth.account import <name>`.

### `user_is_signed_in`

function · defined in `oldman.web.auth.account`

```python
def user_is_signed_in(request: Any) -> bool
```

Whether the request comes from a signed-in user, however it authenticated; AccountFlow's default `allow`.

## Module `oldman.web.auth.flows`

What the auth flows share: how a page is rendered and who counts as signed in by default.

Import with `from oldman.web.auth.flows import <name>`.

### `PageRenderer`

class · defined in `oldman.web.auth.flows`

```python
class PageRenderer(Protocol)
```

Renders one page of a flow, named by `page`, with the given context.

### `resolve_page_renderer`

function · defined in `oldman.web.auth.flows`

```python
def resolve_page_renderer(render: PageRenderer | None, template_prefix: str | None) -> PageRenderer
```

The host's `render`, or one that renders `<template_prefix>/<page>.html`; exactly one of the two is given.

### `session_is_authenticated`

function · defined in `oldman.web.auth.flows`

```python
def session_is_authenticated(request: Any) -> bool
```

Whether the request carries a signed-in Session; the default for "already signed in, skip this page".

## Module `oldman.web.auth.forms`

Forms shared by every site that manages the configured User model: login, filter, create/edit, password.

Import with `from oldman.web.auth.forms import <name>`.

### `BOOLEAN_FILTER_CHOICES`

value · defined in `oldman.web.auth.forms`

```python
BOOLEAN_FILTER_CHOICES = (('', cast(str, gettext_lazy('All'))), ('true', cast(str, gettext_lazy('Yes'))), ('false', cast(str…
```

### `EDITABLE_USER_FIELDS`

value · defined in `oldman.web.auth.forms`

```python
EDITABLE_USER_FIELDS = ('username', 'email', 'display_name', 'is_active', 'is_staff', 'is_superuser')
```

### `PASSWORD_MESSAGE`

value · defined in `oldman.web.auth.forms`

```python
PASSWORD_MESSAGE = cast(str, gettext_lazy('Password must be 8-128 characters and include letters and numbers'))
```

### `PASSWORD_PATTERN`

value · defined in `oldman.web.auth.forms`

```python
PASSWORD_PATTERN = '^(?=.*[A-Za-z])(?=.*\\d).{8,128}$'
```

## Module `oldman.web.auth.login`

The login and logout steps every site shares: form values, error redirects and opening the session.

Import with `from oldman.web.auth.login import <name>`.

### `LOGIN_RATE_LIMIT_PATH`

value · defined in `oldman.web.auth.login`

```python
LOGIN_RATE_LIMIT_PATH = 'login'
```

## Module `oldman.web.auth.password_reset`

Password reset flow shared by the Admin site and project login pages.

Import with `from oldman.web.auth.password_reset import <name>`.

### `client_ip`

function · defined in `oldman.web.request`

```python
def client_ip(request: Any) -> str
```

The address a request came from: Sanic's `client_ip` honours the configured proxy headers, `ip` is the socket peer.

### `RateLimiter`

class · defined in `oldman.web.security.rate_limiter.base`

```python
class RateLimiter(Protocol)
```

What a flow needs from a limiter; `RedisFixedWindowRateLimiter` satisfies it.

Members:

- `async def is_rate_limited(subject: int | str, path: str, limit: int, period: int) -> bool` — Count this event and return whether the subject is now over the limit.

### `redis_rate_limiter`

function · defined in `oldman.web.security.rate_limiter.fixed_window`

```python
def redis_rate_limiter(alias: str | None=None, namespace: str | None=None) -> RedisFixedWindowRateLimiter
```

The default limiter: a Redis fixed window on the session connection (the one a login site must have).

## Module `oldman.web.auth.tables`

Table pieces for the configured User model: cell renderers, row actions, filters and a ready-made table view.

Import with `from oldman.web.auth.tables import <name>`.

### `USER_FILTER_FIELDS`

value · defined in `oldman.web.auth.tables`

```python
USER_FILTER_FIELDS = ('is_active', 'is_staff', 'is_superuser', 'last_login_from', 'last_login_to')
```

### `USER_MODAL_TARGETS`

value · defined in `oldman.web.auth.tables`

```python
USER_MODAL_TARGETS = {'password-modal': '#user-password-modal', 'status-modal': '#user-status-modal', 'delete-modal': '#…
```

### `UserTableFilters`

class · defined in `oldman.web.auth.tables`

```python
class UserTableFilters
```

The standard User filters (`filter_<name>` hooks) for any table view whose `model` is the User model.

Members:

- `model: type[Any] | None`
- `async def filter_is_active(query: Any, value: object, table_request: Any)`
- `async def filter_is_staff(query: Any, value: object, table_request: Any)`
- `async def filter_is_superuser(query: Any, value: object, table_request: Any)`
- `async def filter_last_login_from(query: Any, value: object, table_request: Any)`
- `async def filter_last_login_to(query: Any, value: object, table_request: Any)`

## Module `oldman.web.auth.user_management`

Managing other users' accounts: the rules every site applies, and a dashboard's user pages.

Import with `from oldman.web.auth.user_management import <name>`.

### `UserChange`

value · defined in `oldman.web.auth.user_management`

```python
UserChange = Literal['created', 'saved', 'password', 'enabled', 'disabled', 'deleted']
```
