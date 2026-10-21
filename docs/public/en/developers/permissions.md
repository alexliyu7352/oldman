# Permissions

A permission describes what a role may do. It exists because code checks it, so declare and release it alongside that code. Declarations define available permissions without granting them to anyone.

## Declarations

Apps declare permissions in their own `permissions.py`:

```python
from oldman.auth import Permission, PermissionSet
from oldman.i18n import gettext_lazy as _


class ReportPermissions(PermissionSet, namespace="reports"):
    view = Permission(_("View reports"))
    export = Permission(_("Export reports"))
```

- Names are `<namespace>.<attribute-name>`, such as `reports.export`. Use the declaring App's label as namespace. Web startup verifies that each namespace belongs to an installed App; misspellings or nonexistent Apps fail explicitly.
- Name permissions by business capabilities, independently of models.
- Names may be declared only once; duplicates fail at import. A `Permission` object may belong to only one `PermissionSet`.
- Reference declared objects (`ReportPermissions.export`) rather than strings, so misspellings fail during import.
- Bulk declarations by name use `declare_permission(namespace, codename, label)`. codenames may contain dot-separated segments such as `project.change`.

## Loading

`AppConfig.permissions_module` defaults to `permissions`. Every service type (Web, persistent service, CLI, Worker) imports this module from each installed App immediately after models in `bootstrap_service()`, skipping absent modules. The complete catalog therefore exists for view imports and CLI bulk role creation. Admin model permissions are declared during model registration instead, existing only in services registering those models. As with views, permission imports must not register database models. Existing unrelated modules named permissions, such as permission-check helpers, also load at every startup. To avoid that, select another `permissions_module` in AppConfig; missing modules are skipped.

Auth's permission module is `user_permissions` (below), because `oldman.auth.permissions` is the declaration mechanism imported by every service. Declaring there would affect services without Auth installed.

`declared_permissions()` returns all declared permissions sorted by name; `get_permission(name)` retrieves one. `Permission` exposes `name`, `namespace`, `codename`, and `label`.

## Permissions declared by the Auth App

Services installing `oldman.auth` have four user-management permissions in `oldman.auth.user_permissions`:

| Object | Name |
| --- | --- |
| `VIEW_USERS` | `auth.users.view` |
| `ADD_USERS` | `auth.users.add` |
| `CHANGE_USERS` | `auth.users.change` |
| `DELETE_USERS` | `auth.users.delete` |

Built-in Admin and custom user-management pages check them (`await require_perm(request, user_permissions.CHANGE_USERS)`), giving roles consistent authority across interfaces. Package `oldman.auth` does not import this module itself; services without Auth lack these four names.

## Roles (`oldman.apps.roles`)

Permissions are assigned to roles, each a set of permission names, and users hold roles. Direct per-user grants are unsupported. Roles and assignments are database records managed at runtime.

Install `oldman.apps.roles` in service `apps`, then migrate following [Project database migrations](migrations.md). It is separate from `oldman.auth` because custom-User projects do not load Auth's models.

Services installing roles have four role-management permissions in `oldman.apps.roles.permissions`, its configured `permissions_module`:

| Object | Name |
| --- | --- |
| `VIEW_ROLES` | `roles.view` |
| `ADD_ROLES` | `roles.add` |
| `CHANGE_ROLES` | `roles.change` |
| `DELETE_ROLES` | `roles.delete` |

Built-in Admin and dashboard `RoleManagementFlow` check these permissions; custom management pages should too, keeping authority consistent. Other roles modules import them only during checks. Services without roles lack these four names.

Two tables:

- `oldman_role`: `id`, unique `name`, `description`, and `permissions` (JSON permission-name array). Deleted IDs are not assigned to new roles.
- `oldman_user_role`: `user_id` referencing `oldman_user.id`, and `role_id`; assignments cascade on user/role deletion.

The database is authoritative. Redis also stores permissions per role under `<core.namespace>:role:<id>`, using Session's security storage connection. `oldman.apps.roles.store` provides:

| Function | Purpose |
| --- | --- |
| `checked_permission_names(names)` | Sort/deduplicate and reject undeclared names; validate before role saves |
| `publish_role(role)` | After save commit, write permissions to its key. Write errors propagate; saving again repairs the entry |
| `forget_role(role_id)` | Delete its key. During deletion, call before deleting the row in the same transaction; Redis failure rolls back without deletion. Call again after commit to remove keys written by requests reading just before deletion. Later queries grant no permissions for this ID |
| `role_permissions(role_ids)` | Union several roles with one MGET. Read missing entries from the database and write only if still absent, preserving newly saved values |
| `user_role_ids(user_id)` | User role IDs in ascending order |
| `replace_user_roles(session, user_id, role_ids)` | Replace assignments within the caller's transaction and return whether they changed |

