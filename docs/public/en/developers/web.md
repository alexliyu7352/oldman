# Web requests, templates, and permissions

This chapter covers services using `WebApplication`. Read [the application lifecycle](applications.md) for configuration/App loading and [Demo HTML/JSON tables and Modal forms](../users/tutorial-dashboard.md) for complete wiring. Business excerpts come from EPG services/web.py, apps/dashboard/views.py, and apps/examples/session.py. Account pages use framework `oldman/web/auth`, without another tasks App.

## Routes and request objects

Internally this uses Sanic directly. Common public imports:

```python
from oldman.web import (
    Request, Response, WebApp, router,
    api_response, html_response, json_response, redirect_response,
    render_template, replace_html_response,
)
```

In installed App `views.py`, import `from oldman.web import router` and use `@router.get()`, `@router.post()`, and related decorators. Registry loads views after the Web runtime exists. Do not import views in `apps.py`, models, or settings, or create another Sanic instance.

Importing a view module does not fail merely because no Web server exists yet. If this process's Web service has already created its application, registrations take effect immediately. Otherwise, registrations are saved until the Web service creates its application, then applied once before views load. This covers Shell, scripts that only call `bootstrap_service()`, App commands, and modules imported before service construction. In a process without a Web service, those registrations never take effect. Errors such as duplicate route names therefore surface when the application is created, still during startup.

`request.args`, `request.form`, and `request.files` are query parameters, form data, and uploads respectively, not interchangeable inputs. `TailwindForm.from_request()` reads forms/files without converting arbitrary JSON into fields. JSON APIs may validate dedicated input models through `msgspec.json.decode(request.body, type=...)`.

## Client addresses and proxies

`request.ip` is the TCP peer. `request.client_ip` is Sanic's proxy-resolved client address, falling back to `request.ip` without trusted proxy headers. [The IP allowlist](#ip-allowlist) requires both in one entry. Sign-in records and sign-in/reset rate limits use `oldman.web.request.client_ip(request)`: `request.client_ip`, then `request.ip` only if empty. Security decisions should use only these properties.

Sanic trusts only the proxy topology you declare. WebApplication writes three `settings.web` fields into Sanic config during `init()`:

| Field | Sanic behavior |
| --- | --- |
| `real_ip_header` (default `X-Real-IP`) | Uses the header directly regardless of sender. Proxies must overwrite client-supplied copies, not forward them. Direct service-port access otherwise lets anyone forge addresses |
| `proxies_count` | Selects the Nth `X-Forwarded-For` value from the right, added by the final N trusted proxies. Unset ignores the header |
| `forwarded_secret` | Accepts RFC 7239 `Forwarded` only with matching `by=`/`secret=` |

Clients control the leftmost `X-Forwarded-For` value and can forge it. None of these settings guesses which private addresses to discard or public addresses to retain.

`oldman.utils.http.first_public_ip(request)` provides that heuristic: read `FORWARDED_CLIENT_IP_HEADERS` in order and return the first globally routable IPv4/IPv6 address (`ipaddress.is_global`), otherwise a public peer address, otherwise `None`. Use it for error-tolerant logging/statistics, not authentication or access control. It does not overwrite `request.client_ip`.

## Custom middleware

Use native Sanic middleware; there is no separate registration interface. Request middleware `async def fn(request)` returns `None` to continue or a response to bypass views. Response middleware `async def fn(request, response)` modifies/replaces responses and still runs after short-circuiting. Both functions below were verified with actual Sanic 25.12 requests:

```python
from oldman.web import Request, Response, json_response


async def block_legacy_api(request: Request) -> Response | None:
    """Returning a response short-circuits request handling and skips the view."""
    if request.path.startswith("/legacy/"):
        return json_response({"error": "gone"}, status=410)
    return None


async def add_no_store(request: Request, response: Response) -> None:
    """Response middleware also runs after a short-circuited request."""
    response.headers.setdefault("Cache-Control", "no-store")
```

