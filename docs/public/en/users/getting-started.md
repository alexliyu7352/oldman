# Run the EPG dashboard demo

This tutorial uses the [EPG Dashboard Demo](https://github.com/alexliyu7352/oldman-epg-dashboard) directly, without creating another tutorial project. Its repository contains all models, forms, tables, templates, and Pages used later; browser operations run that code too. The link points to the project repository. Use a demo commit compatible with the current framework; this text does not establish that unpushed local changes exist remotely.

This dashboard includes a real database and sign-in, rather than a minimal API returning fixed JSON. To create an empty project, use [Creating a service](../agents/create-service.md). Do not remove the demo's Apps, Redis, or frontend initialization to run this tutorial.

## Operating environment and installation

Use Linux, Python 3.12 to 3.14 (3.13 recommended), uv, Node.js 20 or later, and pnpm. When enabling `core.debug`, note that uvloop (unfixed in both 0.22.1 and 0.23.0) may raise errors or segfault while collecting unclosed async generators in asyncio debug mode ([uvloop#699](https://github.com/MagicStack/uvloop/issues/699), [uvloop#715](https://github.com/MagicStack/uvloop/issues/715)). This requires both debug mode and an unclosed async generator in the code; see the [Configuration reference](../developers/configuration.md#web-defaults-and-switches). The default, with debugging disabled, is unaffected. `bootstrap.py` calls `uv` and `pnpm` directly; both must already be on PATH:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh          # uv: Python and dependency management
# Install Node.js 20 or later using your distribution or nvm, then enable the bundled corepack:
corepack enable                                          # Provide pnpm, the version is specified by the packageManager of the repository package.json
```

You also need an accessible Redis. The default example enables Taskiq and Core communication, so NATS with JetStream enabled is required too; see [the communication tutorial](service-communication.md#1-prepare-and-start-the-demo). Actual dependencies are declared in the demo's [pyproject.toml](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/pyproject.toml) and [frontend/package.json](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/package.json). This documentation does not maintain a second version list.

If you do not have the demo yet, clone it from the directory where you want to keep the project:

```sh
git clone https://github.com/alexliyu7352/oldman-epg-dashboard.git oldman_epg_dashboard
cd oldman_epg_dashboard
python3 scripts/bootstrap.py
```

When this repository already exists, enter the existing directory and run bootstrap without cloning again. Unless otherwise specified, subsequent commands are executed in the **Demo root directory** and not in the framework source code directory.

[bootstrap.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/scripts/bootstrap.py) has two actual installation paths:

- A sibling `oldman_framwork/` or `oldman/` source directory exists: create the demo's own `.local/oldman` link and `.venv`, install Python in editable mode, and use framework frontend source in Vite.
- No sibling source: install the release packages declared in the manifests. This works only when the corresponding versions have been published to the package index in use. An older package with the same name is not the current source version.

Both paths use the same business code. There is no need to modify the dependency list every time between local debugging and public examples, and there is no need to install the demo into the framework's virtual environment.

## 1. Prepare the configuration of the current service

Demo's [services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py) defines `WebService`. The file name determines the service name `web`, so the command and default configuration file are:

```text
./run.sh web ...
data/web_settings.yaml
```

The first run creates the missing configuration files for the five services that the demo has defined. Even if only the web is started temporarily, project-level migrations read these configurations:

```sh
for service in web task_worker task_scheduler nats_a nats_b; do
  test -e "data/${service}_settings.yaml" || cp "data/${service}_settings.example.yaml" "data/${service}_settings.yaml"
  ./run.sh "$service" settings sync
done
./run.sh web settings check
```

**Do not overwrite existing configuration again**, just run sync/check and check the required nodes. sync completes the default values and missing security keys; check verifies the configuration, does not create data tables, does not import demo data, and does not prove that Redis is connected successfully. Real keys and local configuration should not be submitted.

All five services use the same database and Auth User model. Preparing all configuration files does not start every service. For ordinary dashboard pages, Worker, Scheduler, and nats_a/nats_b need not run. If you are not running NATS, disable both taskiq.enabled and nats_bus.enabled in your own Web YAML; disabling Taskiq alone leaves Core enabled. Enable and start the relevant services following their tutorials when you want those features.

The database and Redis nodes in [Configuration Template](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/web_settings.example.yaml) are as follows. This is an excerpt from an existing file, do not append it as a second set of nodes with the same name:

```yaml
database:
  url: sqlite+aiosqlite:///data/epg_dashboard.db
  echo: false
  enable_sql_logging: false
redis:
  SESSION:
    redis_url: redis://127.0.0.1:6379/5
  SSE:
    redis_url: redis://127.0.0.1:6379/6
```

SQLite stores business data. Redis SESSION stores sessions, while SSE provides realtime delivery. The complete example also includes CACHE for statistics, TASKIQ for task results/schedules, and framework DEFAULT aliases (one for Redis and one for NATS, used when no alias is specified). Check every connection for your environment; do not change only the two addresses excerpted above. The demo does not start or manage external Redis. Commands/buttons modify only their documented keys, without clearing an instance. With shared Redis, use a different `core.namespace` per environment (the first segment of this service's Redis keys/channels, falling back to `core.app_name`) and check the Taskiq namespace. Redis database numbers do not isolate Pub/Sub; prefer a dedicated instance for independent verification.

## 2. Create tables, then import data

Run in the order of Demo README:

```sh
./run.sh db migrate
./run.sh web loaddata demo
./run.sh web createsuperuser
```

- `db migrate` applies migrations already included in the repository. Select “first use” for a new database; do not select it for an existing database to bypass the prompt.
- `loaddata demo` reads `apps/examples/fixtures/demo.json`, imports examples and real records of EPG business pages.
- `createsuperuser` comes from the Auth App (`oldman.auth`). Enter your account and password interactively. Do not assume a default account or password exists.

Do not regenerate initial migrations for an existing database. Reimporting fixtures updates specified fields for the same primary keys and may overwrite edits to preset records; it does not only fill missing data. See [the data tutorial](tutorial-tasks.md).

## 3. Build and start

```sh
pnpm --dir frontend build
./run.sh web static collect
./run.sh web start
```

Frontend build prerequisites already collect icons and generate browser translations. static collect gathers static assets from the framework and installed Apps. Production Web reads the build manifest without connecting to Vite.

Open [http://127.0.0.1:17997/](http://127.0.0.1:17997/). If signed out, you reach the sign-in page; sign in with the account you just created. Then open:

- [/examples/tables/static](http://127.0.0.1:17997/examples/tables/static): Database data is rendered directly by the backend.
- [/examples/tables/html](http://127.0.0.1:17997/examples/tables/html): Server-side HTML dynamic table.
- [/examples/tables/json](http://127.0.0.1:17997/examples/tables/json): JSON dynamic table for the same query.

The expected example data should appear. An accessible page with an empty list does not establish successful initialization. The next chapter explains how to trace the data source.

`web start` runs in the foreground. Press Ctrl+C in that terminal to stop it; do not terminate services you do not own to free the port. If 17997 is occupied, first determine whether the existing demo owns it. For an independent instance, use separate directories, database, and configuration, and adjust addresses accordingly: change `web.listen_port` and `web.domain` together. Password reset email links are built from `web.domain`; changing only the port leaves links pointing at the old address.

## 4. Local debugging

After stopping the production mode service that you started, run in the same Demo root directory:

```sh
python3 scripts/dev.py
```

This demo script manages Vite and the Web service. Access backend port 17997 in the browser. Style, TypeScript, and template changes appear automatically; Python changes require stopping and rerunning. With sibling framework source, Python/TypeScript changes can be debugged directly without rebuilding a wheel first.

`run.sh` has different responsibilities. It only switches to the project root directory and hands the parameters to `.venv/bin/oldman` as they are. For example, `./run.sh web start` is equivalent to executing `oldman web start` using this environment; running `./run.sh` will not automatically migrate, import data, or start multiple services.

## Find the code from the page

| What are you looking at | Files in Demo |
| --- | --- |
| Service, CSRF, template and bundle initialization | [services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py) |
| root configuration type, global configuration entry | [config/schemas.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/config/schemas.py), [config/settings.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/config/settings.py) |
| Sign-in, sign-out, profile, user management, and role management (framework account flows) | [apps/accounts/routes.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/accounts/routes.py) |
| Display name, icon and registration object of the sample App | [apps/examples/apps.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/apps.py) |
| Example classification and specific routing module loading | [`apps/examples/views/__init__.py`](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/__init__.py) |
| Single browser startup entry point | [frontend/src/main.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/main.ts) |
| Private components and actions of the example page | [frontend/src/pages/examples.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/pages/examples.ts) |

The template is at `templates/pages/examples/`, not `templates/examples/`. The frontend sample pages share `ExamplesPage`, and each URL does not require a TS file with the same name.

## FAQ

| Symptom | Check |
| --- | --- |
| Oldman is not installed | Run the demo bootstrap first; a global installation does not install it into the demo's .venv |
| auth is not installed | Did you copy the correct example YAML, and is the service's apps list complete? |
| Sign-in fails | Run migrate before createsuperuser, and use your own account |
| Redis errors on sign-in/realtime requests | Check Redis reachability and matching SESSION/SSE aliases and configuration |
| Empty table | Was loaddata demo run in the same demo against the same database? |
| Missing styles, icons, or manifest | Check frontend build, web static collect, and static paths |
| CSRF 403 on an old page submission | Refresh to obtain a new token; do not disable CSRF |
| Page displays but interactions do not respond | Inspect script requests, Console, and the current Page; an HTML 200 response alone is insufficient |

Next read [real data and migrations](tutorial-tasks.md), then read [tables and Modal forms](tutorial-dashboard.md). For other pages and source codes that have implemented functions, see [Demo page and source index](demo-examples.md).

<!-- source: zh/users/getting-started.md @ 6a3c1971 -->