Built-in Admin includes role management when roles is installed (see [Built-in Admin and extensions](admin.md#role-management)); dashboards install `RoleManagementFlow` (see [Web requests, templates, and permissions](web.md#ready-made-account-flows)). List/create/edit/delete flows are ready-made. Custom pages use `oldman.apps.roles.forms.RoleForm` for name, description, and App-grouped permission checkboxes. Saving/deleting uses three Admin-shared functions in `oldman.apps.roles.management`, maintaining keys in the order above:

| Function | When | Action |
| --- | --- | --- |
| `publish_saved_role(role)` | After save transaction commits | `publish_role`; unavailable Redis raises 503 (`ServiceUnavailable`, “The permission store is unavailable”). The role is already saved; save again after recovery to repair Redis |
| `delete_role(session, role)` | Inside delete transaction | `forget_role` first; unavailable Redis raises 503 and rolls back without deletion. Then delete the row |
| `forget_deleted_role(role_id)` | After delete transaction commits | Repeat `forget_role`; Redis unavailability only logs WARNING |

`oldman.web.auth.roles_installed(app)` reports whether roles is installed.

Assign roles through shared user forms (`oldman.web.auth.user_create_form_class` / `user_edit_form_class`). If roles is installed and at least one role exists, forms include Roles checkboxes loaded from the database, requiring a bound session. After writing the user row in the same transaction, call `await form.save_roles(session, user)` (new users now have IDs). It returns whether assignments changed; if `True`, end that user's sign-ins after commit. Without a roles field it writes nothing and returns `False`.

Only role save/delete code calls `publish_role`/`forget_role`. `loaddata` and direct table edits bypass them. Missing cached keys let the next check read new database values; existing keys retain old permissions until the role is saved again in Admin/dashboard management or its key is deleted.

Known limitation: a request reading a role just before deletion may recreate its key afterward. This affects only sign-ins retaining that ID, not other roles, and requires simultaneous cache absence and deletion.

## Checks

```python
from oldman.web.auth import has_perm, require_perm
from oldman.web.components.tables import SQLAlchemyTableView

from apps.reports.permissions import ReportPermissions


async def export_report(request):
    await require_perm(request, ReportPermissions.export)   # 403 if not held
    ...


class ReportTable(SQLAlchemyTableView):
    async def check_permission(self, request, *, method_name, route_kwargs):
        return await has_perm(request, ReportPermissions.view), None   # 403 without querying report data if not held
```

- Superusers hold all permissions without queries; signed-out callers hold none. Other users hold permissions granted by their roles at sign-in.
- Role IDs travel with sign-in: services installing `oldman.apps.roles` write them into Session snapshots and access-token `roles` claims on token issuance/refresh. Read them through `request.ctx.user.role_ids`. Services without roles issue sign-ins without roles and admit only superusers through checks. Even shared Sessions carrying role IDs from another service do not activate roles here or read role cache/tables.
- The first check per request fetches a permission set from the role cache; later checks reuse it. Missing roles load from the process `db_manager` by default. If roles use another database, such as Admin's own `DatabaseManager`, pass `db_manager=` to `has_perm`, `require_perm`, or `permissions_not_held`; built-in Admin does so. Unavailable role Redis returns 503, not permission denial.
- Checks accept only declared `Permission` objects; strings fail.
- Business code chooses checks: views call `require_perm`; table/chart/select hooks follow the layers below. The framework adds no separate declarative component properties. Templates do not decide permissions; backends omit unauthorized content or reject operations.
- Grant only permissions you hold. `await permissions_not_held(request, names)` returns sorted names absent from the current user (always empty for superusers). Shared user forms use it when **adding** roles, and `RoleForm` when **adding** permissions. For non-superusers, all permissions in newly assigned roles and all newly added permissions must be held already, or validation fails. Removing/retaining existing grants is unrestricted. Otherwise role/user editors could escalate privileges through their own roles or accounts. Custom grant pages should enforce this too.
- Role permission changes affect holders immediately without new sign-in. When assignments change (`replace_user_roles` returns `True`), callers end user sign-ins after commit through `revoke_user_logins` or `end_user_logins`, because existing Sessions/tokens retain old IDs. Role deletion ends no sign-ins but grants no permissions for retained deleted IDs. This relies on IDs not being reused: SQLite uses `AUTOINCREMENT`; PostgreSQL and MySQL 8.0+ sequences do not roll back. MySQL 5.7 and earlier keep counters only in memory and resume after the current maximum following restart, allowing deleted maximum IDs to recur. Before deleting roles there, query assigned users through `UserRole` (`oldman_user_role`), then call `end_user_logins(user_id)` after deletion for all of them.
- Complete demo: [apps/examples/permissions.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/permissions.py) declares `examples.view_projects`; the project table's `check_permission` in [apps/examples/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/tables.py) checks it. All signed-in users can open the page, but table data returns 403 without a role granting that permission. User management checks `auth.users.*`. Fixtures include Project viewers granting `examples.view_projects` and User managers granting `auth.users.*`; assign them in user editing.
- Built-in Admin uses these same checks to determine models/actions available to staff. See [Built-in Admin and extensions](admin.md#permissions-and-user) for four automatically declared model permissions.

## Permission layers in data components

Table/chart/select data endpoints pass four layers in order. Each asks a different question and has different inputs:

| Layer | Timing | Available inputs | Question | Rejection |
| --- | --- | --- | --- | --- |
| `require_authenticated` (switch, component default True) | First | request | Signed in? | Authentication protocol: 401, page requests redirect to sign-in |
| `check_permission(request, *, method_name, route_kwargs)` | Before parameter parsing or database sessions | User, HTTP method, route parameters | Whole-request denial without data access: staff, role permissions, route arguments | 403 |
| `check_auth(table_request)` / `check_auth(chart_request)` | After parameter parsing (and chart validation); SQLAlchemy read session open | Parsed request: user (`.request`), routes, filters, search; database queries allowed | Whole-request denial requiring parameters or queries | 403 |
| Data scope: table `apply_base_filters(query, table_request)`, select `get_queryset(request, context)`, chart `get_result(chart_request)` | Query construction | User, routes, query parameters, query itself | Which rows are visible? | Narrows results without rejecting |

This runnable example appears on complete demo Access Guards (`/examples/auth/guards`): [apps/examples/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/tables.py)
defines `TeamProjectTable`, extending the example project table. Its three hooks answer different questions. The page shows which hook handles four requests (anonymous, non-staff, staff selecting an inactive team, staff selecting an active team)
and displays the class source.

```python
class TeamProjectTable(ExampleProjectTable):
    """One team's projects, read-only: how a data endpoint decides who gets what, one hook per question.

    The Access Guards example page mounts it. Each hook answers at its own moment:

    - ``check_permission`` — before the parameters are parsed or a session is opened: staff only. It
      replaces the parent's role check; a subclass states its own rule.
    - ``check_auth`` — after the parameters, with the read session open: the team in the path must
      exist and be active, which only the database knows. It can refuse the whole request, nothing less.
    - ``apply_base_filters`` — which rows: this team's projects. It refuses nothing; totals, pages and
      search all count within it.
    """

    route_name = "example_team_projects_table"
    route_path = "/examples/auth/teams/<team_id:int>/projects/table"
    selectable = False
    export_formats = ()
    empty_message = _("This team has no projects.")
    # Read-only: no team column (it is the one in the path) and no edit or delete buttons.
    columns = tuple(
        column for column in ExampleProjectTable.columns if isinstance(column, Column) and column.name not in {"team", "action"}
    )

    async def check_permission(self, request, *, method_name: str, route_kwargs: dict[str, object]) -> tuple[bool, str | None]:
        """Staff only, decided from the signed-in user alone."""
        del method_name, route_kwargs
        return request_user(request).is_staff, None

    async def check_auth(self, table_request) -> bool:
        """The team in the path must exist and be active."""
        team = await self.require_db_session().get(ExampleTeam, table_request.route_kwargs["team_id"])
        return team is not None and team.is_active

    async def apply_base_filters(self, query, table_request):
        """Only this team's projects."""
        return query.where(ExampleProject.team_id == table_request.route_kwargs["team_id"])
```

User-specific row restrictions, such as showing members only their own projects, also belong in `apply_base_filters`. Its scope governs totals, pagination, and exports together.
Do not place them in `check_auth`, which can reject only the entire request and cannot alter the query used for counts, pagination, or exports.
Selects use one central endpoint for all providers. Dispatch does not yet know the provider; put individual rules in provider `check_auth(request, context)`.
Framework `UserTable` requires `auth.users.view` in `check_permission`. Built-in Admin tables express staff (or required superuser) plus model permissions in
`check_permission`, using the same dispatch.

<!-- source: zh/developers/permissions.md @ c47d6711 -->