Register inside the service's `init()` override: call `super().init()`, then obtain Sanic through `self.runtime_app`. The demo's `init()` override that installs CSRF and notification routes in [the application lifecycle](applications.md#wiring-templates-and-base-capabilities) uses this location:

```python
from oldman.runtime import WebApplication


class WebService(WebApplication):
    def init(self) -> None:
        super().init()
        app = self.runtime_app
        if app is None:
            raise RuntimeError("Sanic app was not initialized")
        app.register_middleware(block_legacy_api, "request")
        app.register_middleware(add_no_store, "response")
```

When `super().init()` returns, the base class has installed messages, Session, Storage, SSE, and i18n middleware and loaded views according to their settings. Request middleware registered afterwards follows them and can read `request.ctx.locale`, `request.ctx.translations`, and the open Session. Do not register middleware while importing `apps.py`, models, or views: the Sanic instance may not exist yet, and views should not depend on import-order side effects.

When multiple middleware functions are registered at the same location, higher `priority` runs first. At equal priority, request middleware follows registration order, and response middleware runs in reverse order. The base Session, messages, and i18n middleware all use `priority=0`, so request middleware registered in `init()` with the default priority follows them. Pass a higher `priority` explicitly when middleware needs to run before Session opens. In actual tests, request middleware registered as `first`, `second`, and `high(priority=10)` ran in the order `high, first, second`; response middleware registered as `resp_a` and `resp_b` ran in the order `resp_b, resp_a`.

The framework's own middleware demonstrates this mechanism. Session registers middleware to open and save sessions in `oldman/web/session/__init__.py`; its request middleware returns 503 directly if Redis fails. In `WebApplication.init()`, i18n registers `install_i18n` and `cleanup_i18n` first, before Session, messages, and authentication. Rejections from those middleware functions, such as a 503 for unavailable storage, therefore use the request's language. Language comes only from paths, query parameters, Cookies, and Accept-Language, independently of sign-in; see [which language a request uses](assets.md#which-language-a-request-uses). Under the reverse response ordering described above, `cleanup_i18n` runs last, so translations remain bound while other response middleware runs. Settings control their installation. Do not register them again in service classes.

## Enable templates

`WebApplication.get_ext_config()` defaults to `None`. This complete method comes from demo [WebService](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py); Any is from typing and settings from project config.settings:

```python
    def get_ext_config(self) -> dict[str, Any]:
        """Return Sanic-Ext settings."""
        return {
            "oas": False,
            "oas_autodoc": False,
            "templating_path_to_templates": settings.web.template.dir,
            "templating_enable_async": True,
            "logging": False,
            "cors": True,
        }
```

Service `init()` first calls `super().init()`, checks `self.runtime_app`, then installs CSRF, notifications, `install_dashboard_templates`, and account pages. `install_dashboard_templates` wires shared templates through `install_template_loaders(app.ext.environment, settings.web.template.dir)` and registers translation, bundle, and menu globals. Tutorials provide the complete service. Do not construct a second Jinja Environment or Sanic-Ext wrapper. cors above is a demo-specific choice; templates do not require cross-origin access.

`settings.web.template.dir` selects the project template directory. Ordinary projects use one directory, without automatically searching every installed App's `templates/`. The demo organizes business templates under templates/pages and templates/partials.

Lookup order is explicit project directories, existing environment loaders, then framework shared templates. Same-relative-path project files override shared templates, such as `templates/oldman/forms/default/message.html`. Component renderers reuse the request's template environment rather than maintaining another theme.

To override only part of a page, inherit its framework original. Prefix `framework:` searches only framework directories: shared templates and registered framework App directories such as installed Admin. Project `templates/oldman/dashboard/account/login.html` can use `{% extends "framework:oldman/dashboard/account/login.html" %}` and override `auth_description`. Ordinary parent names in originals, such as `base.html`, still prefer project directories. Jinja caches by name; restart after adding overrides. For all templates, use `./run.sh <service> templates copy` (see [CLI reference](cli.md)). Framework Apps register directories through `oldman.web.template.add_framework_template_dir(environment, directory)`; `framework_template_dirs(environment)` returns the list.

Distinguish full HTTP responses from HTML content. This home view comes from demo [apps/dashboard/views.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/dashboard/views.py); router, Request, `login_required`, and render_template are imported there, and `dashboard_page_context()` is defined in the same file:

```python
@router.get("/", name="dashboard")
@router.get("/dashboard", name="dashboard_alias")
@login_required()
async def dashboard(request: Request):
    """Render actual business statistics for all signed-in accounts, as in the scaffold; no personal data."""
    return await render_template("pages/dashboard.html", context=await dashboard_page_context(request, "dashboard_overview"))
```

In contrast, public `oldman.web.template.render_component_template(owner, template_name, context)` returns `Markup`, using `owner.request` for the current environment. Form/Table renderers and custom components use it; it sends no HTTP response. Views render fragments with `await render_fragment(request, template_name, **context)`, returning `Markup` from the installed environment with `request` in context. Initial demo Modals build title/html JSON this way; see [the Modal tutorial](../users/tutorial-dashboard.md#4-modal-only-loads-content). Views must not access `request.app.ext.environment` directly. All environments provide shell globals `current_language(request)`, `language_menu_items(request)` (`oldman.web.i18n`, for language menus/`<html lang>`), and `csrf_token_for(request)` (`oldman.web.security.csrf`, for `csrf-token` meta). `oldman/dashboard/partials/language_switcher.html` uses these when no arguments are supplied, hiding itself for one language. `site_name()` returns `core.site_name` or `core.app_name` for error/authentication pages and dashboard sidebar branding when `dashboard_sidebar` has no `brand_name`. Still supply required template context explicitly. Async Jinja may call `{{ form.render() }}`; Python requires `await form.render()`.

## Session and authentication are not automatic sign-in systems

```yaml
web:
  session:
    enabled: true
    redis_alias: SESSION
```

Enabled Session automatically installs WebApplication read/write middleware. Connections come from service `settings.redis`; there is no production Memory Session. Session Redis reads/writes failing return 503 rather than pretending anonymous success.

Session middleware also lets subsystems use the Session Cookie policy: `Session.get_session_manager(request).send_cookie(request, name, value, max_age=...)` schedules a Cookie for response processing after session save, including unchanged sessions skipped for saving. Domain, Secure, and SameSite match Session, with HttpOnly enabled. `opened_session_id(request)` returns the request's recorded SID or None on handcrafted requests bypassing middleware. `send_cookie` requires a middleware-processed request. Anonymous CSRF Cookies use this mechanism, below.

Demo [apps/examples/session.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/session.py) imports SessionData/get_session_data from oldman.web.session and Request from oldman.web.request. Its original class/accessor follow. WebService.SESSION_MODEL selects this subclass:

```python
class DashboardSessionData(SessionData, kw_only=True):
    """Keep an application-specific Session type without duplicating base fields."""


def dashboard_session(request: Request) -> DashboardSessionData:
    """Return this application's concrete request Session model."""
    return get_session_data(request, DashboardSessionData)
```

`SessionData.user_id` is `int | None`. Session data also includes username, display name, sign-in IP and time, and snapshots of the active, staff, and superuser flags. Add custom fields through a subclass and select it with the service's `SESSION_MODEL`. Reading a Session does not query the user database every time. After changing user permissions, revoke the affected Sessions to invalidate their old authorization snapshots. Framework entry points accepting user IDs, including session storage, token issuance and revocation, and user services in `oldman.auth`, accept only `int` itself. Subclasses such as `bool` and `IntEnum` raise TypeError: user IDs are rendered as text in Redis keys and token claims, and a subclass's text may differ from the number it represents. `oldman.security.require_user_id()` enforces this rule centrally.

`oldman.web.auth.authenticate_credentials(request, username=..., password=...)` checks credentials through `web.auth.login_backends` in order; the first recognizing them decides. Default `users` delegates to `oldman.auth.authenticate_user`, checking existence, active state, and password without staff requirements. Regardless of backend, `authenticate_credentials` rejects inactive accounts: all sign-ins require active users, so `request.ctx.user` contains only active users. Sites add restrictions, such as Admin staff. Custom backends use class import paths, no-argument construction, `name`, and `async authenticate(request, **credentials)`. Read only recognized keywords (such as `token=` for devices); return `None` if unrecognized, or the User to sign in.

The demo does not reimplement sign-in. Account pages use framework `LoginFlow` below without `accept_user`, like dashboard scaffolds. All active users may sign in and access pages; only permission examples add `staff_required` or role checks. Ordinary business sites need not inherit Admin's staff restriction.

Sign-in forms, user filters, and user creation and editing ModelForms come from `oldman.web.auth`: `LoginForm`, `UserFilterForm`, `user_create_form_class(User)`, and `user_edit_form_class(User)`. The user list comes from `oldman.web.auth.UserTable`, which lists emails and flags for all accounts and requires `auth.users.view` in its own `check_permission`; superusers hold that permission. Subclasses supply only `model`, the route name, and `object_url(row, action)`. The cell and row-menu helpers `user_cell_value` and `user_row_actions` can also be used separately. User-management self-protection rules, `set_user_active`, `validate_user_delete`, and `UserManagementError`, come from `oldman.auth`. Only superusers may manage staff and superuser accounts. `oldman.web.auth.can_manage_user(request, target=None, *, makes_privileged=False)` enforces this rule. Bound user forms check the operator through their request and reject non-superusers who create or edit privileged accounts or select either flag. Delete, activation, and password views that do not use these forms call `can_manage_user(request, user)` after fetching the user, as both the built-in Admin and `UserManagementFlow` do. After changing a password, active state, flags, or roles, or deleting an account, call `await finish_user_change(request, user_id, login_url=...)` to end that account's sign-ins. When the account belongs to the operator, it returns a response explaining that they must sign in again and redirecting to `login_url`; return that response directly. Otherwise it returns None. Use `user_change_text(change, username=..., request=request)` for consistent success messages. Row-menu status and deletion modals come from `oldman.web.auth.user_status_modal_response(request, user, action=...)` and `user_delete_modal_response(...)`. Views only fetch users by ID and provide the form's POST URLs. Pass `None` for a missing user to receive a 404 modal response. Projects and Admin share these helpers. Dashboard and Admin sign-in submissions use the same handler installed by `LoginFlow` below. The following is its original code from `register_routes()` in `oldman/web/auth/login.py`, with method indentation removed. form_value, remember_me_requested, login_error_url, login_user, and safe_next_url come from `oldman.web.auth`. safe_next_url accepts only same-site paths and rejects external URLs, `//host`, backslashes, and control characters. `authenticate_credentials` is described above. `self.limiter()` counts failed sign-ins against Auth's `login` limits. redirect_response and the CSRF decorators come from the framework. This handles native sign-in submission, rather than JSON Form submission:

```python
@csrf_protect()
@add_csrf_token()
async def login_submit(request: Any):
    next_url = safe_next_url(form_value(request, "next", str(request.args.get("next", "") or "")), self.home_path)
    username = form_value(request, "username").strip()
    limiter = self.limiter()
    # Before the password is checked, so a spent budget costs no PBKDF2 round.
    retry_after = await limiter.retry_after(request, username)
    if retry_after is not None:
        response = await login_page(request, error=RATE_LIMITED, next_url=next_url)
        response.status = 429
        response.headers["Retry-After"] = str(retry_after)
        return response
    user = await authenticate_credentials(
        request,
        username=username,
        password=form_value(request, "password"),
        auth_settings=self.auth_settings,
        db_manager=self.db_manager,
    )
    # Refused by the site's own rule, an account gets the wrong-password answer: telling
    # them apart would confirm the password was right.
    if user is None or (self.accept_user is not None and not self.accept_user(user)):
        await limiter.record_failure(request, username)
        return redirect_response(login_error_url(self.login_path, next_url, INVALID_CREDENTIALS), status=303)
    return await login_user(
        request,
        user,
        response=redirect_response(next_url),
        remember=remember_me_requested(request),
        auth_settings=self.auth_settings,
        db_manager=self.db_manager,
    )
```

`user` is the authenticated real User. `login_user()` uses `session_data_for_user()` with the request's Session type (DashboardSessionData in the demo), remember-me expiry, and proxy-aware IP. It creates an exclusive sign-in through exclusive_login and writes a Cookie. Use public login() yourself for multiple same-user sessions. `await logout_user(request, "/login")` calls `Session.logout_session` and schedules Cookie removal. Force sign-out with `await session_manager.force_logout_user(user_id)`. These are server operations; deleting a browser flag is not sign-out. Wrong passwords return to GET sign-in with an error and fresh CSRF. Expired CSRF follows the 403 flow below; do not bypass it as a password error.

## Ready-made account flows

Do not handwrite sign-in, sign-out, profile pages, user management, and role management for every site. `oldman.web.auth` provides three flows, and the roles App provides `RoleManagementFlow` (`oldman.apps.roles.management`). They all have the same shape as `PasswordResetFlow` under [password reset](security.md#password-reset-tokens): a dataclass accepts page paths and optional `auth_settings` and `db_manager`, defaulting to the installed Auth App's settings and the process database manager. `register_routes(app=None, *, render=None, template_prefix=None, name_prefix="")` installs routes. Supply either `render=`, an `async def render(request, page, /, **context)` function returning a response, or `template_prefix=`, which renders `<template_prefix>/<page>.html`. Supplying both or neither raises `ValueError`. Omitting `app` registers through `oldman.web.router`. All route names carry `name_prefix`.

| Flow | Routes | Pages and context | Access |
| --- | --- | --- | --- |
| `LoginFlow(login_path, logout_path, home_path, password_reset_path=None, accept_user=None, rate_limit=None, ...)` | GET/POST `login_path`, GET `logout_path`; names `login`, `login_submit`, `logout` | `login`: `login_form`, `login_url`, `next_url`, `login_error`, `password_reset_url` | Active accounts; optional `accept_user(user)` adds site restrictions, rejecting identically to wrong passwords. Signed-in browsers go directly to `next` (checked by `register_routes(is_authenticated=...)`, Session by default). Failed sign-ins count against Auth `login` `ip_limit`/`username_limit`; excess returns 429 |
| `AccountFlow(profile_path, login_path, logout_path, language_path, notification_routes=None, user_events_path=None, ...)` | Profile at `profile_path`; self-password at `<profile_path>/password-modal` and `<profile_path>/password`; POST `language_path` exclusively writes language Cookies. `notification_routes` installs center at `center_url`; `user_events_path` plus `web.sse.enabled` installs user SSE and makes `register_routes` return that path, otherwise None | `user_session`: `session_profile`, `session_path`, `password_modal_path`, `logout_path`; `user_notifications`: `notification_center_content` | `register_routes(allow=...)`, signed-in by default. Signed-in denial returns 403; anonymous uses sign-in protocol. Language preferences allow every visitor, including on sign-in pages |
| `UserManagementFlow(base_path, login_path, user_model=None, ...)` | List `base_path`, data `<base_path>/table`, new `<base_path>/new`; accounts `<base_path>/<id>/edit`, `/password`, `/status`, `/delete`; content `/password-modal`, `/status-modal`, `/delete-modal`; data route name `users_table` | `users/index`: `table`, `filter_form`, `users_url`, `new_url`; `users/form`: `form`, `user` (None on creation), `action`, `users_url` | View/add/change (edit/password/active)/delete require `auth.users.view`, `.add`, `.change`, `.delete`; superusers hold all. `can_manage_user` additionally applies |
| `RoleManagementFlow(base_path, login_path, db_manager=None)` | List `base_path`, data `<base_path>/table`, new `<base_path>/new`; roles `<base_path>/<id>/edit`, `/delete`, content `/delete-modal`; data route name `roles_table` | `roles/index`: `table`, `roles_url`, `new_url`; `roles/form`: `form`, `role` (None on creation), `action`, `roles_url` | View/add/change/delete require `roles.view`, `.add`, `.change`, `.delete`; superusers hold all. `RoleForm` permits non-superusers to add only held permissions. Save/delete maintain role cache in Admin's order; unavailable Redis returns 503 with a permission-storage error, deleting nothing on failed deletion. Role deletion ends no sign-ins. `register_routes` rejects `app` instances without roles installed |

All sign-ins require active accounts. Built-in Admin adds staff through `accept_user`; dashboards admit all active users by default. Use `staff_required` for staff-only pages or `require_perm` for individual permissions (see [permission entry points](#permission-entry-points)).

Built-in Admin, dashboard scaffolds, and the EPG demo use these flows. Admin ([oldman/apps/admin/site.py](https://github.com/alexliyu7352/oldman/blob/main/oldman/apps/admin/site.py)) mounts beneath its own prefix and adds menu context through `render=`. Its original sign-in setup:

```python
        login_flow = LoginFlow(
            login_path=login_path,
            logout_path=f"{prefix}/sign-out",
            home_path=prefix,
            password_reset_path=f"{prefix}/password-reset",
            # Every login requires an active account; the Admin adds staff (or superuser) on top.
            accept_user=lambda user: has_staff_access(user, require_superuser=admin_settings.require_superuser),
            rate_limit=login_rate_limit,
            auth_settings=auth_settings,
            db_manager=manager,
        )
```

Dashboard paths come from [account-page addresses](configuration.md#account-page-addresses):

| Parameter | Setting |
| --- | --- |
| `LoginFlow` `login_path`, `logout_path`, `home_path`, `password_reset_path` | `web.account.login_url`, `logout_url`, `login_redirect_url`, `password_reset_url` |
| `AccountFlow` `profile_path`, `login_path`, `logout_path`, `language_path`, `user_events_path` | `web.account.profile_url`, `login_url`, `logout_url`, `i18n.preference_url`, `web.account.user_events_url` |
| `AccountFlow` `notification_routes` | Return from `oldman.web.messages.notifications.init_app(app)` when notifications are installed |
| `UserManagementFlow` `base_path`, `login_path` | `web.account.users_url`, `login_url` |
| `RoleManagementFlow` `base_path`, `login_path` | `web.account.roles_url`, `login_url` |
| `PasswordResetFlow` `base_path`, `login_path`, `home_path` (see [password reset](security.md#password-reset-tokens)) | `web.account.password_reset_url` (omit flow when unset), `login_url`, `login_redirect_url` |

For a dashboard, `startproject` generates `apps/accounts/routes.py` with four flows wired according to this table: sign-in, profile and notifications, user management, and role management. The service calls it in `init()`. To restrict sign-in to certain accounts, pass `accept_user` to `LoginFlow`; to support password recovery, install `PasswordResetFlow` alongside it. The EPG demo's [apps/accounts/routes.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/accounts/routes.py) is this same source with `PasswordResetFlow` added at the end. See [dashboard scaffold scope](assets.md#dashboard-scaffold-scope) for the rest of the scaffold.

Install flows in the service's `init()` after `super().init()`, at the same location as `install_admin`; `app` is `self.runtime_app`. Setting `template_prefix="oldman/dashboard/account"` uses the bundled dashboard account pages. Sign-in and password-reset pages (`PasswordResetFlow` uses `oldman/dashboard/account/password_reset`) inherit `oldman/dashboard/account/auth_base.html`, which wraps the shared standalone authentication page `oldman/auth/base.html`. They have no sidebar or top bar, use `data-om-page="login"`, and load the project's `app_main_bundle`. Profile, notification-center, user-management, and role-management pages inherit the project's own `base.html`. Override same-name templates in the project directory or inherit `framework:` originals to change part of a page; see [enabling templates](#enable-templates). In the browser, `startDashboard` uses `AuthPage` to mount authentication pages; see [the frontend reference](frontend.md#framework-startup-entry-point).

Account links in project templates use the template global `account_urls(request)`, rather than hardcoded paths. It returns `home` (`web.account.login_redirect_url`, the destination after sign-in), `login`, `logout`, `profile`, `users` (`web.account.users_url`, user management), `roles` (`web.account.roles_url`, role management), `password_reset`, `user_events` (populated only when `web.sse.enabled` is on), and `notifications` (`{"center": ..., "topbar": ...}` when notifications are installed, otherwise None). The earlier sign-in submission handler is installed by `LoginFlow`: validation of `next`, error display, rate limits, and remember-me handling are all part of the flow, so sites do not rewrite them.

## Request authentication: request.ctx.user

Before views, every request passes an authentication pipeline. Results occupy two fixed locations regardless of credentials:

- `request.ctx.user`: a signed-in user snapshot (`id`, `username`, `display_name`, `is_staff`, `is_superuser`, `role_ids`, and true `is_authenticated`), or an anonymous user with false `is_authenticated` and all permission flags false. It is a snapshot taken at authentication time, rather than a database row; reading it does not query the database. Fetch the full User by `id` when needed.
- `request.ctx.auth`: recognized authenticator (`method`, such as `"session"`), or `None` when anonymous.

```python
@router.get("/me", name="me")
@login_required(response_mode="json")
async def me(request: Request):
    return json_response({"id": request.ctx.user.id, "via": request.ctx.auth.method})
```

The pipeline tries `web.auth.authenticators` in order. The first authenticator recognizing credentials decides; if none does, the request is anonymous. Without an explicit setting, it uses only `session` when Session is enabled, otherwise no authenticators. Listing `session` without enabling Session fails startup. Custom authenticators use class import paths. Each class takes no constructor arguments, provides `name` and `async authenticate(request)`, and returns `oldman.web.authentication.Authentication` when it recognizes credentials, otherwise `None`. Do not respond to the request here; rejection belongs to the permission layer.

```yaml
web:
  auth:
    authenticators: [session, apps.accounts.auth.DeviceTokenAuthentication]
```

After successful `login_user()`, the rest of the request sees the new user. `logout_user()` makes Session-authenticated requests anonymous. Browser-session pages (profile/self-password) accept only authenticated Sessions. `authenticated_session(request)` retrieves one; other authenticator types get 401.

## Bearer access tokens (JWT)

Separate frontends, mobile clients, and other services authenticate through the `Authorization: Bearer <token>` header. Add `jwt` to the authenticators and configure a signing secret:

```yaml
web:
  auth:
    authenticators: [session, jwt]
    jwt:
      secret: "a random string of at least 32 characters"
```

`oldman.web.authentication.issue_access_token(user, role_ids=...)` returns `AccessToken` with token, `expires_in`, and claims. Claims snapshot the user at issuance: `sub` ID, username, display name, staff, superuser, and role IDs in `roles` (see [Permissions](permissions.md)), plus `iat`, `exp`, and `jti`. Invalid/missing `roles` claims are rejected. Reading tokens does not query users. Only case-insensitive `Bearer` is accepted, not `Token` or query parameters.

- Missing, malformed, expired, or wrong-key tokens leave authentication anonymous, allowing permission layers to return 401 instead of rejecting during recognition. This avoids interfering with shared-key Bearer endpoints.
- Bearer-presenting requests always receive JSON 401/403, not sign-in redirects.
- Clients explicitly attach tokens; browsers do not send them automatically, so CSRF is skipped. A signed-in Session on the same request still requires CSRF.
- SSE supports Session only: browser EventSource cannot attach headers.
- Put `session` before `jwt`, so Session decides identity when both credentials appear.

**Refresh tokens.** Short-lived access tokens are renewed with refresh tokens without another sign-in. Refresh tokens are random strings stored in Redis only as SHA-256 digests. Each sign-in begins a family: `issue_refresh_token(user_id)` issues the first; `rotate_refresh_token(token)` replaces each used token with the next, invalidating the old one. New expiry starts at rotation using `web.auth.jwt.refresh_token_ttl`. Reuse indicates two parties sharing a family without a trustworthy owner, so the entire family is revoked and both must sign in again. Concurrent refreshes follow this rule: only one succeeds. Family revocation does not retract already issued access tokens; they expire naturally. `revoke_refresh_token(token)` ends one family's client sign-in. `refresh_token_user(token)` looks up ownership without consuming it: fetch/check users before rotation, so intermediate failures such as transient database outages leave tokens usable and retries are not treated as replay. Token routes follow this order. Inactive users returned by login backends get 401 during token issuance too.

**Obtain, refresh, and revoke endpoints.** The framework provides three endpoints; projects decide who may obtain tokens:

```python
from oldman.auth import has_staff_access
from oldman.web.auth import TokenFlow

TokenFlow(accept_user=has_staff_access).register_routes(
    obtain_path="/api/token",
    refresh_path="/api/token/refresh",
    revoke_path="/api/token/revoke",
)
```

- `accept_user` is required without a default. A staff-only site's token endpoint must not accidentally issue tokens to everyone. It runs at issuance and every refresh against the latest database user. Deactivated, deleted, or no-longer-eligible accounts receive no new token at next refresh and their family is revoked.
- Obtain: pass request-body JSON/form `username` and `password` to [the sign-in backend](#session-and-authentication-are-not-automatic-sign-in-systems). Change `credential_fields` for other credentials; extra client fields are not forwarded. Failures share sign-in-page limits; success updates last sign-in time.
- Refresh: body `refresh_token` returns a new pair and invalidates the old refresh token.
- Revoke: body `refresh_token` ends its family; any access token presented in the header is also revoked immediately. Already invalid refresh tokens still return success.
- None writes Cookies or requires CSRF (all are `csrf_exempt`). Other sites can submit browser requests but cannot read returned tokens. Every response has `Cache-Control: no-store`.
- Omit `app` to register through `oldman.web.router`; names are `<name_prefix>token_obtain`, `..._refresh`, `..._revoke`. Issuers must configure `web.auth.jwt.secret`. Registration does not check it because views call `register_routes` during import, which must succeed without running services; a missing secret fails at the first request instead. Token consumers list `jwt`; issuer-only services need not.

Responses use the shared JSON envelope:

```json
{"error_code": 0, "message": "", "data": {"access_token": "…", "token_type": "Bearer", "expires_in": 900, "refresh_token": "…", "refresh_expires_in": 604800}, "actions": []}
```

| Situation | HTTP status | `error_code` |
| --- | --- | --- |
| Missing or non-string fields | 400 | 1000 |
| Invalid credentials or `accept_user` rejection, answered identically without revealing password correctness | 401 | 1401 |
| Sign-in failure rate limit exceeded | 429 with `Retry-After` | 1429 |
| Token Redis unavailable | 503 | — |

**Revocation.** Framework password changes, deactivation, deletion, and active/staff/superuser changes call `revoke_user_logins(request, user_id)` (see [security boundaries](security.md#credentials-sessions-and-trusted-html)), ending all Sessions and invalidating earlier access/refresh tokens. Redis in Session's security store records a cutoff; access tokens with `iat` and refresh tokens with sign-in times at or before it are rejected, including the same second. JWT issuance has second precision, so even tokens issued after revocation within that second fail. The framework has no immediate reissue flow; custom flows must wait until the next second. Cutoffs remain for the longer token lifetime, after which older tokens would expire anyway. Single-client `revoke_access_token(claims)` revokes one presented access token by `jti` until its original expiry. CLI/background callers without requests use `end_user_logins(user_id)`. Services without `web.auth.jwt.secret` issue/consume no tokens but still write cutoffs, so Admin password/deactivation changes invalidate API-issued tokens too. Services sharing users must share both `web.auth.jwt` lifetimes, Redis, and `core.namespace`: cutoff retention uses local lifetimes. Changes in any service then apply everywhere. Different namespaces cannot see each other's revocations. Redis failure during validation returns 503, not acceptance as unrevoked.

## Service and internal-tool caller authentication

Endpoints for services, scripts, and internal machines ask which caller is connecting, rather than which user signed in. These authenticators identify **callers**,
not users: `request.ctx.user` remains anonymous and `request.ctx.auth.caller` is the configured name. Authorize through `authenticated_by`.

### API key

```yaml
web:
  auth:
    authenticators: [session, api_key]
    api_keys:
      monitor:
        secret: "a sufficiently long random string"
      legacy_bot:
        secret: "……"
        query_param: admin_secrets   # Also read this query parameter
        authorization: true          # Also accept Authorization: Bearer <key>
```

- Callers default to `X-API-Key` headers. Query parameters are read only for keys configuring `query_param`; they appear in access logs, browser history, and Referer,
  so reserve them for legacy callers unable to set headers. Keys accept `Authorization: Bearer <key>` only with `authorization: true`.
- Comparisons use constant time. Named keys must be nonempty and distinct; listing `api_key` without keys fails startup.
- Clients explicitly attach keys, so CSRF is skipped. A signed-in Session on the same request still requires it.
- With `jwt` and API key authentication enabled, a non-JWT Bearer value passes through `jwt` and is then checked by `api_key`, so they do not conflict.

### HTTP Basic

```yaml
web:
  auth:
    authenticators: [session, http_basic]
    http_basic:
      realm: "Internal"
      accounts:
        ops: "a sufficiently long password"
```

- Fixed accounts serve HTTP-Basic-capable tools/machines such as monitoring, curl, and legacy systems. Usernames become `request.ctx.auth.caller`.
- Passwords are stored verbatim (settings files are owner-readable/writable only). Usernames must contain no colon and passwords must be nonempty. Listing `http_basic` without accounts fails startup.
- Both username and password use constant-time comparison, taking the same time regardless of which part is wrong.
- Browsers remember and automatically send Basic credentials, so CSRF still applies. Machine clients posting through Basic need endpoint `csrf_exempt`
  or should switch to API keys.
- Basic-only endpoints without `session` return 401 with `WWW-Authenticate: Basic realm="…"`, opening a browser sign-in prompt.
  With `session` listed too, the normal sign-in page flow applies instead.

### IP allowlist

```yaml
web:
  auth:
    authenticators: [session, api_key, ip_allowlist]   # ip_allowlist must be last
    ip_allowlist:
      local: ["127.0.0.1/32", "::1/128"]
      office: ["10.0.0.0/8", "127.0.0.1"]   # Behind local nginx, include the proxy's address too
```

- Callers are recognized by source networks; entry names become `request.ctx.auth.caller`. Entries contain individual addresses or CIDRs. Host bits such as `10.0.0.1/8`,
  invalid addresses, and empty entries fail configuration rather than silently broadening access. Listing `ip_allowlist` without entries fails startup.
- Both addresses must belong to the **same entry**: TCP peer `request.ip` and proxy-resolved `request.client_ip`.
  Any client can send proxy headers, and Sanic does not verify `real_ip_header` senders (see [client addresses and proxies](#client-addresses-and-proxies)). Requiring peer membership
  prevents direct-port clients spoofing only headers. Behind a reverse proxy, include its address and permitted client networks together. The TCP peer is always the proxy there,
  so spoof resistance depends on it overwriting `real_ip_header` with the real address (or appending only to `X-Forwarded-For` when `proxies_count` is configured).
  It must not forward client headers unchanged or outside clients could claim allowlisted addresses. This deployment prerequisite cannot be verified by the framework.
- ip_allowlist must be last in `web.auth.authenticators` or startup fails. Earlier placement treats signed-in internal users as anonymous allowlisted callers,
  masking their sign-in state.
- Dual-stack listening (default `listen_host: "::"`) presents IPv4 peers as `::ffff:a.b.c.d`. Matching converts them to IPv4 first, so configure IPv4 entries.
  Requests without IPs, such as UNIX sockets or anonymized proxy identifiers, are not recognized.
- Browsers always originate from their networks, so CSRF applies as with HTTP Basic.

### authenticated_by

```python
from oldman.web.auth import authenticated_by

@router.post("/internal/metrics", name="internal_metrics")
@authenticated_by("api_key", callers={"monitor"})
async def internal_metrics(request: Request):
    ...
```

- `authenticated_by(*methods, callers=None, login_url=None, response_mode=None)`: require recognition by one listed authenticator.
- `callers` restricts caller names (keys), not users: signed-in users still pass when `session` or `jwt` is included.
- No recognition gives 401; recognition through another method or unlisted caller gives 403. With `session`, responses follow page modes like `login_required`
  (browser pages redirect to sign-in). Otherwise responses are JSON for programmatic callers; `http_basic` adds `WWW-Authenticate` on 401.

## Permission entry points

Import from `oldman.web.auth`; all read only `request.ctx.user`:

| Decorator | Check |
| --- | --- |
| `login_required(login_url=None, response_mode="auto")` | Signed-in user, regardless of authenticator |
| `staff_required(login_url=None, response_mode="auto")` | Authenticated staff |
| `superuser_required(login_url=None, response_mode="auto")` | Authenticated staff superuser |
| `api_login_required()` | Authenticated; JSON unauthenticated responses |
| `authenticated_by(*methods, callers=None)` | One listed authenticator; `callers` restricts caller names; see [caller authentication](#service-and-internal-tool-caller-authentication) |

Without explicit `login_url`, anonymous browsers use `web.account.login_url` (default `/login`). Only hosts with independent sign-in paths, such as prefixed Admin, need explicit values.

Place beneath route decorators, for example `@router.post(...)`, `@staff_required()`, `@csrf_protect()`, then the function. Protect data, save, delete, and Modal content endpoints, not only pages.

Anonymous browser HTML navigation redirects 302 to sign-in. JSON or `X-Requested-With: XMLHttpRequest` gets HTTP 401 with `data.login_url` for the shared HTTP Client. Signed-in denials get 403. These are not HTTP 200 business validation failures.

Business queries still enforce object scope. Do not trust arbitrary URL IDs because users are signed in. The ExampleProject tutorial shares projects among signed-in users without implying user/tenant isolation. For private data, restrict list and save/delete lookups together, not only button visibility.

`HTTPMethodView` from `oldman.web` subclasses the Sanic class of the same name and adds the sign-in protocol and permission hooks. When `require_authenticated` is true, anonymous requests follow the sign-in protocol, receiving 401 or a redirect. Next, asynchronous `check_permission(request, *, method_name, route_kwargs)` returns `(allowed, message)`; denial returns 403. By default, `require_authenticated` is off and `check_permission` allows access, preserving native Sanic behavior. Register the view with `as_view()`. The `check_permission` hook runs before parameter parsing or database sessions open, so put rules requiring no data query there: check `request_user(request).is_staff` for staff or `await has_perm(...)` for a permission. Table, Chart, and Select bases require only sign-in by default; endpoints add staff or permission requirements. See [permission layers in data components](permissions.md#permission-layers-in-data-components) for the other layers. Admin tables put admission and model permissions in `check_permission`. Calling an instance's `get()` directly bypasses the authentication and `check_permission` checks in `dispatch_request()`. Applications must therefore use `as_view()` or call `dispatch_request()` as Admin does.

## CSRF

A secret does not automatically protect every POST. Business Web services construct one `StatelessCSRFManager(app)` in `init()`; Admin installation already does this.

```python
from oldman.web.security.csrf import (
    StatelessCSRFManager, add_csrf_token, csrf_protect,
)
```

- Form GETs use `@add_csrf_token()`, storing tokens in `request.ctx.csrf_token`.
- Writing POSTs use `@csrf_protect()`; add `@add_csrf_token()` too when rerendering.
- Oldman Forms emit hidden token fields automatically. Handwritten native forms use `{% csrf_token %}`.
- Missing or expired tokens, mismatched binding, and cross-site origins return 403. Do not disable checks to fix sign-in pages left open for a long time. The exception is `oldman.web.exceptions.CSRFFailure`, a subclass of `Forbidden`, so existing handlers for `Forbidden` continue to work. The HTML error page explains that the page has expired or the request's same-site origin could not be confirmed and asks the user to refresh, instead of reporting a permission denial. The JSON response is unchanged.
- Expiry is `settings.web.security.csrf.ttl`, currently 3600 seconds. Keys come from common Web security settings.
- Binding: signed-in tokens use middleware-recorded SID, invalid in another same-user Session or after signing out/in. Anonymous visitors bind to a Cookie containing only a random ID (`web.security.csrf.cookie_name`, default `csrf_id`, like Django). Other visitors' tokens and signed-in tokens on anonymous requests do not pass.
- Signed-in token issuance also records that browser Cookie, which outlives Session as in Django. If a form stays open while Session expires, signs out elsewhere, or is forcibly ended, anonymous submission still matches the same browser Cookie and passes CSRF. View authentication then redirects to sign-in or returns 401 rather than a CSRF error. Signed-in requests compare SID only, so signing in again invalidates old tokens. Other browsers or Cookie-less requests fail. The tradeoff is that CSRF-protected anonymous endpoints still accept forms opened while signed in after that Session ends.
- Issue this Cookie only when generating a token (anonymous or signed-in) without a valid browser ID. Session response middleware writes it using Session Domain/Secure/SameSite, HttpOnly, Path `/`, and one-year expiry. Endpoints/static/SSE not generating tokens issue none. Servers store nothing, and anonymous visitors gain no persistent Session.
- Without Session middleware, nobody writes this Cookie. Anonymous tokens are unbound and rely only on Origin checks; these services have no ambient browser sign-in state to exploit.
- Signing in invalidates pre-sign-in forms in other tabs by switching to SID comparison; refresh them. `cache_response` skips token-generating pages because their tokens belong to one visitor/Session.
- CSRF checks only credentials that browsers send automatically. Authentication through a header token or key has false `ambient` and skips these checks because cross-site forms cannot forge such requests. Any signed-in session on the same request still triggers CSRF checks.

`csrf_exempt` matters only with `web.security.csrf.enforce`: global middleware checks every state-changing request and skips marked handlers. With enforcement off, protection is per-route (`@csrf_protect`); absent protection already means exemption and the decorator has no effect.

Do not add `csrf_exempt` to ordinary business forms. External webhooks need explicit alternative authentication and are not the tutorial default.

### Optional per-request timezone parsing

`oldman.web.middlewares.install_timezone(app)` registers middleware resolving timezone from `X-Timezone`, then
the `timezone` Cookie, and writes `request.ctx.timezone`. Missing both falls back to
`core.time_zone`. **Not registered by default**: most services do not use it and should not pay per-request header/timezone parsing costs.
Invalid timezone names fall back to configured defaults without exceptions.

## Error pages and content negotiation

Primary keys in URLs come from browsers, and missing records are normal. Read objects inside your transaction with `await get_object_or_404(session, Model, object_id)` from `oldman.web.shortcuts`. If the record does not exist, it raises `NotFound` for the error handling below, so each view need not repeat a None check and raise. Pass `message=` for a custom message.

WebApplication installs `ErrorPageHandler` with default `settings.web.fallback_error_format: auto`. HTML exception templates are selected in this order:

1. `errors/<status>.html`, usually supplied by the project.
2. `oldman/errors/<status>.html`, supplied for 403, 404, and 500.
3. `errors/default.html`。
4. `oldman/errors/default.html`。

Bundled error pages contain only inline CSS and load no frontend build output, so both pure API services and websites can use them. Branding and titles use `site_name()`. Back links on site-level pages (`oldman/errors/*`) go to the site root `/`; dashboard error pages (`oldman/dashboard/errors/*`) use `account_urls(request).home`, the destination after sign-in. Colors and font fallbacks follow shared design tokens and the system's light or dark preference. To include the dashboard shell, provide project templates according to the lookup order above. Template context contains only the necessary `request`, `status_code`, and `description`; production pages receive no exception stacks or sensitive details. `description` is populated only when the exception provides `page_description`, currently only `CSRFFailure` with translated recovery advice. Other exception messages do not appear on the page. The framework's 403 template displays `description` when present, otherwise a permission-denied message. Custom 403 templates need the same conditional to show that advice. Projects can add `templates/errors/401.html` if needed. Dashboard scaffolds supply `errors/403.html`, `404.html`, `500.html`, and `default.html`, each independently inheriting a framework dashboard error template. Changing one does not require copying the entire handler.

Project `errors/default.html` does not override matched framework 403/404/500 templates; supply dedicated files for those. Override `oldman/errors/...` paths for shared framework styling changes.

Exception handlers and shared permission-denial helpers use the same template flow. `await permission_denied_response(request, response_mode)` returns HTML 403 or standard JSON 403 according to the resolved mode; explicit modes are not reinterpreted through Accept. HTTPMethodView, staff/superuser decorators, and Admin already use it; callers must await asynchronous rendering.

A view's own `return text_response(..., status=403)` is not globally rewritten into an error page. API errors retain JSON or their negotiated format; 500 errors in debug mode retain Sanic debugging behavior. A missing template environment or a failing error template logs the exception and falls back to Sanic HTML. Custom templates are therefore not guaranteed under every condition.

## HTML trust boundaries

Jinja ordinary variables escape by default. Tables escape ordinary strings; `Markup` means business code has approved HTML. `replace_html` and Modal content also accept HTML: escape untrusted fields or sanitize permitted rich text server-side.

Form JSON `message`/field errors and Feedback Action `title/text` display as text. Use templates and `ReplaceHtmlAction` for complex HTML, not plain-text fields. Cookie flash, persistent notifications, and response Feedback have distinct contracts despite similar names.

<!-- source: zh/developers/web.md @ 6a3c1971 -->
