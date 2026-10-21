# Oldman

English | [简体中文](https://github.com/alexliyu7352/oldman/blob/main/README.zh-CN.md)

Oldman is a server-rendered first Python application framework for dashboards, admin interfaces, Web/API services, and background task services.

Python handles settings, application lifecycles, permissions, data, and HTML. The browser handles partial page updates, form submissions, tables, modals, and realtime interactions. You can work entirely on the backend or add TypeScript to pages that need interaction.

The two packages have distinct responsibilities:

| Package | Purpose |
| --- | --- |
| `oldman` (Python) | Application, App registration, settings, database migrations, Web, Auth, Admin, forms, templates, storage, and background capabilities |
| `oldman-web` (npm) | Page/Component lifecycles, dashboard layouts, shared styles, forms, Tables, Modals, and browser interactions |

The built-in Admin and business dashboards share components, styles, and response protocols, without maintaining two separate frontends.

## Where to start

- [User guide](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/users/README.md): installation, project creation, and practical usage.
- [Developer reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/developers/README.md): exact interfaces, loading order, and extension methods.
- [Agent guide: application development](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/agents/README.md): choose files by task, complete wiring, and verify results.
- [Oldman documentation](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/README.md): find documentation by question.

Start by [running the EPG dashboard demo](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/users/getting-started.md), then follow its tutorials on [real data](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/users/tutorial-tasks.md) and [tables and Modal forms](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/users/tutorial-dashboard.md). Tutorials use actual demo code and specify source files, working directories, configuration, and expected results. See the [Demo page and source index](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/users/demo-examples.md) for more pages.

## The shortest path to a project

First prepare the tools: [uv](https://docs.astral.sh/uv/) manages Python environments and dependencies and installs the `oldman` CLI. `--python 3.13` pins the CLI to a supported Python version. Without it, uv uses the newest interpreter it finds without checking the package's declared version range.

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install --python 3.13 oldman
```

Then run this from the directory that will contain your project:

```sh
oldman startproject my_site
```

On first use, the command asks for the CLI language and remembers it (change it later with `oldman language set <language>`). It then asks for the project type and database. After selecting `api` and `none`, run in the new project directory:

```sh
cd my_site
uv sync
./run.sh api settings sync
./run.sh api start
```

Generated projects include `.python-version` (3.13). `uv sync` selects that interpreter and downloads it if missing locally. The service includes three example endpoints: `/` is an unauthenticated health check; `/api/caller` and `/api/ops` demonstrate API key and HTTP Basic authentication. See the generated project's README for credentials and example commands. For API wiring, see [Creating a service](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/agents/create-service.md). To explore complete business pages directly, run the demo above.

`run.sh` passes arguments unchanged to `oldman` in the project's `.venv`. It does not select a service, migrate databases, or start the frontend for you. `./run.sh api start` has the same meaning as `oldman api start` in the same virtual environment. These commands create an empty project; they are not demo startup instructions. See [runtime requirements and installation](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/users/getting-started.md#operating-environment-and-installation) for the demo's separate installation and debugging.

## What the framework provides

- **Application organization**: a project can contain multiple services, each reading its own YAML and explicitly installing its required Apps. Apps can provide models, views, custom commands, and strongly typed settings.
- **Web and data**: asynchronous services based on Sanic, Jinja HTML, SQLAlchemy models, project-level Alembic commands, Auth, and Admin.
- **Page interactions**: backend Forms and HTML/JSON Tables; shared frontend components such as Form/Modal/Feedback/Select/Chart; and ordered JSON response actions.
- **Messages**: Cookie flash messages, persistent database notifications, temporary realtime pushes, and general SSE browser delivery. Process control messages have separate responsibilities.
- **Infrastructure**: file storage, HTTP Client, caches, Redis/NATS providers, logging, short-lived child processes, and persistent Workers.
- **Durable tasks**: Taskiq + NATS JetStream + Redis for asynchronous function publication, multiple execution processes, results, broadcasts, and schedules. Use these separately from long-lived local Workers and Core NATS events/RPC.

Ordinary APIs do not require the frontend package. Install `oldman-web` and its declared dependencies when you need the shared dashboard UI. Default browser assets for the built-in Admin ship with the Python package.

The current runtime target is Linux. Supported Python versions are `>=3.12,<3.15`, with 3.13 recommended. Known limitation: with `core.debug` enabled (asyncio debug mode), uvloop (unfixed in 0.22.1 and 0.23.0) may raise errors or segfault while collecting unclosed async generators ([uvloop#699](https://github.com/MagicStack/uvloop/issues/699), [uvloop#715](https://github.com/MagicStack/uvloop/issues/715)). This requires both debug mode and an unclosed async generator; changing Python versions does not avoid it. See the [Configuration reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/developers/configuration.md#web-defaults-and-switches). Production with the default debugging disabled is unaffected. Dashboard projects and both demos also require Node.js 20 or later and pnpm (`corepack enable` enables it). The SQLite driver ships with the Python package; declare MySQL/PostgreSQL drivers according to project needs. Redis connection settings alone do not cause connections at startup; a reachable service is needed when the corresponding capability is enabled or called.

## Complete examples

- [Admin demo](https://github.com/alexliyu7352/oldman-admin-demo): a standalone application using the built-in Admin.
- [EPG Dashboard demo](https://github.com/alexliyu7352/oldman-epg-dashboard): a business dashboard with UI and feature examples.

Examples are separate Git repositories with their own settings, virtual environments, frontend dependencies, and databases. Follow each example's README for actual setup; do not install them inside the framework directory.

## Source layout

```text
oldman/                       Python framework and bundled resources
frontend/packages/oldman-web/  Browser package
frontend/apps/admin/          Frontend source for the built-in Admin
examples/snippets/            Usage excerpts, not complete applications
tests/                        Python tests
scripts/                      Maintenance and verification tools
docs/                         User, developer, and agent documentation
```

The Python and npm packages do not include business code or runtime data from standalone demos. The framework repository is not a business project. Do not add application `config/`, `services/`, or databases to its root.

See [PRODUCT.md](https://github.com/alexliyu7352/oldman/blob/main/PRODUCT.md) for product decisions.

<!-- source: README.zh-CN.md @ 7dfc0480 -->
