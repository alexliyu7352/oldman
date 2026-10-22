# Developer reference

This reference defines public entry points, loading order, and extension contracts. For your first project, start with [Run the EPG dashboard demo](../users/getting-started.md); you need not read every reference first.

Agents developing an application start at the [agent guide](../agents/README.md): find the guide for the task and read it before writing code, then come back here for exact interfaces.

A name is public when included in its exporting package/module's `__all__`; import it there. Any module path segment starting with an underscore, such as `oldman.cli._main`, is internal. The source-generated API index `docs/public/en/api/README.md` lists public names, signatures, and import locations.

| Topic | Contents |
| --- | --- |
| [Applications and lifecycle](applications.md) | Service discovery, AppConfig, Registry, Web/SimpleApplication, Shell, resource ownership |
| [Configuration reference](configuration.md) | Root/App Settings, YAML management, defaults/paths, mutable runtime configuration |
| [CLI reference](cli.md) | Project/service commands, interaction conventions, custom async Commands |
| [Terminal interaction](tui.md) | CLI/operations output, tables, waiting, questions, forms, menus, cancellation, non-terminals, testing |
| [Operations primitives](ops.md) | Repeatable configuration editing, os-release, systemd units |
| [Remote files](remote.md) | Remote Python files/scripts in operations menus: base URLs, cache/refresh, conventions, credentials |
| [Web requests, templates, and permissions](web.md) | Routes, template loading, Session, permissions, CSRF, error pages |
| [Permissions](permissions.md) | Code declarations, naming/startup checks, roles, role cache |
| [Forms, fields, and remote choices](forms.md) | WTForms responsibilities, binding/validation, ModelForm, layouts, remote choices |
| [Static, HTML, and JSON Tables](tables.md) | HTML/JSON data, queries, column paths, sorting, stable DOM |
| [Chart](charts.md) | Data endpoints, shells, request allowlists, time windows, result objects |
| [Browser responses and ordered actions](responses.md) | JSON/Form/HTML boundaries, ordered actions, targets, errors |
| [Pages, components, and dynamic content](frontend.md) | Page, components, Modal, dynamic mounting, HTTP, navigation cleanup |
| [Frontend assets, styles, icons, and translation](assets.md) | Vite, bundles, fonts, icons, visual variables, shared translation |
| [Models and database sessions](database.md) | Mapping, sessions, transactions, queries, User foreign keys, connection cleanup |
| [Project database migrations](migrations.md) | Project scope, App branches, renaming, external tables, downgrade, state recovery |
| [JSON data import and export](fixtures.md) | Service imports/exports, field types, foreign-key ordering, failure boundaries |
| [File storage and model file fields](storage.md) | Aliases, async I/O, file fields, replacement/deletion, private downloads |
| [Mail](mail.md) | Message objects, backends, template emails, locmem tests, `mail sendtest` |
| [Caching](cache.md) | Memory/Redis/two-level caches, TTL, response/model caches, Django interoperability, image caches |
| [Redis and NATS providers](providers.md) | Named connections, locks, managed buses, typed events/RPC, addressing, startup/shutdown ownership |
| [Backend HTTP client](http-client.md) | Three backends, shared responses, retries, streams, Cookies, TLS |
| [Media streaming proxy](proxy.md) | Upstream status forwarding, final player-visible failures, route-handler responsibilities, live entry points, browser fingerprints |
| [MCP server](mcp.md) | Expose App tools/resources/prompts to AI agents: installation, access, rate limits, protocol versions, known limits |
| [Processes and background tasks](background.md) | Coroutines, short-lived processes, controlled external commands, long-lived Workers, reliability limits |
| [Taskiq interfaces and runtime](distributed-tasks.md) | Native task API, JetStream/Redis, Worker/Scheduler, result/acknowledgment failure boundaries |
| [Logging](logging.md) | Standard Logger, initialization, rotation, child processes, shutdown |
| [Page messages, feedback, and notifications](messages.md) | Cookie messages, Form/Feedback, database notifications, shared top bar/center |
| [SSE and WebSocket](sse.md) | Direct output, Redis publication, Session, translation, backpressure, browser connections |
| [Built-in Admin and extensions](admin.md) | Explicit site installation, ModelAdmin, permissions, template/asset extensions |
| [Security boundaries and rate limiting](security.md) | Shared keys, trust boundaries, Redis rate limits, actual fingerprint-tool responsibilities |
| [Source development, verification, and releases](maintenance.md) | Builds, versions, sequential acceptance, installed artifacts, evidence cleanup |
| [Test isolation requirements](testing.md) | Test boundaries for settings, Apps, models, processes, databases |

Reference classes/functions use public installed-package imports. Private methods appear only to explain call order, not as application entry points.

Before extending, decide whether code belongs to a service, App, or request. Services own startup/resources, Apps supply business modules, and views handle requests. Do not bypass initialization by creating Applications, connecting databases, or loading views during import.

Start from [Demo page and source index](../users/demo-examples.md) for complete usage scenarios, then consult topic-specific APIs. Examples should come from actual demo files and identify excerpts/dependencies. ExampleProjectForm and similar names are demo business classes, not public framework APIs. Inspect specific implementations only for highly customized behavior not covered here.

<!-- source: zh/developers/README.md @ 84e6ddf1 -->
