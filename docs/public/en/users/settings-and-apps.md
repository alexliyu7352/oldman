# Settings, Apps, and services

Their responsibilities are simple: **the service decides what starts, the App provides capabilities, and the configuration file determines which capabilities and values the service uses.**

The EPG demo illustrates these roles: [services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py) supplies the Web service, [apps/examples/apps.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/apps.py) registers feature examples, and [data/web_settings.example.yaml](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/web_settings.example.yaml) contains public initial settings for the service. Run all commands below in the demo root; see [Run EPG Dashboard Demo](getting-started.md) for installation prerequisites.

## Services and configuration files

The current demo has these actual entry points:

```text
services/web.py → ./run.sh web start → data/web_settings.yaml
services/task_worker.py → ./run.sh task_worker start → data/task_worker_settings.yaml
services/task_scheduler.py → ./run.sh task_scheduler start → data/task_scheduler_settings.yaml
services/nats_a.py → ./run.sh nats_a start → data/nats_a_settings.yaml
services/nats_b.py → ./run.sh nats_b start → data/nats_b_settings.yaml
```

`WebService` is the Python class name; `web` is the command name derived from the file name. Changing `SERVICE_NAME` changes only the readable name, not the command or configuration file name. You do not need to specify `SERVICE_ID`.

Service file names support lowercase letters, digits, and underscores, and must start with a letter. Files sit directly under `services/`; nested directories are not searched. Each file defines one concrete class directly extending `WebApplication`, `SimpleApplication`, `TaskiqWorkerApplication`, or `TaskiqSchedulerApplication`.

