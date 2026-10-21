# Configuration reference

Oldman validates service YAML with the project's single Settings type. Global and App settings share one file but are published as separate strongly typed objects.

## Root Settings

The EPG demo's [config/schemas.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/config/schemas.py) defines its single root class. This excerpt contains the complete class, not a standalone file. `Field` comes from Pydantic, configuration types from `oldman.conf.schemas`, and default factories are above it in the same file:

```python
class Settings(DefaultSettings):
    """Project settings schema."""

    database: DatabaseConfig = Field(default_factory=default_database_config, description="Database settings")
    i18n: I18nConfig = Field(default_factory=I18nConfig, description="Internationalization settings")
    web: WebConfig = Field(default_factory=default_web_config, description="Web service settings")
    storages: StoragesConfig = Field(default_factory=default_storages_config, description="Named file storage settings")
```

Default factories handle project database paths, templates/static directories and Session, and default file storage; i18n uses `I18nConfig` directly. These two consecutive functions show how Web groups compose, rather than assembling settings throughout business code:

```python
def default_session_config() -> SessionConfig:
    """Return the Redis Session contract used by the Dashboard service."""
    return SessionConfig(
        enabled=True,
        expiry=86400,
        cookie_name="oldman_session_id",
    )


def default_web_config() -> WebConfig:
    """Assemble the Dashboard's browser-facing service settings."""
    return WebConfig(
        session=default_session_config(),
        template=default_template_config(),
        static=default_static_config(),
        frontend=FrontendConfig(),
    )
```

