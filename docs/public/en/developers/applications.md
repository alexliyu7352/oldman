# Applications and lifecycle

Oldman distinguishes two objects: **Application is the runtime that starts a service; App is a reusable feature package installed by that service.** The `app` exported by an App's `apps.py` is an AppConfig instance, not a Sanic application. In views, `from oldman.web import router` supplies a route registration entry point, not AppConfig.

Agents: before writing code, read the [services and endpoints guide](../agents/create-service.md). It says which interface the task needs, how to wire it and what counts as done.

The wiring below comes from the EPG demo's [services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py) and [apps/examples](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/apps/examples). Public signature tables describe interfaces; class method excerpts help you follow existing services and are not complete new service files.

## Public entry points

```python
from oldman import ServiceBootstrapContext, bootstrap_service
from oldman.apps import AppConfig, AppRegistry
from oldman.runtime import BaseApplication, SimpleApplication, WebApplication
from oldman.runtime import TaskiqWorkerApplication, TaskiqSchedulerApplication
from oldman.web import Request, Response, WebApp, router
```

`WebApp` is the public name for the Sanic type. Views retain Sanic route and request semantics. Oldman does not require another application runtime adapter.

## Service discovery

The framework reads `.py` files directly under project `services/`, ignoring `__init__.py` and names beginning with underscores. Valid service names match `[a-z][a-z0-9_]*`.

Discovery reads direct base classes through Python AST without executing service modules. It can therefore discover services and provide `settings init` commands before configuration files exist.

Each file must define exactly one class directly extending `WebApplication`, `SimpleApplication`, `TaskiqWorkerApplication`, or `TaskiqSchedulerApplication`. Use normal base-class names; do not alias them and expect static discovery to infer their meaning, or generate service classes dynamically. Loading the selected service also checks the actual class against static discovery and rejects abstract classes.

`SERVICE_NAME` changes the readable name used in logs and similar contexts. It does not change the command or default YAML name, which always derive from the file name.

Service modules may import already loaded business models, but must not import extra unregistered modules to create new tables. Model declarations belong to the App model phase.

## Actual loading order

Commands load only required phases. Configuration checks do not start Web:

| Entry point | Read settings and App metadata | Load models | Load App commands | Create Sanic / load views |
| --- | --- | --- | --- | --- |
| `settings init/sync/check` | Yes | No | No | No |
| `bootstrap_service()` / `shell` | Yes | Yes | No | No |
| `<service> --help`, one-off App commands | Yes | Yes | Yes | No |
| `<service> start` | Yes | Yes | Yes, during CLI assembly | WebApplication only |
| Project-level `db` commands | Collect only settings needed for migrations | As needed by the command | No | No |

`oldman --help` shows root help: it discovers services without loading their business models. `oldman web --help` must show commands from Apps installed by the demo's web service, so it loads that service's settings and models. Errors from invalid configuration in the latter do not contradict the former's behavior.

Ordinary service startup follows this order:

```text
Discover services/<name>.py
→ Select data/<name>_settings.yaml
→ Import config.schemas.Settings
→ Import apps.py from each package in settings.apps
→ Validate global and App settings separately
→ Publish conf.settings and bind each App's app.settings
→ Load the configured User and all App models
→ CLI loads App commands and imports the selected service class
→ Construct and start Application
→ WebApplication creates Sanic and installs enabled base extensions
→ Import each App's views
→ Enter the Sanic runtime lifecycle
```

Loading models before views establishes common model ownership and lets non-Web commands use the database. It does not rescan project directories. Registry stores the explicit App list and tracks completed phases.

Loading settings and models should not initiate database, Redis, or NATS I/O. `bootstrap_service()` starts no server, background task, or process Worker and does not connect to databases proactively. Ordinary Web/Simple services load Core receiver declarations when nats_bus is enabled with consume=true; actual connections and consumption begin later in the asynchronous runtime. Commands, Shell, and Taskiq Worker/Scheduler do not automatically load events.

## AppConfig

