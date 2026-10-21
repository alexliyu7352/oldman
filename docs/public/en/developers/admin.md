# Built-in Admin and extensions

Admin is the `oldman.apps.admin` App, depending on base Web, Auth, and Sessions. Its browser uses Dashboard, Form, Table, Modal, and Feedback from `oldman-web`. See [Run and understand the Admin Demo](../users/admin.md) for a complete application example.

## Entry point and registration

```python
from oldman.apps.admin import AdminSite, AdminUserModelAdmin, ModelAdmin, install_admin, site
```

`site` is the package's default site. You can also create `AdminSite("project_admin")`, register models during one service initialization, and pass it to the installer. Do not create sites per request or reinstall routes.

| Method | Responsibility |
| --- | --- |
| `AdminSite(name="oldman_admin", *, app_registry=None)` | Holds model registrations for this management site |
| `site_title` | Admin name, default `"Oldman Admin"`, used by page titles, sidebar branding, sign-in pages, and password-reset mail. Assign it on the instance or override it in a subclass; customize appearance through templates |
| `register(model, admin_class=None)` | Returns ModelAdmin, using the base class by default; duplicate model registration raises an error |
| `unregister(model)` | Removes registration without database changes |
| `is_registered(model)` | Whether this site has registered the model |
| `get_model_admin(model)` | Returns the model's manager |
| `register_user_model(model)` | Retains a unique dedicated User manager; normally called by the installer |
| `await menu_items(request)` / `await menu_groups(request)` | Builds model menus/App groups from Registry display metadata (`menu_group`, defaulting to the model's App), including only models visible to this request. Links use the installed site prefix; calling before `install_admin()` raises an error |

Registry loads models, views, and commands from installed Apps without automatically importing `admin.py`. Services must explicitly import/register business ModelAdmins. Menus omit inaccessible models, but routes still enforce access independently.

## Installer

Inspect signature types in your editor. Call it as follows:

```python
install_admin(
    app,
    db_manager=None,
    admin_site=None,
    dev_mode=False,
    dev_server_url="",
    extension_bundle_name=None,
    auth_settings=None,
    admin_settings=None,
    password_reset_rate_limiter=None,
    login_rate_limit=None,
)
```

The mount path comes from Admin `app_settings.admin.prefix` (default `/admin`, or supplied `admin_settings.prefix`), not an installer argument. Trailing slashes are stripped; root `/` and external addresses are rejected during configuration loading. The stripped value is the canonical home URL. Oldman Web registers strict-slash routes, so Admin additionally redirects `/admin/` to `/admin` with 301, preserving the query. Sanic apps without strict slashes already accept both forms and receive no duplicate registration.

All arguments except app are keyword-only. The result is the installed `AdminSite`. Defaults use framework database management and site; typed registered-App settings supply Auth/Admin configuration. Usually these three need no explicit arguments.

Prerequisites:

1. Service bootstrap is complete, Auth/Admin are explicitly installed, and Registry has loaded business models.
2. `WebApplication.init()` has created Sanic, Sessions, and related objects, and `get_ext_config()` enables asynchronous templates.
3. Sessions are enabled with reachable Redis, and database migrations have been applied before normal use.
4. Collected Admin manifests/assets exist in production static storage, or Vite development mode is explicitly selected.

The installer reads global `conf.settings.web.static` and SSE settings, not `app.ctx.settings`. It binds the existing `app.ctx.app_registry` instead of creating another Registry. It registers the selected User, wires templates/CSRF, then adds routes. It creates no tables, migrations, or default administrator.

The Admin demo likewise writes no startup data. Its 25 projects live in `apps/demo/fixtures/demo.json` and are explicitly loaded by existing `web loaddata demo`. Fixed permission-test accounts are created only during isolated setup in `scripts/verify-admin-browser-with-servers.py`, not services/fixtures. Ordinary accounts use createsuperuser/changepassword. Restart neither resets passwords nor overwrites projects. Reimport/unique-constraint/transaction semantics remain owned by [JSON data import and export](fixtures.md), without Admin-specific seeding.

Default routes include `/admin`, sign-in/out, model lists/CRUD, `/admin/user-session`, and shared current-password/language endpoints. Model lists use `/admin/<model_path>`; ordinary edits use `/admin/<model_path>/<object_id>/edit`. Generate object URLs with `get_object_url()` rather than manually encoding special string keys.

With the notification App installed, Admin installs shared notification HTTP routes and the center page. SSE separately controls the user-events route. Without notifications, no persistent center/business endpoints are installed, but the shared topbar retains an activity dropdown. That does not enable database notifications. See [Page messages, feedback, and notifications](messages.md).

## ModelAdmin

`ModelAdmin(model, site=None)` generates shared Tables/Forms from SQLAlchemy mappings. Built-in CRUD requires single-column primary keys. Ordinary business models may use integer, string, or UUID keys; Auth User must retain its fixed integer-key contract.

Common class attributes:

| Attribute | Default and purpose |
| --- | --- |
| `list_display` | When empty, up to five primary-key/ordinary columns, skipping password_hash |
| `search_fields` | When empty, searchable text columns, skipping password_hash |
| `ordering` | Primary key when empty; supports `("-id",)` |
| `readonly_fields` | No editable fields generated |
| `exclude` | Columns excluded from generic field handling |
| `page_size` | 20 |
| `table_selectable` | false; does not automatically supply bulk-operation behavior |
| `require_superuser` | false; true restricts this model to superusers regardless of role permissions |
| `add_button_icon` | `ri-add-line`; custom icons must enter the application CSS build |
| `form_card_classes` | `max-w-3xl` |
| `show_form_card_header` | true |

Main extension points:

- `get_list_display()`, `get_search_fields()`, `get_ordering()`, `get_readonly_fields()`: return field sequences.
- `get_table_columns()`: returns shared Table column declarations, defaulting to list_display. See [Static, HTML, and JSON Tables](tables.md) for relationship paths/sorting; arbitrary strings do not become database columns.
- `get_form_class(*, create=True, dialect=None)`: returns a Form class, automatically using `TailwindModelForm`. Overrides retain this signature and can return business ModelForms.
- `build_form(request, *, instance=None, session=None)`: passes the request, instance, and current transaction to the form.
- `async get_object(session, object_id)`: parses the single-column key and loads the instance. Missing objects return None; invalid keys raise `InvalidAdminObjectId`, converted by the site to an appropriate error.
- `async save_model(session, instance)`: defaults to add + flush and returns the instance, without committing the outer transaction.
- `async delete_model(session, instance)`: defaults to delete + flush, also without committing itself.
- `async after_save(request, instance, *, created)`, `async after_delete(request, instance)`: called only **after commit** for creation/edit/deletion. User activation/deactivation/password changes also save the user row and call `after_save` with `created=False`. Defaults do nothing. Use them for work requiring committed changes, such as refreshing an external copy. Exceptions fail the response after saving/deletion has taken effect. If `after_save`, `after_delete`, or `delete_model` raises `ServiceUnavailable` for a required store, Admin Form/Modal requests receive framework `error_code` 1503 and show its translated message; ordinary page requests still receive error pages. `delete_model` runs inside the deletion transaction, so its exception rolls back without deleting anything.
- `await has_view_permission(request, obj=None)`, `await has_add_permission(request)`, `await has_change_permission(request, obj=None)`, `await has_delete_permission(request, obj=None)`: asynchronous booleans checking corresponding model-action permissions by default (see "Permissions and User"). Handlers check once without an object and again after loading it. Override for object-level rules, first awaiting `super()` before additional conditions.
- `row_value(instance, field_name)`, `table_cell_value(instance, field_name, *, admin_prefix)`: customize display. Explicitly mark trusted HTML according to shared Table rules. Defaults render booleans as Yes/No badges, `datetime` as `YYYY-MM-DD HH:MM` with ISO 8601 raw values, and `date` as ISO dates. Other values retain their normalized original form.
- `table_action_html(instance, *, admin_prefix)`, `get_edit_extra_buttons(instance, admin_prefix)`: customize controls while reusing shared DOM/actions protocols.

Save hooks receive the current request transaction. Set business fields there, then call `await super().save_model(session, instance)`. Do not commit separately or assume flush means successful commit. File fields retain [File storage and model file fields](storage.md); Admin does not delete attachments independently.

Display names default to model Meta and can be overridden by ModelAdmin `verbose_name` / `verbose_name_plural`. Top-level menus group Apps using App display_name/icon; second-level entries use model names. Models appear under their owning App by default. `menu_group = "<App-label>"` moves a ModelAdmin under that installed App's group, reusing its name/icon. Framework User/Role ModelAdmins both set `menu_group = "auth"`: project User belongs to its project App and Role to `oldman.apps.roles`, but both appear under Authentication. Unknown menu_group labels fail `install_admin` route installation. `model_path` defaults to the database table name; display-name changes affect neither URLs nor schemas.

## Permissions and User

Sign-in validates the actual password and active/staff flags, then requests use typed Session snapshots rather than rereading User on each render. staff permits Admin sign-in; [Permissions](permissions.md) determines which models/actions are accessible:

- Every registered model except User (below) has four permissions: `admin.<App-label>.<lowercase-class-name>.view`, `.add`, `.change`, and `.delete`, such as `admin.examples.exampleproject.view`. `AdminSite.register()` declares them, making them assignable to roles at service startup. Display names include the model name (for example, "View Articles", using `verbose_name_plural`) to distinguish entries on role forms. `ModelAdmin.permission(action)` returns one. Multiple AdminSites share one model's four permissions. Names use classes rather than table names because legacy names such as `LegacyOrders` or `2024_orders` may violate permission syntax; lowercase class names usually work. Classes starting with underscores or containing non-ASCII letters fail registration and must be renamed, without changing tables/Admin URLs. App labels distinguish same-named classes across Apps, as in Django `app_label.view_model`. Models outside App loading (tests/scripts) omit the App segment. Service model loading writes App labels onto tables, so register afterwards, after `super().init()` in service `init()`. Early registration declares names without App segments but later checks include them. `install_admin` detects that mismatch and fails rather than starting permanently inaccessible permissions. Colliding models fail at second registration rather than sharing permissions. Admin URLs still use table names (`model_path`).
- Superusers hold all permissions. Other staff need roles granting them: without view, menus disappear and lists return 403; without add, create buttons disappear and creation pages return 403; without delete, edit pages omit delete buttons. Row-action buttons are not hidden by permissions: opening/submitting change/delete without permission returns 403. Without `oldman.apps.roles`, only superusers can access models.
- Two switches require superusers: site-wide `app_settings.admin.require_superuser` (`AdminSettings`) and model `ModelAdmin.require_superuser`. The site switch applies to Admin sign-in, home, current-session pages (including self password changes), and every model page; model switches apply to their model pages. Staff sharing sign-in state from another service are still denied even without passing the Admin sign-in page, which also will not redirect them as authenticated. Language changes remain unrestricted, including anonymously. Role permissions do not override these switches. Model switches suppress declaration of the four permissions, so role forms omit them. Site settings are unknown during model registration; those permissions still appear but have no effect.

User management checks Auth's own `auth.users.view`, `.add`, `.change`, and `.delete` (see [Permissions](permissions.md#permissions-declared-by-the-auth-app)), rather than Admin model permissions. Project user-management pages check the same four, so role behavior is consistent everywhere. Additionally, ordinary staff can manage only ordinary accounts, neither staff nor superusers, regardless of role permissions. Selecting staff/superuser during creation/edit, or editing, deleting, activating/deactivating, or changing passwords for privileged accounts, yields "Permission denied". Only superusers may do those operations. Newly assigned roles may grant only permissions already held by the actor, except for superusers. Removing roles or retaining existing roles is unrestricted.

### Role management

With `oldman.apps.roles` installed, the installer registers Role in Admin, retaining an already-registered project ModelAdmin. Roles appears next to users under Authentication. Like user management, it checks App-declared `roles.view`, `.add`, `.change`, and `.delete`, not Admin model permissions (see [Permissions](permissions.md#roles-oldmanappsroles)). Project role-management pages check those same four.

- Creation/editing uses `oldman.apps.roles.forms.RoleForm`: unique name, description, and permissions. All service-declared permissions appear as checkbox groups by declaring App display name, sorted/deduplicated on save. Non-superusers may newly select only permissions they hold; removing/retaining permissions is unrestricted. Stored names not declared by this service (such as another service's `admin.*` sharing the role table) remain hidden and are preserved unchanged. Saving modifies only this service's declarations. Obsolete names no longer declared anywhere cannot be distinguished here and remain too.
- After save commits, `RoleModelAdmin.after_save` writes permissions to the role cache key. Save/delete cache steps call shared `oldman.apps.roles.management` functions also used by project pages. Redis write failure returns 503 after the role is saved; save it again after Redis recovery to repair the cache. This uses framework `error_code` 1503, displaying translated "The permission store is unavailable" rather than generic "Request failed". Deletion removes the cache key inside the transaction before deleting the row, then repeats deletion in `after_delete` after commit (see [Permissions](permissions.md#roles-oldmanappsroles)). If Redis is unavailable, the first step fails with the same 503/1503/message and deletes nothing; retry after recovery.
- Role editors can add only permissions they hold, but can add them to any role, including their own. Grant this capability only to trusted users.
- User creation/edit forms add Roles checkboxes when at least one role exists, preselecting current assignments. Saves write assignments in the same transaction as the user row. Changed roles end all user sign-ins after commit, like active/staff/superuser flag changes. The earlier rules still apply: only superusers edit staff/superusers and therefore assign their roles; staff allowed to edit ordinary users can assign any role to ordinary users.

Built-in permissions do not automatically filter tenant rows. For user-isolated data, complex workflows, or approvals, prefer a business dashboard with explicit queries rather than merely hiding Admin menus.

`AdminUserModelAdmin` supplies User-specific forms, passwords, and state operations. To extend the selected User's management UI, register a subclass of it rather than ordinary ModelAdmin; the installer retains an existing dedicated manager. See [Models and database sessions](database.md) for custom fields, real foreign keys, and migration ownership.

`createsuperuser` and `changepassword` are asynchronous Auth App (`oldman.auth`) commands, available without Admin. The service must install Auth, but Sanic does not start. Scripts/gates use `createsuperuser --noinput`: username (explicit `--username` required) and email are arguments; passwords come from `OLDMAN_SUPERUSER_PASSWORD`, not command-line arguments exposed in process lists/history. Both modes fail if the username exists. `ensure_superuser` would overwrite passwords and promote to active+staff+superuser; repeated release scripts would silently undo administrator password changes, while ordinary usernames would be elevated. Explicitly add `--update` when update-if-present is intended. `change_user_password()` only updates the database password. After changing it, `changepassword` and `createsuperuser --update` call `end_user_logins(user_id)`, invalidating existing Sessions/access tokens. Admin deactivation/deletion and changed active/staff/superuser flags likewise end sign-ins. Profile-only changes (username, email, display name) do not.

## Assets and templates

Project template loaders precede shared/Admin fallbacks. Supply matching `admin/login.html`, `admin/index.html`, or other actually used paths in project templates. Overrides must retain required layout, CSRF, Form messages, bundles, and page-entry contracts rather than copying appearance and losing the protocol.

Admin has two base templates. Sign-in/password reset inherit `admin/auth_base.html`, wrapping standalone shared `oldman/auth/base.html` without sidebar/topbar, with `data-om-page="login"`, Turbo, `csrf-token`, and theme head content. Other pages inherit shell `admin/base.html`. Override `admin/auth_base.html` or `admin/login.html` to restyle Admin sign-in without affecting dashboard authentication. The form itself is shared `oldman/auth/partials/login_form.html`; overriding it changes dashboard too.

To override one page block while inheriting the framework original, prefix the template name with `framework:`. Lookup then searches only framework-provided shared/installed Admin directories. For example, project `admin/login.html` can use `{% extends "framework:admin/login.html" %}` and replace selected blocks. Jinja caches by name; restart after adding overrides.

Production normally uses Admin build files from the current release package and runs service `static collect`. `dev_mode=True` requires a valid HTTP(S) `dev_server_url` pointing to a running Admin Vite service. Production must not depend on development servers.

For CSS extensions, register an application `StaticBundle` with current `app.ctx.static_bundle_registry`, then pass `extension_bundle_name="app:admin-style"`. Its entry must be `.css` with an available build. Default Admin entry remains `oldman:admin`; do not replace shared interactions with another private JS runtime.

Static directories, global Settings, App Settings, bundles, and templates are distinct objects. Do not add another Settings to app.ctx to resolve missing configuration/builds.

<!-- source: zh/developers/admin.md @ 70734786 -->
