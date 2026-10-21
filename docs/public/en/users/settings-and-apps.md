# Settings, Apps, and Services

Their responsibilities are simple: **the service decides what starts, the App provides capabilities, and the configuration file determines which capabilities and values the service uses.**

This article takes EPG Demo as an example: [services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py) provides Web services, [apps/examples/apps.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/apps.py) registers function examples, and [data/web_settings.example.yaml](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/web_settings.example.yaml) saves the public initial configuration of the service. The following commands are executed in the Demo root directory; see [Introduction Tutorial](getting-started.md) for installation prerequisites.

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

You can use `startservice` to add services in the future. For specific interfaces, see [CLI Reference](../developers/cli.md#项目级命令). This command only creates the entry file and does not automatically create the configuration. For the shared namespace, connections and different App lists of the three Web/Taskiq services, see [Distributed Task Tutorial](distributed-tasks.md); for the two Simple receiving services, see [Communication Tutorial](service-communication.md). These five services still use the same root Settings type, and their initial configuration does not mean starting all services.

Different services run in different processes, and each has its own current Settings instance. A process cannot first initialize a service configuration and then switch to another service to continue running.

## Create, check and complete configurations

| Command | Purpose | Writes files? |
| --- | --- | --- |
| `./run.sh web settings init` | Create missing configuration; fail if it already exists | Yes |
| `./run.sh web settings sync` | Keep existing values and comments, fill in missing fields and necessary keys | Yes |
| `./run.sh web settings check` | Verify the current configuration and output diagnostics | No |
| `./run.sh web start` | Read the configuration and start the service | Do not automatically rewrite YAML |

The demo provides `data/web_settings.example.yaml`. If local `data/web_settings.yaml` does not exist, run `./run.sh web settings init`. The framework reads the example, fills in default fields, and generates local keys; no prior YAML copy is needed. If you already copied or initialized the file following the demo README, use `sync` without overwriting local configuration. Ordinary projects without a matching example file have an empty App list by default.

This suits public projects: commit an example without real passwords or keys, and users obtain local configuration on their first `settings init`. The framework does not scan every business directory and assume this service should install them all.

`sync` will not overwrite the values you have filled in with new default values. For example, if `messages.enabled: false` is written, it will not change to true because you install Admin; after moving the project, it will not automatically correct the persisted absolute path. `core`, `logging`, `process`, static directories, and Storage paths should be checked and edited.

The run configuration is YAML. Ordinary business configuration values are not read from `.env` or environment variables with the same name. The environment parameters of tools such as CLI language and project directory discovery are another matter, and it cannot be inferred from this that business Settings support environment variable injection.

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

`oldman.apps.admin` provides shared settings and user management commands. Adding it to the list does not mount `/admin`; the EPG demo uses its own dashboard. See the [Admin tutorial](admin.md) for the standalone Admin site.

An App must be importable in the current Python environment and have a `<包路径>.apps` module exporting an `AppConfig` object named `app`.

The same usage is used for third-party apps: first install its Python package, and then write the actual import package path given in its document into the list. The Python release package name and import path may be different, do not guess the path based on the pip name.

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

For details on directory and loading constraints, see [AppConfig Reference](../developers/applications.md#appconfig).

## An App's own settings

The settings for a reusable app are placed in the app's own Pydantic class. The above ExamplesSettings comes from the Demo package [settings.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/settings.py), which defines the http_base_url actually used by the HTTP example. The default is <https://httpbin.org>. `AppConfig[ExamplesSettings]` and `settings_model = ExamplesSettings` declare both static types and runtime configuration types; the service configuration's `app_settings.examples.http_base_url` is bound to its app.settings. This example rejects non-HTTP(S), credentials, queries, and fragments, and addresses can only be provided by trusted deployment configurations.

The actual consumer is run_http_example in [http_example.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/http_example.py). It imports app from that App and reads app.settings.http_base_url when the function runs, rather than during metadata import. See the [HTTP example](cache-and-http.md#running-the-backend-http-example) for configuration and operations. Only Apps needing settings declare a model; other Apps do not need empty settings classes.

The demo also installs the built-in Auth and Admin, whose strongly typed settings are read by the framework itself. Admin's sign-in policy illustrates this path below.

Admin's configuration is declared in the framework [AdminSettings](https://github.com/alexliyu7352/oldman/blob/main/oldman/apps/admin/settings.py) and registered in the framework [AdminAppConfig](https://github.com/alexliyu7352/oldman/blob/main/oldman/apps/admin/apps.py). These two codes belong to the framework package installed by Demo and do not need to be copied to Demo:

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

When two different services install the same App with settings, they can fill in different values in their respective YAMLs; the shared business code maintains the same import entry, and there is no need to determine which service you are in. It can only be read when the configuration has been initialized and the App has been installed; the normal CLI will complete the initialization, IDE see [Shell and bootstrap](../developers/applications.md#python-shell-与-ide).

Apps that are not installed will not generate configuration; however, an error will be reported when YAML writes its `app_settings`. When an App with a configuration model is installed but no specific value is filled in, the default value of the model is used; the verification fails when a required field without a default value is missing.

Do not write `settings.admin`, `settings.app_settings` or `settings.for_app(...)`. App and root Settings are two strongly typed object spaces, just saved to the same YAML. For the method of writing App configuration model, see [App Settings Reference](../developers/configuration.md#app-settings).

## Shared project configuration

There is only one root type for the entire project. Demo's [config/schemas.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/config/schemas.py) declares the project default configuration of database, Web, i18n and Storage on `DefaultSettings`; instead of writing a set of `ApiSettings` and `WebSettings` for each service. For specific classes and default functions, see [Root Settings Reference](../developers/configuration.md#根-settings).

The business import entry point is [config/settings.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/config/settings.py), with these complete contents:

```python
"""Runtime settings instance for the Oldman application."""

from typing import cast

from oldman import conf

from config.schemas import Settings

settings = cast(Settings, conf.settings)
```

`cast()` only tells the static analyzer that this is the project's Settings. It neither reads YAML nor creates another configuration. Business code uses `from config.settings import settings`; do not copy it to `app.ctx.settings`.

Only fields that truly belong to the project's public settings are added to the root class; fields unique to a reusable app should remain in the app's configuration model. Each service shares the type and reads its own YAML value.

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

<!-- source: zh/users/settings-and-apps.md @ 950469ee -->