The demo's Examples App splits views into a package. This actual directory excerpt shows wiring-related files, not a complete inventory:

```text
apps/examples/
├── __init__.py
├── apps.py
├── settings.py
├── commands.py
├── models.py
├── tasks.py
├── forms.py
├── tables.py
├── services.py
├── providers.py
├── views/
│   ├── __init__.py
│   ├── forms.py
│   └── tables.py
├── fixtures/
│   └── demo.json
└── migrations/
    ├── __init__.py
    └── a839bf3055f2_create_example_models.py
```

It includes settings.py for HTTP examples, tasks.py for Taskiq, and commands.py exporting project-stats and coroutine/process/Worker/cache example commands. commands.py may import concrete Command classes from sibling modules rather than contain every implementation; see [custom commands](cli.md#custom-app-commands). Default `views` may be a module or a package as here. A package imports concrete views through its own `__init__.py`; Registry does not scan directories for each feature. Apps lacking a capability omit its module instead of creating empty implementations.

`apps.py` must export exactly one public `AppConfig` instance named `app`. Defining a class is not exporting an instance. See [the user guide](../users/settings-and-apps.md#install-apps) for the complete ExamplesAppConfig: label `examples`, display name `Dashboard Examples`, and icon `ri-flask-line`.

| Attribute | Default / constraint | Purpose |
| --- | --- | --- |
| `label` | Required; `[a-z][a-z0-9_]*` | Stable identifier, unique within the Registry |
| `display_name` | Required; nonempty `str` or `LazyTranslation` | Display name for menus, command groups, etc. |
| `icon` | `ri-database-2-line` | One icon class, supporting `ri-`, `mdi-`, `bx-`, `bxs-`, and `bxl-` prefixes |
| `settings_model` | `None` | Optional Pydantic `BaseModel` subclass |
| `models_module` | `"models"` | Model module relative to the App package |
| `migrations_module` | `"migrations"` | Migration module relative to the App package |
| `web_module` | `"views"` | Web module relative to the App package |
| `permissions_module` | `"permissions"` | Permission declarations, loaded after models at every service startup (before views for Web); see [Permissions](permissions.md) |
| `commands_module` | `"commands"` | Command module relative to the App package |
| `tasks_module` | `"tasks"` | Task module loaded by Worker/Scheduler after models |
| `events_module` | `"events"` | Handler declarations loaded after models by Web/Simple with Core consumption enabled |
| `mcp_module` | `"mcp"` | MCP tool/resource/prompt declarations (`from oldman.mcp import mcp`); loaded after models only by Web services calling `install_mcp(app)` with `web.mcp.enabled` true |

Module paths must be nonempty relative Python module paths, not `None`. Missing default model, view, or command modules are skipped normally. An existing module with a failing internal import retains the actual exception rather than pretending the module is absent. Custom nested paths require real parent packages.

For App-specific settings, follow the demo's `ExamplesAppConfig(AppConfig[ExamplesSettings])`, whose settings_model points to ExamplesSettings for the HTTP upstream address, or the built-in AdminAppConfig it uses. The generic parameter determines app.settings static typing; settings_model controls runtime construction. Both should reference the same class. See [App Settings](configuration.md#app-settings) and [the HTTP example](http-client.md#actual-use-in-the-demo) for complete declarations and access paths.

`settings.apps` already provides package paths; do not add a separate `name`. AppConfig has neither a `ready()` hook nor declarations to install dependencies automatically. Explicitly install required Apps in service configuration and wire their interfaces.

Keep the App package root, `apps.py`, and settings model module lightweight: do not read unbound `app.settings`, import views, declare or import tables early, or connect to external services.

### Settings access exceptions

Import these exceptions from `oldman.apps`:

| Exception | Cause | Handling |
| --- | --- | --- |
| `AppNotInstalledError` | This service has not installed the App | Check package paths in its YAML |
| `AppSettingsNotDefinedError` | Reading `app.settings` without a declared settings model | Define required settings or stop reading nonexistent settings |
| `AppSettingsNotReadyError` | Reading before settings binding completes | Move access out of metadata import or finish bootstrap first |

Do not catch these exceptions and silently return defaults. That hides missing installations and initialization-order errors as harder-to-diagnose business failures.

## AppRegistry

You normally need not construct Registry manually. Service bootstrap creates it; debugging code gets it from `context.apps`.

| Attribute / method | Return value or behavior |
| --- | --- |
| `packages`, `labels` | Tuples preserving configuration order |
| `configs` / Registry iteration | Installed AppConfig instances |
| `get_by_package(package)`, `get_by_label(label)` | Selected App; raises `AppNotInstalledError` if absent |
| `models` | `ModelMetadata` tuple after the model phase |
| `get_model_metadata(model)` | Model Table, App label, display name, and managed state |
| `commands`, `get_command(name)`, `get_app_commands(label)` | Query discovered commands after the command phase |

Complete the corresponding phase before reading `models` or `commands`. `register_packages()`, `bind_settings()`, `load_models()`, `load_commands()`, `load_permissions()`, `load_views()`, `load_tasks()`, `load_events()`, and `load_mcp()` are phase interfaces for configuration/runtime use. Applications should not create a second Registry registering alongside the framework. Repeated completed phases do not reimport modules, and Apps cannot be appended after model loading starts. Like tasks, permissions/events/mcp must neither declare new tables nor perform network I/O while loading.

All models share `Base.metadata`. Registry assigns ownership from registered Apps' defining modules; association tables must also live in the corresponding model modules. Auth settings select the `oldman_user` model; do not define a concrete User in every App.

## WebApplication

The demo defines `WebService(WebApplication)` in `web.py`, so its command is `./run.sh web start`.

The base `prepare_server()` takes listening parameters from `web`: host, port, debug, auto_reload, workers, and access_log all come from YAML. `single_process` is derived from having neither multiple workers nor auto_reload (Sanic rejects combining these modes). Increase YAML `workers` to enable multiple processes without code changes.

Override this method only for extra work, retaining the parent call:

```python
def prepare_server(self, app: WebApp) -> None:
    """Check frontend build output, then let the framework prepare listening settings."""
    registry = app_bundle_registry(app)
    registry.ensure_build_available(APP_MAIN_BUNDLE)
    # Languages come from settings; catalogs come from the frontend build. Missing catalogs leave languages untranslated.
    ensure_frontend_catalogs(registry, APP_MAIN_BUNDLE, source_dir=PROJECT_ROOT / "frontend" / "public" / "i18n")
    super().prepare_server(app)
```

`ensure_build_available()` checks assets by production/development mode. Production needs a built, collected manifest; development uses a Vite URL. `ensure_frontend_catalogs()` (`oldman.web.i18n`) verifies compiled frontend catalogs for every configured language. See [Frontend assets, styles, icons, and translation](assets.md) for preparation; `prepare_server()` should not run builds implicitly.

### Wiring templates and base capabilities

The demo's complete `get_ext_config()` supplies Sanic-Ext settings. The original file also imports `Any` from `typing`:

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

Templates use the same global Settings, with asynchronous rendering explicitly enabled. Oldman still manages logging; Sanic-Ext does not install another logging system.

After base initialization, the demo's `init()` follows the dashboard scaffold generated by `startproject`: CSRF, notifications, templates/frontend bundles, then account pages. It then adds project-specific token endpoints and the built-in Admin:

```python
def init(self) -> None:
    """Install scaffold CSRF, notifications, templates/bundles, and accounts, then project tokens and Admin."""
    super().init()
    app = self.runtime_app
    if app is None:
        raise RuntimeError("Sanic app was not initialized")
    StatelessCSRFManager(app)
    notification_routes = install_notifications(app)
    install_dashboard_templates(app)
    install_account_pages(app, notification_routes=notification_routes)
    install_token_routes(app)
    # Admin mounts at app_settings.admin.prefix (default /admin), shares sign-in state, and opens via full-page navigation.
    install_admin(app)
```

These names come from the same service file:

- `StatelessCSRFManager` is imported from `oldman.web.security.csrf`.
- `install_notifications` is the import alias of `oldman.web.messages.notifications.init_app`, not another subscriber. Its returned routes let account pages install the notification center.
- `install_dashboard_templates()` matches the scaffold: it installs shared/project template loaders, wires static bundles through `register_project_bundle()` and `registry.install_template_globals()` (see [Frontend assets, styles, icons, and translation](assets.md)), then registers `app_main_bundle`, menu checks `can_manage_users`/`can_manage_roles`, and demo business notifications in the top bar. Language menus, CSRF tokens, and account URLs `account_urls` are framework globals, not supplied here.
- `install_account_pages()` (apps/accounts/routes.py) installs framework sign-in, profile, notification center, user management, role management, and password reset flows at `web.account` addresses. It also installs `/user-events` when SSE is enabled.
- `install_token_routes()` (apps/accounts/tokens.py) adds token endpoints absent from the scaffold; `install_admin()` installs the built-in Admin.

Base `init()` creates Sanic and the extension environment, installs messages/Session according to switches, initializes Storage and the SSE output extension, then asks Registry to load models/views. Bootstrap already completed models, so this does not load them twice. The demo override adds its capabilities afterward; all wiring is complete before requests are handled. Do not assume project template globals/CSRF helpers exist while importing `apps.py`, models, or views. Register project globals with `template_globals(environment)["name"] = value` (`from oldman.web.template import template_globals`). Jinja does not annotate `environment.globals`; type checkers infer a narrow dictionary from its defaults, so direct `environment.globals[...]` assignment triggers Pyrefly errors despite identical runtime behavior.

Register project request/response middleware in this `init()` override too. See [custom middleware](web.md#custom-middleware) for signatures, short-circuit behavior, and ordering relative to base middleware.

The following extension points are framework reference interfaces; the demo does not override every method.

Override as needed:

| Method | Timing / requirements |
| --- | --- |
| `get_ext_config()` | Sanic-Ext settings mapping, default `None`; enable asynchronous templates if needed and keep `logging` false |
| `get_extension()` | Sanic-Ext extension collection; defaults include injection, OpenAPI, HTTP, health, and templating |
| `get_runtime_config()` | Optional low-level Sanic overrides; prefer `settings.web` for ordinary settings |
| `init()` | Creates Sanic, configures base extensions, and loads views; call `super().init()` first when overriding |
| `async main_process_ready(app)` | After the Sanic main process is ready |
| `async before_server_start(app)` | Before worker startup; the base initializes Web i18n here |
| `async after_server_start(app)` | After worker startup |
| `async before_server_stop(app)` | Before stopping; the base cancels registered background tasks |
| `async after_server_stop(app)` | After stopping, while asynchronous cleanup still works and Taskiq/Core remain open. The framework then closes them, waits for model cache invalidation writes, and closes cache, Redis, and database engines. Overrides need not call super() |

Listener methods receive only `app`; do not add `loop`. Retain required `super()` calls in lifecycle overrides. Initialize resources needing an event loop in asynchronous lifecycle hooks, not imports or constructors.

Startup errors exit nonzero so process supervisors can restart the service. Sanic workers report startup after before_server_start, before after_server_start runs. In Sanic 25.12.1, a subsequent startup-failure report makes the main process treat it as a restart request and spin without exiting. The framework patches Sanic's `WorkerManager` until Sanic fixes this. Put connections and configuration checks in before_server_start wherever possible to fail early.

With nats_bus enabled, the framework opens Core in the **actual Sanic worker**, then enabled Taskiq publication connections, then runs user before_server_start. Core consumption starts only after user after_server_start completes. Shutdown stops receiving and awaits handlers' finally blocks before user before_server_stop/after_server_stop, then closes Taskiq/Core, cache, Redis, and database engines. Cleanup still completes after business hook failures. If before_server_stop fails, Sanic skips after_server_stop and cleanup happens in that earlier step. The main process loads declarations only, without creating cross-process shared clients. Do not repeat bus start/stop in subclass hooks. See [the NATS lifecycle](providers.md#app-and-runtime-lifecycle) for budgets, exceptions, and separately owned resources.

`runtime_app` is `None` before initialization and a Sanic instance afterward. It stays `None` on non-Web services (SimpleApplication and Taskiq services). Registering AppConfig alone does not install all built-in routes: `install_admin(...)`, for example, is an extra wiring step, not replaced by the package list.

Services must close custom pools and clients. Do not assume the base discovers arbitrary business resources automatically. Tutorials show database cleanup; request Sessions use context managers without destroying shared pools per request.

## SimpleApplication

These ordinary SimpleApplication interfaces come from [oldman/runtime/simple.py](https://github.com/alexliyu7352/oldman/blob/main/oldman/runtime/simple.py). Actual examples are services/nats_a.py and nats_b.py, two independent Core receivers in the demo; see [Let running services communicate with each other](../users/service-communication.md). They share a receiving App instead of copying brokers or collection/scheduling loops.

It creates neither Sanic nor App views. Implement:

```python
def prepare(self) -> None:
    ...

async def main(self, *args, **kwargs) -> None:
    ...
```

Normal startup runs init/models, enabled events declarations, then synchronous prepare. In the event loop it opens enabled Core/Taskiq send connections, runs before_start, starts Core consumption, then runs main. When main returns or a stop signal arrives, it ends Core handlers, runs before_stop/after_stop, closes Taskiq/Core, then cache, Redis, and database engines. Returning from main ends the service. Demo main waits with await asyncio.Event().wait() for normal shutdown; an empty main does not become a Worker.

If `before_start`, `main`, or stop hooks raise, the framework still runs stop hooks and closes connections, logs the exception with its traceback, and re-raises. `start` exits nonzero, visible to supervisors configured to restart on failure. `prepare` runs synchronously before the loop and this lifecycle. Its exceptions are also logged with tracebacks and exit nonzero, but do not run stop hooks or framework Core/Taskiq/cache/Redis/database cleanup. `prepare` must clean up resources it opens before raising. `asyncio.TaskGroup` in `main` logs every child exception's traceback. Stop signals and Ctrl-C are normal exits.

`before_start()`, `before_stop()`, and `after_stop()` are asynchronous extension points. Base before_stop cancels background tasks registered through its interface. After after_stop, the framework closes Taskiq/Core, waits for model cache invalidations, then closes cache, Redis, and database engines in order. Failure in one does not skip later resources; business hook failures also retain cleanup. Business-owned resources still need their own cleanup, but do not duplicate `await db_manager.close()`.

Overrides of `after_stop` need no super call (the base does nothing). Receiving handlers have already exited. Stop hooks may still send through Core to other online services, but must not expect stopped local subscriptions to reply. Signals cancel the managed main coroutine rather than interrupt cleanup with loop.stop. Cancellation remains cooperative and gives no hard deadline for unbounded blocking business code.

App commands neither run `main()` nor start background services; they follow [the command lifecycle](cli.md#command-lifecycle). Do not put all command initialization in `prepare()` and assume one-off commands call it.

## Dedicated Taskiq services

The demo provides task_worker and task_scheduler. task_worker extends TaskiqWorkerApplication, using native ProcessManager for execution children. task_scheduler extends SimpleApplication through TaskiqSchedulerApplication and runs only the native scheduler. Neither loads Web views; both load installed App tasks after models. Ordinary Web/Simple/commands manage enabled publication connections without importing every task. See [the Taskiq runtime](distributed-tasks.md#app-and-service-loading) for exact ordering, explicit Shell connections, and ownership.

## Access services outside service classes

Use `self` inside service methods. Views, background tasks, and App commands use the service class's `current()` to obtain this process's running service. Like Sanic's `get_app()`, this retrieves the whole service rather than only one part.

`current()` retrieves without constructing: it returns the process's service if it is an instance of this class or a subclass, otherwise `None`. The actual object retains IDE completion for subclass attributes.

This function builds a URL from the route table without a request, for example for background email. `WebService` is the EPG demo's service class; `example_cache_page` names its `/examples/cache/redis` route:

```python
def cache_page_path() -> str:
    # Import inside the function: EPG services/web.py imports App modules too, so a top-level import would cycle.
    from services.web import WebService

    service = WebService.current()
    app = None if service is None else service.runtime_app
    if app is None:
        raise RuntimeError("This process has no running Web service or route table")
    return app.url_for("example_cache_page")
```

Reusable Apps do not know the project's service class. Use `BaseApplication.current()` for any service or `WebApplication.current()` for Web services only. Import both from `oldman.runtime`.

Every service has `runtime_app`. It is `None` when the service creates no Web server or before Web initialization. App commands construct service objects without creating Sanic.

**Where `current()` returns `None`.** The CLI constructs services before running them or App commands; each Sanic worker also constructs its own. Taskiq execution children, Shells, and scripts calling only `bootstrap_service()` do not construct a service. There `current()` returns `None` without error, so importing modules using it does not fail. Use `oldman.conf.settings` and the context returned by `bootstrap_service()` when you need settings.

**Call it inside functions.** A top-level `svc = WebService.current()` freezes the value at import time. Views load after service construction and can retrieve it; App commands and modules imported by service modules load earlier, so their cached `None` does not change after startup. Top-level access suits only cases where `None` is acceptable. One `current()` call takes about 75 ns; caching it to save that step is unnecessary.

**Each process has its own.** Each Sanic worker constructs its service and application. It retrieves the application handling its current request; `runtime_app.ctx` and `request.app.ctx` are the same object. With multiple workers, the main process has its own non-request-handling service/application. Attributes added to `ctx` in `main_process_ready` are not visible to workers.

`runtime_app` is the underlying server object, outside Oldman's own interface. Prefer Oldman entry points for capabilities it provides, such as `router` for routes and `BackgroundTaskManager()` for background tasks.

Service members have two categories; keep them distinct:

| Readable at runtime | CLI lifecycle only |
| --- | --- |
| `app_name`, `bootstrap_context`, `runtime_app`; Web/Simple `task_manager`; subclass attributes | `start()`, `stop()`, `restart()`, `run()`, `init()`, `shutdown()` |

The CLI calls the latter before/after service execution. Calling them inside a running service has the same CLI behavior: `stop()` verifies the identity record beside the PID file, sends SIGTERM to the **main process**, and waits for the entire process group. Calls from the service's own processes, including workers, are rejected because the caller belongs to that group. Neither rejection nor success (such as an App command stopping a running service) affects the caller's logging. The CLI closes logging when commands on its constructed instance end; these methods do not. The exception is `start()`, which actually runs the service: its `run()` closes logging when service execution ends.

## Python Shell and IDE

In the EPG demo root, run:

```sh
./run.sh web shell
```

Shell supplies `context`, `settings`, and `apps`; import service models directly. It creates no Sanic, views, or business background tasks.

IDE Python Shells use the same public entry point. This interactive example references existing demo settings/models, rather than another demo script. Set working directory and import paths to the application root first:

```python
from oldman import bootstrap_service

context = bootstrap_service("web")

from config.settings import settings
from apps.examples.models import ExampleProject

assert context.service_module == "web"
```

Public signature:

```python
def bootstrap_service(
    service_module: str,
    *,
    config_file: str | Path | None = None,
) -> ServiceBootstrapContext:
    ...
```

The returned frozen dataclass contains `service_module`, resolved `config_file: Path`, `settings`, and `apps`. The context container is frozen, not the Pydantic settings deeply contained within it.

Repeated calls with the same service and resolved path return the existing context; they do not hot-reload disk configuration. Changing service or configuration file fails and requires a new process. Tests should use isolated processes or test fixtures rather than adding production reset APIs.

Pure functions without configuration dependencies remain directly importable in ordinary Python Shells. Run asynchronous database operations inside the debugging session's event loop and close used connections. Bootstrap itself is not a database connection entry point.

<!-- source: zh/developers/applications.md @ 84e6ddf1 -->
