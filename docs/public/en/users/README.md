# User Guide

This guide is for people developing applications with Oldman. You do not need to read the framework's internals first.

## Learn in order

1. [Run the EPG Dashboard Demo](getting-started.md): installation, a separate directory, configuration, migrations, data, accounts, and startup.
2. [Real demo data](tutorial-tasks.md): follow actual models, fixtures, migrations, and database queries.
3. [Demo tables and Modal Forms](tutorial-dashboard.md): operate existing HTML/JSON Tables and understand sign-in, forms, and create, update, and delete flows.
4. [Settings, Apps, and services](settings-and-apps.md): use different settings for multiple services and register reusable Apps.
5. [Data and files](data-and-files.md): the demo's two file fields, uploads, replacements, deletion, and rollback checks.
6. [Caching and external HTTP](cache-and-http.md): operate real Redis project statistics and backend HTTP JSON, upstream errors, timeouts, and stream reads.
7. [Distributed tasks](distributed-tasks.md): run actual Taskiq Workers/Schedulers and operate project summaries, exports, queues, broadcasts, schedules, results, and duplicate business effects.
8. [Service communication](service-communication.md): start two real Simple receiving services and operate NATS RPC, competing consumers/broadcasts, failures, and RPC from tasks.

The core tutorials use the standalone EPG demo directly, without creating another teaching application. Each chapter identifies source files and excerpt boundaries; see the [Demo example index](demo-examples.md) for more pages. Run in the demo's own environment, without creating business files in the framework source root. To create an empty API from scratch, see [Creating a service](../agents/create-service.md).

## Look up a problem

- Missing configuration files, ungenerated keys, or uninstalled Apps: [Configuration operations](settings-and-apps.md#create-check-and-complete-configurations).
- Different configurations for multiple services: [Services and configuration files](settings-and-apps.md#services-and-configuration-files).
- App-specific settings and IDE completion: [An App's own settings](settings-and-apps.md#an-apps-own-settings).
- Generating versus applying migrations: [Tutorial data preparation](tutorial-tasks.md#3-run-existing-migrations-on-the-first-run).
- Custom and built-in commands: [CLI reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/cli.md).
- Basic UI, dropdowns, Tabs, Slider, Carousel, and charts: [Component usage](components.md).
- Form cleaning, dynamic JSON fields, tags, and remote selection: [Form reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/forms.md).
- Choosing icons and building styles and translations: [Assets reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/assets.md).
- Renaming, adopting external tables, or restoring migration state: [Migration reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/migrations.md).
- Uploading, replacing, and deleting model files: [File storage](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/storage.md).
- Shared caches, named Redis connections, and reading caches across Django and Oldman: [Cache](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/cache.md) and [Providers](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/providers.md).
- Backend external API calls, stream downloads, or NATS RPC: [HTTP client](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/http-client.md) and [NATS](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/providers.md#nats-连接与发布).

- Periodic work, computation processes, and long-lived Workers: [Background work](background-work.md).
- Page messages, the notification center, and realtime data: [Messages and realtime updates](messages-and-live-updates.md).
- Installing the built-in admin site and creating administrators: [Admin](admin.md).
- Preparing production, static assets, and resource cleanup: [Deployment and operations](deployment.md).

Consult the [Developer Reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/README.md) when you need exact signatures or extensions. Use the [Example index](demo-examples.md) to find specific pages, backends, and templates, avoiding copying only the UI while missing data or component initialization.

<!-- source: zh/users/README.md @ 1147cb3f -->