`BASE_DIR = Path(__file__).resolve().parents[1]` in that file generates project paths. The referenced `default_template_config()` and `default_static_config()` are also there; retain these dependencies when copying factories. Example YAML explicitly sets messages and SSE too; see [the demo's settings and switches](../users/settings-and-apps.md#web-switches). Do not infer final settings from this default factory alone.

The demo's [config/settings.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/config/settings.py) only adds the project type to an initialized object. Its imports and binding are:

```python
from typing import cast

from oldman import conf

from config.schemas import Settings

settings = cast(Settings, conf.settings)
```

Business code reads `from config.settings import settings`. `cast()` neither constructs an instance, loads a file, nor changes runtime values.

Generic framework code may import `settings` from `oldman.conf`, where its static type is `DefaultSettings`. Project-specific fields use the project's own import entry point.

Web services use this same instance without attaching another copy to `app.ctx.settings`. Admin assets, language menus, sign-in expiry, language preference Cookies, and CSRF read global settings. `app.ctx` stores installed runtime objects, not another configuration source.

Reading `conf.settings` before initialization raises `RuntimeError`. It is neither an always-available default object nor a lazy proxy. Normal CLI bootstrap precedes business imports; IDEs use [the public bootstrap entry point](applications.md#python-shell-and-ide).

Root values come from YAML and model defaults, without layering `.env`, environment variables, or secrets directories as business configuration sources. This does not restrict independent environment parameters for CLI language or runtime tools.

## Configuration file selection

In the EPG demo root, `./run.sh web start` reads `data/web_settings.yaml` for `services/web.py`. Other services similarly use `data/<name>_settings.yaml`; names may contain underscores. `core.data_dir` does not change this startup file name retroactively.

These examples demonstrate CLI path options, not another debug configuration bundled with the demo. `data/web_debug.yaml` is a user-chosen alternative: run `init` on it before `check/sync` or Shell. The CLI provides `--config PATH` only on these tooling entry points:

```sh
./run.sh web settings init --config data/web_debug.yaml
./run.sh web settings sync --config data/web_debug.yaml
./run.sh web settings check --config data/web_debug.yaml
./run.sh web shell --config data/web_debug.yaml
./run.sh web static collect --config data/web_debug.yaml
```

This is not a global option. `web start` does not reuse the last `settings --config` choice; do not write `oldman --config ... web start`. Python `bootstrap_service(..., config_file=...)` can select a file explicitly.

`settings init/sync/write` replace whole files, writing a sibling temporary file before renaming it. Failure leaves either the old or new file, never a partial file. For symlinked configuration (services sharing one file), writes follow the link to the real file and preserve the symlink. The replacement file is owned by the command's user.

Relative paths resolve against the working directory; project `run.sh` first changes to its root, so examples use `data/...`. Explicit paths are accepted without copying into `data` or registering them as service defaults. Keep production service settings in `data`: project-level `db` commands read only actual services' default YAML, not temporary alternatives.

Project-root discovery prefers a valid `PROJECT_ROOT`, otherwise searches upward from known locations such as the working directory for `pyproject.toml`, `setup.cfg`, `setup.py`, or `.git`. Ordinary projects run from their root or through `run.sh` without setting this environment variable.

## Two settings spaces in YAML

This excerpt from the demo's [web_settings.example.yaml](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/web_settings.example.yaml) retains the entire App list and its settings, without repeating other root settings:

```yaml
apps:
  - oldman.auth
  - oldman.apps.admin
  - oldman.web.messages.notifications
  - oldman.apps.roles
  - apps.accounts
  - apps.dashboard
  - apps.epg_admin
  - apps.examples
app_settings:
  auth:
    user_model: apps.accounts.models.User
  admin:
    require_superuser: false
  examples:
    http_base_url: https://httpbin.org
```

- `apps`, `database`, and `web` belong to root Settings.
- `app_settings.auth`, `app_settings.admin`, and `app_settings.examples` are validated by AuthSettings, AdminSettings, and the demo's ExamplesSettings respectively, then bound to their Apps.
- `apps.accounts` is the demo Python package (as in the `startproject` scaffold), with label `accounts`. `app_settings.auth` belongs to framework package `oldman.auth`. The former defines the concrete User; the latter selects it.
- Root Settings has no `app_settings` field or per-App proxy lookup methods.

Unknown root fields fail. Unknown fields in built-in nested groups neither fail nor take effect; `settings check` and service startup report them by path (for example `unknown settings key 'web.sesion'`), exposing typos. User-named aliases under `redis` are excluded from this check. Unknown App Settings fields fail as above. `check` validates names and values, not business relationships.

## App Settings

Settings models must extend `pydantic.BaseModel`. Prefer `ConfigDict(extra="forbid")` and typed, constrained `Field` definitions for configurable values. No dedicated `AppSettings` base class is required.

The demo's installed Admin App supplies this settings class. These fields come from framework [oldman/apps/admin/settings.py](https://github.com/alexliyu7352/oldman/blob/main/oldman/apps/admin/settings.py); do not create another same-name file in the demo:

```python
"""Strongly typed settings owned by the Admin application."""

from pydantic import BaseModel, ConfigDict, Field


class AdminSettings(BaseModel):
    """Configure access policy specific to the built-in Admin UI."""

    model_config = ConfigDict(extra="forbid")

    require_superuser: bool = Field(
        default=False,
        description="Require superuser access to Admin",
    )
    prefix: str = Field(
        default="/admin",
        description="URL path the Admin is mounted under; its own pages (login, sign-out, session) sit beneath it",
    )
```

The complete file also validates `prefix`: it trims trailing slashes and rejects root `/` or nonlocal paths containing a domain, query, `#` fragment, or leading `//` during configuration loading.

Registration comes from framework [oldman/apps/admin/apps.py](https://github.com/alexliyu7352/oldman/blob/main/oldman/apps/admin/apps.py). Imports, class, and instance are retained below:

```python
"""Installable Admin application metadata."""

from oldman.apps import AppConfig
from oldman.apps.admin.settings import AdminSettings
from oldman.i18n import gettext_lazy as _


class AdminAppConfig(AppConfig[AdminSettings]):
    """Describe the built-in Admin application and its settings owner."""

    label = "admin"
    display_name = _("Administration")
    icon = "ri-admin-line"
    settings_model = AdminSettings


app = AdminAppConfig()
```

`AppConfig[AdminSettings]` defines the static type of `app.settings`; `settings_model = AdminSettings` defines its runtime type. Custom Apps use the same interface with their own class and label, without changing root Settings.

The demo's sign-in service reads `admin_app.settings.require_superuser`; see [the user guide](../users/settings-and-apps.md#an-apps-own-settings) for consumers and initialization requirements. Its Examples App also binds a real ExamplesSettings through the same generic/settings_model mechanism. run_http_example reads http_base_url at runtime. This satisfies a configurable HTTP upstream requirement rather than adding an empty model for consistency. Apps without settings requirements may omit settings models.

Binding rules:

1. Load only Apps explicitly installed in `settings.apps`.
2. Validate `app_settings.<label>` through each App's `settings_model`.
3. Use defaults for omitted fields; missing required fields fail.
4. Reject settings for uninstalled Apps, Apps without a settings model, and unknown App fields.
5. Normal bootstrap binds instances after validation. `settings check/sync` do not publish runtime App Settings for business use.

Do not cache business values from `app.settings` at module level and assume the module remains importable before initialization. The demo reads `app.settings.http_base_url` inside `run_http_example()` in `apps/examples/http_example.py`, not at module level. Initialize through the service entry point before calling it.

## SettingsManager

Ordinary projects use CLI or `bootstrap_service()`. Configuration tools may import `SettingsManager` from `oldman.conf`:

```python
SettingsManager(
    settings_class,
    service_definition,
    config_file,
)
```

This describes the construction interface, not demo calling code. It requires an actual `ServiceDefinition`; a Settings class alone cannot replace startup logic. Do not manually construct managers to share or switch Registry with a running service.

| Method | Behavior |
| --- | --- |
| `read_config()` | Read current YAML mapping without writing |
| `load()` | Validate and bind App Settings, returning the root instance; unified bootstrap still publishes globally |
| `check_config()` | Validate and return root settings, without writing or publishing runtime App Settings |
| `init_config()` | Create only if missing, optionally initialized from same-name `.example.yaml` |
| `sync_config()` | Preserve existing values/comments and fill missing model fields |
| `write_config(data)` | Validate and explicitly write supplied data, generating Web keys if needed |
| `diagnostics` | Tuple of nonfatal suggestions from the latest successful validation |

Initial EPG setup uses adjacent `web_settings.example.yaml`, providing an explicit initial App list. Without a matching example, no App directory scan installs packages. Use `sync` for existing YAML rather than overwriting with `init`.

A manager does not support changing its App list or rebinding initialized Apps to different instances. Run configuration tooling in separate processes.

`init/sync/write` include field descriptions. New files use mode 0600; writing existing files does not tighten their permissions automatically. Check deployment permissions and do not commit real keys.

## Root configuration groups

Pydantic group types are defined in `oldman.conf.schemas`. `settings sync` generates a commented YAML version of all fields for a service.

| Node | Type | Main purpose |
| --- | --- | --- |
| `apps` | `tuple[str, ...]`, a YAML list | App package paths installed by this service |
| `core` | `CoreConfig` | Names, data directory, timezone |
| `logging` | `LoggingConfig` | Level, directory, console color policy |
| `process` | `ProcessConfig` | PID directory |
| `web` | `WebConfig` | Listening, sessions, SSE, templates, static assets, security |
| `i18n` | `I18nConfig` | Web translation, languages, default locale |
| `database` | `DatabaseConfig` | Async SQLAlchemy URL and query logging |
| `redis` | `RedisConfig` | Case-sensitive connection alias mapping |
| `nats` | `NATSConfig` | Named NATS URLs, authentication, TLS |
| `nats_bus` | `NATSBusConfig` | Core events/RPC switches, consumption, namespace, peer, codec, startup/shutdown waits |
| `taskiq` | `TaskiqConfig` | Distributed task switch, namespace, connection aliases, concurrency, scheduling/shutdown budgets |
| `cache` | `RedisCacheConfig` | Redis alias and serializer for caches; fixed key prefix `<core.namespace>:cache` |
| `http_client` | `HttpClientConfig` | Outbound pools and User-Agent defaults |
| `storages` | `StoragesConfig` | Named storage backends and options |
| `mail` | `MailConfig` | Outgoing backend, default sender, admin recipients, SMTP |
| `proxy` | `ProxyConfig` | Proxy connection/read timeouts and other settings |

Auth's `user_model` and password-reset `password_reset` settings (`expiry` 24 hours; `ip_limit`/`ip_window` 5 per 15 minutes; `email_limit`/`email_window` 3 emails per hour) come from `oldman.auth.apps.app.settings`. Admin's `require_superuser` and mount `prefix` (default `/admin`) come from `oldman.apps.admin.apps.app.settings`. They are stored under `app_settings.auth`/`app_settings.admin`, not root settings.

### Common non-Web defaults

| Field | Default |
| --- | --- |
| `core.app_name` | `oldman` |
| `core.site_name` | Falls back to `core.app_name`. Human-readable branding for error pages, dashboard sidebar, authentication pages, and password-reset emails. Templates read global `site_name()` |
| `core.namespace` | Falls back to `core.app_name`. First segment of all service Redis keys/channels (sessions, token revocation, caches, rate limits, SSE, locks, etc.). Related services sharing sessions/tokens/cache, such as a public site and dashboard, use the same value; independent services use different values. If omitted everywhere, sharing requires matching `app_name`. With different `app_name` values, a password change in one service does not end the other's sessions/tokens or invalidate its cache. Colons and whitespace are forbidden, including in fallback `core.app_name`; invalid values fail startup and ask for `core.namespace`. `startproject` defaults it to the project name in `config/schemas.py` (`CoreSettings`), so all project services, including later additions, share it while other projects on the same Redis remain isolated |
| `core.data_dir` | `data` under project root |
| `core.time_zone` | `Asia/Singapore` |
| `core.debug` | `False`. Shared debug switch: Web passes it to Sanic (debug mode and detailed error pages); unset `logging.level` defaults to DEBUG when debugging is enabled; unset `database.echo` follows it; streaming proxy errors log full tracebacks |
| `core.id_alphabet` | Unset. Per-deployment alphabet for public IDs (`oldman.utils.hash_ids` `encode_id` / `decode_id`). **Only Web services** generate it automatically during `init/sync/write`. Copy the same value to other project services encoding/decoding IDs, such as Workers; separate alphabets decode incorrectly in Web. Missing values make `encode_id` / `decode_id` fail with setup instructions. Existing alphabets do not rotate automatically; changing one invalidates all published IDs |
| `logging.level` | Unset: DEBUG with `core.debug`, otherwise INFO. Explicit values take precedence; level names such as `INFO` are accepted |
| `logging.dir` | `logs` under project root |
| `logging.color` | `auto`; alternatives `always`, `never` |
| `logging.rotate_when` | `D` (daily); also `S`/`M`/`H`/`W0`–`W6`/`midnight`. Set `null` to disable time rotation |
| `logging.rotate_interval` | `1`, number of `rotate_when` units between rotations |
| `logging.max_bytes` | `0` (disabled). Size rotation **requires `rotate_when` to be `null`**; both modes cannot be enabled together |
| `logging.backup_count` | `3`, number of retained log backups |
| `process.pid_dir` | `pids` under project root |
| `process.stop_timeout` | `60` seconds. Web/background `stop` deadline for the entire process group, followed by group SIGKILL; Taskiq uses `taskiq.stop_timeout` |
| `database.url` | `None`; configure before database use |
| `database.echo` | `None`, following `core.debug` |
| `database.enable_sql_logging` | `False` |
| `database.cache_pool_size` / `cache_pool_timeout` | `5` / `1.0` seconds; dedicated query pool for model-cache misses; see [model caching](cache.md#cache-connection-pool) |
| `i18n.use_i18n`、`use_i18n_path` | `False` |
| `i18n.default_language` | `en` |
| `i18n.cookie_name` / `cookie_max_age` | `preferred_language` / 365 days in seconds. Remembers visitor language outside path mode, written only at `i18n.preference_url`; see [which language a request uses](assets.md#which-language-a-request-uses) |
| `cache.client` / `serializer` | `CACHE` / `pickle`; prefix `<core.namespace>:cache` |
| `http_client.max_connections` | `300` |
| `mail.backend` | `oldman.mail.backends.console.ConsoleEmailBackend`, printing to stdout; use smtp in production |
| `mail.default_from_email` / `subject_prefix` | `webmaster@localhost` / `[Oldman] ` |
| `mail.smtp.host` / `port` / `timeout` | `localhost` / `25` / `10` seconds; `use_tls` and `use_ssl` are mutually exclusive |

Built-in Redis aliases `DEFAULT`, `CACHE`, and `SESSION` default to TCP `localhost:6379`, databases 3, 2, and 5. `redis_url` also accepts `rediss://` for TLS and `unix:///path/to/redis.sock?db=N` for an enabled Unix socket. Add aliases such as `SSE` with real `redis_url` values; do not assume they exist automatically. Check generated URLs, database numbers, and `decode_responses` before enabling dependent capabilities.

NATS DEFAULT defaults to nats://localhost:4222. Taskiq is disabled by default; enabling requires a namespace and existing NATS/Redis aliases. Non-Web services do not generate web automatically but still generate these root groups. See [distributed-task configuration](distributed-tasks.md#configuration-and-defaults) for all Taskiq defaults, security parameter conversion, and lifecycle.

Root nats_bus separately controls Core events/RPC: enabled/consume default false, nats_alias defaults DEFAULT, and enabled buses require namespace. It may use the same named address as Taskiq without sharing connections/protocols. See [NATS configuration](providers.md#configuration-and-defaults) for all defaults, peer_id, codec, and startup/shutdown budgets. init/sync/check neither connect to NATS nor read certificate files.

See [Mail](mail.md) for mail fields and built-in backends. Explicit `storages` must include `default`; specify actual backend class import paths and options. Do not create backend connections during model import.

## Web defaults and switches

| Field | Default |
| --- | --- |
| `web.listen_host` / `listen_port` | `::` / `17998` |
| `web.auto_reload` | `False` |
| `web.workers` / `access_log` | `1` / `False` |
| `web.response_timeout` / `request_timeout` / `keep_alive_timeout` | 120 seconds each |
| `web.real_ip_header` | `X-Real-IP`; Sanic directly uses its value as `request.client_ip` |
| `web.proxies_count` / `forwarded_secret` | Both unset; only when configured does Sanic parse `X-Forwarded-For` or RFC 7239 `Forwarded`; see [client addresses and proxies](web.md#client-addresses-and-proxies) |
| `web.fallback_error_format` | `auto`; also `html`, `json`, `text` |
| `web.websocket_max_size` | `1048576` bytes |
| `web.websocket_ping_interval` / `websocket_ping_timeout` | 5 / 20 seconds |
| `web.domain` | `http://localhost:17998` |
| `web.template.dir` | `templates` under project root |
| `web.static.dir` / `root` | `static` under project root |
| `web.static.url` | `/static/` |
| `web.media.storage` / `url` | `default` / `/media/` |
| `web.frontend.vite_dev_server_url` | `http://localhost:5173` |

Web runtime or concrete services consume these fields. `prepare_server()` still selects Sanic worker parameter combinations, and services must enable the template environment. Configuration is not an automatic installation inventory bypassing runtime wiring.

A real-IP header does not make every request trustworthy. Production reverse proxies must overwrite it and restrict routes bypassing the proxy.

### MCP endpoint (web.mcp)

Used only when `init()` calls `oldman.mcp.install_mcp(app)` and `web.mcp.enabled` is true. Other services also have default YAML entries without behavioral changes. See [MCP server](mcp.md).

| Field | Default |
| --- | --- |
| `web.mcp.enabled` | `False`: `install_mcp` logs INFO and does nothing: no App `mcp` loading, checks below, or routes. Code installs the capability; deployments can disable it through settings without code changes |
| `web.mcp.path` | `/mcp` |
| `web.mcp.allow_anonymous` | `False`: requests without credentials get 401. When enabled, anonymous callers can invoke only tools without `permission=`. Automatically supplied browser credentials (session, HTTP Basic, IP allowlist) always get 403 |
| `web.mcp.callers` | Empty: no API keys accepted. Names must exist in `web.auth.api_keys`; `web.auth.authenticators` must include `api_key` |
| `web.mcp.allowed_origins` | Empty: requests with `Origin` get 403 (the specification requires Origin validation against DNS rebinding). CLI and desktop clients omit this header |
| `web.mcp.max_request_body_size` | 4 MiB; larger requests get 413 |
| `web.mcp.name` / `instructions` | Empty; name falls back to `core.site_name`, then `core.app_name`. Version comes from `[project].version` in project `pyproject.toml` |
| `web.mcp.rate_limit.enabled` / `limit` / `period` | `True` / 60 / 60 seconds: each caller (user, API key, anonymous address) may invoke this many tools per window. Excess calls return a tool error with retry seconds |
| `web.mcp.rate_limit.redis_alias` | Unset: uses `web.session.redis_alias`, like sign-in rate limits |

When enabled, `install_mcp` fails startup if `web.auth.authenticators` omits `jwt`, `callers` is empty, and `allow_anonymous` is false, leaving no possible clients.

With `core.debug` true, Web Sanic calls `set_debug(True)` on the event loop. In this mode uvloop may raise `AttributeError` or segfault while collecting unclosed async generators ([uvloop#699](https://github.com/MagicStack/uvloop/issues/699), [uvloop#715](https://github.com/MagicStack/uvloop/issues/715); unfixed in 0.22.1 and 0.23.0 as of 2026-10-01). Both conditions are required: debugging enabled and an async generator left unclosed for garbage collection, for example by using `break` to leave `async for`. Changing Python versions does not avoid it. The upstream #715 reproduction fails in debug mode on Python 3.12 patch versions and 3.13.11, 3.13.15, and 3.14.2 (segfault or an ignored `AttributeError`). That script succeeds on 3.14.7, but framework tests crash there. All work with debugging disabled. Framework tests do not trigger it on 3.13.11 and 3.14.2, so CI pins those versions. Default production with debugging disabled is unaffected. Collection errors or segfaults during debugging indicate this issue. Explicitly close your generators with `contextlib.aclosing` instead of leaving garbage collection to close them.

### Web security settings

`web.security.secret_key` defaults empty and is generated/persisted during Web `init/sync/write`. `fingerprint.aes_secret_key` is likewise generated/persisted as a Base64-encoded 32-byte key. Existing nonempty keys do not rotate automatically.

If `settings check` or service loading finds required keys empty, it requests configuration sync first. Do not generate temporary secrets per worker; signing and validation would not work consistently.

Other security fields:

- `web.security.csrf.ttl`: 3600 seconds by default; `check_referer` true, `check_url` false.
- `web.security.csrf.cookie_name`: `csrf_id`, storing the random anonymous visitor ID binding CSRF tokens (see [the Web reference](web.md#csrf)). Do not use `csrftoken`; the frontend reads a Cookie with that name as the token if no hidden field exists.
- `web.security.csrf.enforce`: **false** by default. Enabling registers global middleware checking CSRF on every state-changing request (other than GET/HEAD/OPTIONS/TRACE), skipping handlers marked `@csrf_exempt`.
  It defaults off because enabling affects **currently unprotected routes**, such as webhooks/callbacks whose callers are not identified by the authentication pipeline.
  Mark these routes `@csrf_exempt` before enabling, or they start returning 403. Bearer access-token authentication is automatically exempt. With enforcement disabled, per-route `@csrf_protect` still applies.
- `check_referer` now checks same-origin using **Origin first, then Referer fallback**. Missing both headers is rejected.
  Referer alone is insufficient: `referrer-policy: no-referrer` removes it entirely. Browsers still send Origin, but with value `null` under `no-referrer`, even for local forms, so the framework rejects them as cross-site. Do not use `no-referrer` on pages submitting forms; use `same-origin` to avoid disclosing addresses to other sites.
- `web.security.fingerprint`: browser fingerprint time differences, frequency limits, and anomaly policies.

Security token and Session expiry are separate settings. Do not substitute one for the other.

### Session, messages, and SSE

| Setting | Default and meaning |
| --- | --- |
| `web.session.enabled` | false; installs session middleware only when enabled |
| `web.session.redis_alias` | `SESSION` |
| `web.session.expiry` | 43200 seconds (12 hours); normal sign-in session lifetime, matching server Redis TTL and Cookie expiry, without activity renewal |
| `web.session.remember_expiry` | 2592000 seconds (30 days); session lifetime with “Remember me” checked |
| `web.session.cookie_name` | `session_id` |
| `web.session.cookie_httponly` / `cookie_secure` / `cookie_samesite` | true / false / `Lax`; adjust Secure for HTTPS |
| `web.auth.authenticators` | Unset: `[session]` with Session enabled, otherwise empty. Try authenticators in order; the first recognizing credentials decides. Built-ins: `session`, `jwt`, `api_key`, `http_basic`, `ip_allowlist` (last only); project classes use import paths. See [request authentication](web.md#request-authentication-requestctxuser) |
| `web.auth.jwt.secret` | Unset. Access-token signing key, separate from `web.security.secret_key`, at least 32 characters. Services sharing tokens share it. Listing `jwt` in `web.auth.authenticators` without it fails startup; settings sync does not generate it |
| `web.auth.jwt.access_token_ttl` | 900 seconds. Access-token lifetime; validation rejects tokens signed for longer |
| `web.auth.jwt.refresh_token_ttl` | 604800 seconds (7 days). Refresh-token lifetime restarts on each refresh: clients stay signed in while refreshing within this period |
| `web.auth.jwt.issuer` / `audience` | Unset. If configured, written as `iss` / `aud` and required to match validation. Tokens with `aud` are rejected if no audience is configured |
| `web.auth.api_keys` | Empty. Named keys accepted by `api_key`; names become `request.ctx.auth.caller`. Each requires `secret`; `query_param` is unset (when set, also reads that query parameter); `authorization` false (true also accepts `Authorization: Bearer <key>`). Names must not share a key. Listing `api_key` without keys fails startup |
| `web.auth.http_basic.realm` / `accounts` | `oldman` / empty. `http_basic` realm shown in browser prompts (no quotes, backslashes, or control characters), and fixed accounts (username → plaintext password; usernames have no colon). Listing `http_basic` without accounts fails startup |
| `web.auth.ip_allowlist` | Empty. Named address/CIDR lists accepted by `ip_allowlist`; names become `request.ctx.auth.caller`. TCP peer and proxy-resolved client addresses must match the same entry, so proxied deployments include the proxy address. Networks must have no host bits; entries must not be empty. Listing `ip_allowlist` without entries fails startup; see [the IP allowlist](web.md#ip-allowlist) |
| `web.auth.login_backends` | `[users]`. Credential backends for sign-in/token issuance, tried in order with first recognition decisive. Built-in `users` queries the user table; project classes use import paths |
| `web.messages.enabled` | false; Cookie flash messages |
| `web.sse.enabled` | false; Redis-backed distributed SSE |
| `web.sse.redis_alias` | `SSE`; explicitly configure this alias or select an existing appropriate alias |
| `web.sse.heartbeat_interval` | 15 seconds |
| `web.sse.session_check_interval` | 30 seconds |
| `web.sse.queue_size` | 100 |
| `web.sse.max_message_size` | 65536 bytes |

Web validation checks that aliases referenced by enabled Session/distributed SSE exist, without connecting to Redis during `settings check`. Cookie messages need no Redis.

If a Web service installs Admin without raw `web.messages.enabled`, `init/sync` fills it with true. Explicit false is preserved. Reading omitted YAML at runtime alone does not write this default or enable other modules.

SimpleApplication does not generate/fill `web` automatically or perform Web-specific key/Redis alias relationship checks. Explicit Web settings are still parsed by field type without installing browser middleware. Other root groups and installed App settings generate normally.

### Account page addresses

Configure site account page paths here once. Values must start with `/`, without domain, query, `#` fragment, or leading `//`. Other forms fail configuration loading.

| Setting | Default and meaning |
| --- | --- |
| `web.account.login_url` | `/login`; sign-in page and submission. Signed-out requests requiring authentication are sent here |
| `web.account.logout_url` | `/logout`; sign out and return to sign-in |
| `web.account.login_redirect_url` | `/`; destination after sign-in without a safe `next`, also used when signed-in users open sign-in pages |
| `web.account.password_reset_url` | Unset; when set, sign-in shows “Forgot password?” linking here. Mount the reset flow at this address |
| `web.account.profile_url` | `/user-session`; current-user page, with self-service password changes beneath it |
| `web.account.user_events_url` | `/user-events`; current-user server events (session termination, notifications), installed only with `web.sse.enabled` |
| `web.account.users_url` | `/users`; user list, with individual account pages beneath it |
| `web.account.roles_url` | `/roles`; role list, with individual role pages beneath it |
| `i18n.preference_url` | `/preferences/language`; browser POSTs language choices here, signed in or not |

Consumers: decorators such as `login_required`, table/chart/select data endpoints, SSE, and notification endpoints read `web.account.login_url` at request time unless explicitly passed `login_url`. Template global `account_urls(request)` supplies these paths to project templates. `i18n compile-frontend` writes `i18n.preference_url` into generated `generated.ts` (`languagePreferencePath`). Sign-in/profile/user-management/role-management flows receive these values from the service instead of reading settings themselves; see [ready-made account flows](web.md#ready-made-account-flows). Built-in Admin pages live under `app_settings.admin.prefix` without reading this group.

## Boundaries when changing settings

After changing settings models or installing Apps, run `settings sync/check` for the target service, inspect YAML, then restart.

Do not mutate global Settings in requests to switch tenants, languages, or services; request-level state has its own objects. Do not expose arbitrary production resets. Different settings require independent processes.

Validation establishes conformance to current models and explicit relationships only. Database connectivity, migration state, Redis availability, and built assets need operation-specific verification. `Settings OK` is not complete deployment acceptance.

## Mutable runtime configuration

The YAML Settings above validate and publish once at startup and remain unchanged. Values needing **changes without restarting**, such as maintenance switches, announcements, per-channel parameters, and device lists, belong in `oldman.conf.containers`. They bypass Settings validation and do not appear in `settings check/sync`.

| | `YamlStore` | `RedisStore` | `RedisSet` |
| --- | --- | --- | --- |
| Storage | One YAML file | One Redis key | One Redis set |
| Visibility across processes | Cached per process; periodically checks file | Shared; reads Redis every time | Shared; every operation accesses Redis |
| Value shape | Schema-defined structure | Schema-defined structure | `str` or `int` members |
| Suitable for | Manually editable structured settings tolerating seconds of delay | Switches/small values needing immediate cross-process visibility | Membership checks on request paths; random proxy-pool selection |

These excerpts from the EPG demo's [apps/examples/dynamic_config.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/dynamic_config.py) retain only relevant imports. Its two “Dynamic configuration” sidebar pages use them; see [Demo page and source index](../users/demo-examples.md#dynamic-configuration) for operations.

### Schema, reading, and saving

`YamlStore` and `RedisStore` values use a `MsgspecModel` subclass defining fields, types, and defaults. Missing files/keys use defaults, so **every field needs a default**, otherwise construction raises `TypeError`. Use `default_factory` for Settings-dependent defaults or nonempty dict/list defaults (`_sample_channels` above), generated only when defaults are requested.

```python
import msgspec

from oldman.serializers import MsgspecModel


class ChannelOverride(MsgspecModel):
    display_name: str = ""
    epg_offset_minutes: int = 0
    enabled: bool = True


def _sample_channels() -> dict[str, ChannelOverride]:
    return {
        "cctv1": ChannelOverride(display_name="CCTV-1"),
        "tvb-jade": ChannelOverride(display_name="TVB Jade", epg_offset_minutes=-60),
    }


class ChannelOverrides(MsgspecModel):
    announcement: str = ""
    channels: dict[str, ChannelOverride] = msgspec.field(default_factory=_sample_channels)
```

| Method | Behavior |
| --- | --- |
| `get()` | Current value |
| `save(value)` | Validate against schema and write the whole value |
| `update(**changes)` | Read current value, change top-level fields, pass to `save()`, and return the saved value |

```python
async def set_channel_offset(channel_id: str, minutes: int) -> None:
    """The usual way to change one entry: get(), assign, save()."""
    store = channel_overrides()
    value = await store.get()
    override = value.channels.get(channel_id) or ChannelOverride(display_name=channel_id)
    override.epg_offset_minutes = minutes
    value.channels[channel_id] = override
    await store.save(value)


async def set_announcement(text: str) -> None:
    """A top-level field in one line: update() reads, changes and saves."""
    await channel_overrides().update(announcement=text)
```

- msgspec Struct construction/assignment does not validate types; pyright/Pyrefly detect wrong assignments statically. Runtime reads decode through schema; `save` and `update` validate before writing. Wrong types raise `msgspec.ValidationError`; unknown `update` fields raise `TypeError`; neither writes anything. `update` returns the validated, actually saved value (date strings become `datetime`), matching later `get()` results.
- Calls to `update` on one instance are serialized: each reads after the preceding save, so concurrent changes to different fields do not overwrite each other. Use one configuration instance per process, at module level or returned by `@cache` as in the Redis alias example below. With multiple processes (`web.workers`), `YamlStore.update` checks for external file changes regardless of `check_interval` and starts from current file contents. Changes saved seconds earlier are not lost; genuinely simultaneous writes still use last-writer-wins. For frequent multi-party writes, assign writing to one process.
- Reads/writes operate on whole values. `update` changes only top-level fields; modify a `channels` entry with `get()`, assignment, and `save()`.

### YamlStore

```python
from functools import cache
from pathlib import Path

import oldman.conf as conf
from oldman.conf.containers import YamlStore

CHECK_INTERVAL = 2.0
FILE_NAME = "example_channel_overrides.yaml"


class ChannelOverridesStore(YamlStore[ChannelOverrides]):
    """Counts the outside edits it picked up: resetting what was derived from the old value is what the hook is for."""

    def __init__(self, path: Path) -> None:
        super().__init__(ChannelOverrides, path, check_interval=CHECK_INTERVAL)
        self.outside_changes = 0

    def on_file_changed(self, old: ChannelOverrides, new: ChannelOverrides) -> None:
        self.outside_changes += 1


@cache
def channel_overrides() -> ChannelOverridesStore:
    return ChannelOverridesStore(conf.settings.core.data_dir / FILE_NAME)
```

The demo hook only counts external changes for display. Real applications can reset state derived from old values here, such as rotation indexes computed from settings. Without a hook, use `YamlStore(ChannelOverrides, path)` directly instead of subclassing.

- Decoded values are cached in process. No disk access occurs within `check_interval`; afterward stat runs, and parsing occurs only when the file changed.
- `get()` returns a **shared object**. Save after changing it. For temporary changes, first copy with `msgspec.structs.replace()`; otherwise a later call to `save` persists the temporary edits.
- A missing file is created with schema defaults.
- `on_file_changed(old, new)` runs only after reading **external changes**, including deletion. Own `save`/`update` do not invoke it. Hook exceptions log ERROR without disrupting reads.
- Subclass caches derived from settings, such as environment-adjusted objects, need invalidation in two places: external changes in `on_file_changed`, and own saves after the parent call in an overridden `save`. `update` writes through `save`, so needs no extra handling. Direct `get()` consumers need no cache; the value is already in memory.
- Invalid external YAML, types, or non-UTF-8 encoding are rejected, retaining the last valid value and logging one ERROR. Once repaired, loading and hooks resume normally. If the file is invalid on first load, `get()` raises parsing/validation errors.
- Failed saves (validation or writing) reload memory from the file without calling hooks.
- Writes use a same-directory temporary file and whole-file replacement, so readers never see partial output. Existing permissions remain unchanged. YAML **comments are not preserved** on save.
- Types follow YAML parsing: unquoted `2026-09-27` is a date and fails in a `str` field. Quote it when a string is required.
- Change detection checks inode, nanosecond modification time, and size. In-place copies preserving time and size (`cp -p`) are not detected.

### RedisStore

```python
from functools import cache

from oldman.conf.containers import RedisStore
from oldman.providers.redis import redis_client

REDIS_ALIAS = "CACHE"


class SiteFlags(MsgspecModel):
    maintenance: bool = False
    banner: str = ""
    max_streams_per_user: int = 3


SITE_FLAGS_NAME = "example_site_flags"


@cache
def site_flags() -> RedisStore[SiteFlags]:
    return RedisStore(SiteFlags, SITE_FLAGS_NAME, client=redis_client.using(REDIS_ALIAS))


async def write_banner_from_another_instance(banner: str) -> None:
    """Another process holds its own store; a second instance stands in for it. Nothing is cached locally, so the next read sees it."""
    other = RedisStore(SiteFlags, SITE_FLAGS_NAME, client=redis_client.using(REDIS_ALIAS))
    await other.update(banner=banner)
```

- Without `client`, first read/write retrieves global `redis_client` (DEFAULT), permitting module-level `RedisStore(SiteFlags, "site_flags")`. `redis_client.using(alias)` reads Redis settings and validates the alias immediately, so call it after service bootstrap. The demo has no DEFAULT alias; its `@cache` function retrieves CACHE on first use. One instance per process also serializes `update`.
- Keys are `<core.namespace>:store:<name>`; values are the whole schema as msgpack. Names must be nonempty strings or raise `ValueError`.
- No local cache: every `get()` reads Redis and sees another process's writes on the next read. `write_banner_from_another_instance` demonstrates this with a second instance. Each returned object is freshly decoded; call `save` directly after edits.
- Missing keys use defaults without writing. Stored values incompatible with schema, such as changed field types, raise `msgspec.ValidationError` rather than falling back. Removed fields are ignored; added fields use defaults.
- There is no expiry. Store an expiry field such as `banner_until: datetime | None` and let readers check it for time-limited values.
- Redis failures propagate client exceptions to callers. Redis Provider owns connections; containers neither open nor close them. The default client requires completed bootstrap and configured Redis aliases.

### RedisSet

```python
from oldman.conf.containers import RedisSet

DEVICES_NAME = "example_allowed_devices"


@cache
def allowed_devices() -> RedisSet[str]:
    return RedisSet(str, DEVICES_NAME, client=redis_client.using(REDIS_ALIAS))
```

| Method | Behavior |
| --- | --- |
| `add(member)` | Add; return `True` if previously absent |
| `remove(member)` | Remove; return `True` if previously present |
| `contains(member)` | Check membership |
| `members()` | Read all members of the entire set |
| `random()` | Random member, or `None` for an empty set |

- Demo [views/config.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/config.py) uses `add`, `remove`, `contains`, and `random` on this set.
- Operations map directly to Redis set commands (`SADD`, `SISMEMBER`, `SRANDMEMBER`, etc.) without reading the full set. Use `contains` for membership instead of checking `members()` output.
- Members are exactly `str` or `int`: an `int` set rejects `True` and `"7"` with `TypeError`.
- Keys use `<core.namespace>:store:<name>`, shared with `RedisStore`. Do not reuse names or Redis raises `WRONGTYPE`.
- Construction, connections, and exceptions follow `RedisStore`. Lists and queues are not provided.

### Deprecated AsyncConfigDict and RedisSettings

Both remain usable but emit `DeprecationWarning` on construction. New code should use the containers above.

| Old form | New form |
| --- | --- |
| `AsyncConfigDict` subclass, `get_empty_data()` | `YamlStore[Schema]`, with defaults on schema fields |
| dict returned by `get_data()`, plus subclass caches decoding dicts to objects | `get()` returns decoded objects directly; remove those caches |
| `on_file_changed(old_data, new_data)` | `on_file_changed(old, new)`, still only after external changes |
| `save_data(data)` | `save(value)`、`update(**changes)` |
| `get_data_sync()` | No equivalent; use `get()` in async code |
| `RedisSettings` `get_value`, `set_value` | `RedisStore` fields, `get()`, `update()` |
| `RedisSettings` set methods | `RedisSet` |
| `RedisSettings` list methods, `set_value(..., ttl=)` | Not provided |

<!-- source: zh/developers/configuration.md @ 31aa114e -->