You can use `startservice` to add services in the future. For specific interfaces, see [CLI reference](../developers/cli.md#project-level-commands). This command only creates the entry file and does not automatically create the configuration. For the shared namespace, connections and different App lists of the three Web/Taskiq services, see [Distributed background tasks](distributed-tasks.md); for the two Simple receiving services, see [Let running services communicate with each other](service-communication.md). These five services still use the same root Settings type, and their initial configuration does not mean starting all services.

Different services run in different processes, and each has its own current Settings instance. A process cannot first initialize a service configuration and then switch to another service to continue running.

## Create, check and complete configurations

| Command | Purpose | Writes files? |
| --- | --- | --- |
| `./run.sh web settings init` | Create missing configuration; fail if it already exists | Yes |
| `./run.sh web settings sync` | Keep existing values and comments, fill in missing fields and necessary keys | Yes |
| `./run.sh web settings check` | Verify the current configuration and output diagnostics | No |
| `./run.sh web start` | Read settings and start the service | Does not automatically rewrite YAML |

The demo provides `data/web_settings.example.yaml`. If local `data/web_settings.yaml` does not exist, run `./run.sh web settings init`. The framework reads the example, fills in default fields, and generates local keys; no prior YAML copy is needed. If you already copied or initialized the file following the demo README, use `sync` without overwriting local configuration. Ordinary projects without a matching example file have an empty App list by default.

This suits public projects: commit an example without real passwords or keys, and users obtain local configuration on their first `settings init`. The framework does not scan every business directory and assume this service should install them all.

`sync` will not overwrite the values you have filled in with new default values. For example, if `messages.enabled: false` is written, it will not change to true because you install Admin; after moving the project, it will not automatically correct the persisted absolute path. `core`, `logging`, `process`, static directories, and Storage paths should be checked and edited.

Runtime configuration uses YAML. Ordinary business settings are not overridden by `.env` or same-name environment variables. CLI language and project-directory discovery have their own tooling environment parameters; do not infer that business Settings support environment injection.

## Install Apps

Each service's YAML has its own list. Below is the complete App manifest and App settings section of the Demo example YAML, not the entire configuration file:

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

`oldman.auth` has label `auth` and provides authentication foundations and User model selection settings. The demo's `apps.accounts` has label `accounts` and provides the concrete `User` model (as in the scaffold generated by `startproject`, account pages such as sign-in use framework flows installed by its routes.py). These are separate Apps; `app_settings.auth.user_model` points to the class defined by the latter. Do not confuse Python package paths, labels, and model class names.

`oldman.apps.admin` provides built-in Admin settings, such as `require_superuser` below. User management commands such as `createsuperuser` and `changepassword` come from `oldman.auth`. Adding it to the list does not mount `/admin`; the EPG demo uses its own dashboard. See the [Run and understand the Admin Demo](admin.md) for the standalone Admin site.

An App must be importable in the current Python environment and have a `<package-path>.apps` module exporting an `AppConfig` object named `app`.

For third-party Apps, first install the Python package, then add the actual import package path documented by that App. Distribution names and import paths can differ; do not infer the path from the pip name.

The actual [apps/examples/apps.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/apps.py) complete content is as follows:

```python
"""Dashboard examples application metadata."""

from oldman.apps import AppConfig
from oldman.i18n import gettext_lazy as _

from .settings import ExamplesSettings


class ExamplesAppConfig(AppConfig[ExamplesSettings]):
    """Own the Dashboard's reusable example data and views."""

    label = "examples"
    display_name = _("Dashboard Examples")
    icon = "ri-flask-line"
    settings_model = ExamplesSettings


app = ExamplesAppConfig()

__all__ = ["ExamplesAppConfig", "app"]
```

`label` is a stable identifier unique within the current service, used in App settings, model ownership, and migration branches. `display_name` is the human-readable name; `icon` is a single supported icon class. Display names can be translated; stable labels are not display text.

Default module names are `models`, `views`, `commands`, `tasks`, `events`, and `migrations`. Omit modules for capabilities you do not need; there is no need to set default module names to `None` or create empty proxy implementations. Only Worker/Scheduler automatically load tasks; Web publishers import them explicitly as needed. Only ordinary Web/Simple services with Core consumption enabled load events; commands and Shell do not start subscriptions automatically.

For details on directory and loading constraints, see [Applications and lifecycle](../developers/applications.md#appconfig).

## An App's own settings

Reusable Apps define their settings in their own Pydantic classes. ExamplesSettings comes from the App's [settings.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/settings.py) and declares the HTTP example's http_base_url, defaulting to <https://httpbin.org>. `AppConfig[ExamplesSettings]` provides static typing and `settings_model = ExamplesSettings` defines the runtime settings type. `app_settings.examples.http_base_url` in service YAML binds to app.settings. This example rejects non-HTTP(S) URLs, credentials, queries, and fragments. Only trusted deployment settings may provide the address.

The actual consumer is run_http_example in [http_example.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/http_example.py). It imports app from that App and reads app.settings.http_base_url when the function runs, rather than during metadata import. See the [Cache examples and external HTTP](cache-and-http.md#running-the-backend-http-example) for configuration and operations. Only Apps needing settings declare a model; other Apps do not need empty settings classes.

The demo also installs the built-in Auth and Admin, whose strongly typed settings are read by the framework itself. Admin's sign-in policy illustrates this path below.

The framework declares Admin settings in [AdminSettings](https://github.com/alexliyu7352/oldman/blob/main/oldman/apps/admin/settings.py) and registers them in [AdminAppConfig](https://github.com/alexliyu7352/oldman/blob/main/oldman/apps/admin/apps.py). Both belong to the installed framework package; do not copy them into the demo:

- `AdminSettings.require_superuser` is a Boolean field, defaulting to false.
- `AdminAppConfig[AdminSettings]` declares a static type, and `settings_model = AdminSettings` specifies a configuration class created at runtime.
- The YAML's `app_settings.admin.require_superuser` is bound to the App's `app.settings.require_superuser`.
- Business code reads them through `from oldman.apps.admin.apps import app as admin_app`; the IDE can infer the settings type.

The actual consumer is the site of the built-in Admin: `AdminSite.register_routes()` ([oldman/apps/admin/site.py](https://github.com/alexliyu7352/oldman/blob/main/oldman/apps/admin/site.py)) reads it when installing the route, and uses the settings of the installed App when there is no explicit configuration passed in:

```python
if admin_settings is None:
    from oldman.apps.admin.apps import app as admin_app

    admin_settings = admin_app.settings
prefix = admin_settings.prefix
self.prefix = prefix
login_path = admin_login_path(prefix)
self.require_superuser = admin_settings.require_superuser
```

This controls only the built-in Admin: false admits active staff users; true additionally requires superuser status. Inactive users, non-staff users, and incorrect passwords are always rejected. It does not disable all permission checks or affect the demo's dashboard. Dashboard sign-in requires an active account; pages requiring staff explicitly declare `staff_required`.

Two services installing the same configurable App may use different values in their YAML files. Shared business code keeps one import entry point without checking which service it is running in. Read settings only after initialization and App installation. The normal CLI handles initialization; for IDE use see [Applications and lifecycle](../developers/applications.md#python-shell-and-ide).

Uninstalled Apps generate no settings; including their `app_settings` in YAML is an error. Installed Apps with a settings model use its defaults for omitted values. A missing required field without a default fails validation.

Do not use `settings.admin`, `settings.app_settings`, or `settings.for_app(...)`. App settings and root Settings are separate strongly typed object spaces stored in the same YAML. See [Configuration reference](../developers/configuration.md#app-settings) for defining App settings models.

## Shared project configuration

The project has one root settings type. The demo's [config/schemas.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/config/schemas.py) extends `DefaultSettings` with project defaults for database, Web, i18n, and Storage, rather than defining separate `ApiSettings` or `WebSettings` per service. See [Configuration reference](../developers/configuration.md#root-settings) for concrete types and default factories.

The business import entry point is [config/settings.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/config/settings.py), with these complete contents:

```python
"""Runtime settings instance for the Oldman application."""

from typing import cast

from oldman import conf

from config.schemas import Settings

settings = cast(Settings, conf.settings)
```

`cast()` only tells the static analyzer that this is the project's Settings. It neither reads YAML nor creates another configuration. Business code uses `from config.settings import settings`; do not copy it to `app.ctx.settings`.

Add only genuinely shared project settings to the root class. Settings specific to a reusable App belong in its own model. Services share the type but read their own YAML values.

After changing the model, run `settings sync` for the relevant services, check configuration, then restart them. Editing YAML on disk does not hot-swap running Settings.

## Web switches

Session, SSE, and Cookie messages are enabled separately. The framework disables them by default; the demo's example YAML explicitly enables all three. Do not treat framework defaults as the demo's current settings.

The demo configures:

| Setting | Demo value | Purpose |
| --- | --- | --- |
| `web.session.enabled` / `redis_alias` | true / `SESSION` | Browser sessions |
| `web.session.expiry` / `cookie_name` | 86400 / `oldman_session_id` | One-day expiry and Cookie name |
| `web.messages.enabled` | true | One-time Cookie flash messages |
| `web.sse.enabled` / `redis_alias` | true / `SSE` | Distributed SSE |
| `redis.SESSION.redis_url` | `redis://127.0.0.1:6379/5` | Demo session data |
| `redis.SSE.redis_url` | `redis://127.0.0.1:6379/6` | Demo SSE connection |

Use your local YAML as the authority; do not overwrite existing Redis URLs to try a tutorial. SSE isolation between projects and environments depends on channel prefixes. Changing Redis database numbers does not isolate Pub/Sub.

- Session uses the configured Redis connection. An in-process dictionary cannot replace sessions shared across multiple workers.
- Distributed SSE uses Redis Pub/Sub; directly streaming local SSE serves a different purpose.
- Cookie messages do not depend on Redis; they provide one-time messages between pages.
- When a Web service installs Admin without explicitly setting the messages switch, `init/sync` fills it with true. This does not automatically enable Session, install Auth, or install Admin routes.

SimpleApplication's `init/sync` does not automatically generate the entire `web` node. If you write that node explicitly, its existing contents remain. It does not start Web routes or browser session middleware. When background code explicitly needs a setting from it, initialization still follows the corresponding module's usage. Having configuration does not mean the capability has started.

See the [Configuration reference](../developers/configuration.md) for fields, actual defaults, and debugging path options.

<!-- source: zh/users/settings-and-apps.md @ d06f9281 -->
