# Oldman public API index

Generated from the source of this version by `scripts/api_index.py`; do not edit by hand.

A name is public when a package or module listed here exports it in `__all__`; import it from that
package or module exactly as its page shows. Anything not listed is internal and may change without
notice. Open a page for signatures, docstring summaries and class members.

| Package | Names | Summary |
| --- | --- | --- |
| [`oldman`](oldman.md) | 2 | @author:alex |
| [`oldman.apps`](oldman.apps.md) | 5 | @author:alex |
| [`oldman.apps.admin`](oldman.apps.admin.md) | 20 | Built-in Admin application. |
| [`oldman.apps.roles`](oldman.apps.roles.md) | 12 | Roles: named sets of permissions that users hold. |
| [`oldman.auth`](oldman.auth.md) | 59 | Framework authentication models and identity services. |
| [`oldman.cache`](oldman.cache.md) | 15 | Native cache contracts. |
| [`oldman.cache.backends`](oldman.cache.backends.md) | 5 |  |
| [`oldman.cli`](oldman.cli.md) | 35 | Lazy public entry point for the Oldman command line. |
| [`oldman.cli.tui`](oldman.cli.tui.md) | 25 | Terminal interaction for Oldman commands and ops tools. |
| [`oldman.conf`](oldman.conf.md) | 51 | Application settings bootstrap and public configuration API. |
| [`oldman.contrib.http`](oldman.contrib.http.md) | 16 | @author:alex |
| [`oldman.contrib.http.backends`](oldman.contrib.http.backends.md) | 3 | HTTP客户端后端实现 |
| [`oldman.contrib.proxy`](oldman.contrib.proxy.md) | 7 | @author:alex |
| [`oldman.db`](oldman.db.md) | 22 | Public database models and lazy sessions; deployments use migrations. |
| [`oldman.db.sqlalchemy`](oldman.db.sqlalchemy.md) | 6 | @author:alex |
| [`oldman.i18n`](oldman.i18n.md) | 30 | Runtime-independent internationalization API. |
| [`oldman.logging`](oldman.logging.md) | 19 | Stable public logging API for Oldman applications. |
| [`oldman.mail`](oldman.mail.md) | 18 | Outgoing mail: django.core.mail's shape, async, on the stdlib email package and aiosmtplib. |
| [`oldman.mail.backends`](oldman.mail.backends.md) | 6 | Built-in outgoing mail backends. |
| [`oldman.ops`](oldman.ops.md) | 10 | Building blocks for server maintenance and deployment tools. |
| [`oldman.processes`](oldman.processes.md) | 12 | Process execution primitives with explicit lifecycle ownership. |
| [`oldman.providers.nats`](oldman.providers.nats.md) | 6 | @author:alex |
| [`oldman.providers.redis`](oldman.providers.redis.md) | 7 | Async Redis provider core. |
| [`oldman.runtime`](oldman.runtime.md) | 16 | Lazy public exports for service discovery, bootstrap, and runtimes. |
| [`oldman.security`](oldman.security.md) | 6 | Framework-independent security primitives. |
| [`oldman.security.rate_limiter`](oldman.security.rate_limiter.md) | 2 | Framework-independent rate-limiting policies. |
| [`oldman.serializers`](oldman.serializers.md) | 9 | @author:alex |
| [`oldman.storage`](oldman.storage.md) | 26 | Public async storage API. |
| [`oldman.storage.backends`](oldman.storage.backends.md) | 2 |  |
| [`oldman.tasks`](oldman.tasks.md) | 8 | @author:alex |
| [`oldman.tasks.distributed`](oldman.tasks.distributed.md) | 2 | Native task declaration and scheduling objects for the configured process. |
| [`oldman.testing`](oldman.testing.md) | 55 | 本地校验门禁用的测试工具：真实浏览器、进程树、PNG 证据。 |
| [`oldman.utils`](oldman.utils.md) | 14 | @author:alex |
| [`oldman.web`](oldman.web.md) | 45 | Lightweight public Web primitives for Oldman applications. |
| [`oldman.web.api`](oldman.web.api.md) | 24 | Public browser response protocol. |
| [`oldman.web.auth`](oldman.web.auth.md) | 67 | Public Web authentication adapters. |
| [`oldman.web.authentication`](oldman.web.authentication.md) | 39 | Request authentication: who is calling, and how they proved it. |
| [`oldman.web.components`](oldman.web.components.md) | 5 | @author:alex |
| [`oldman.web.components.charts`](oldman.web.components.charts.md) | 11 | 后端 Chart 组件封装入口。 |
| [`oldman.web.components.forms`](oldman.web.components.forms.md) | 46 | 后端 Form 组件包入口。 |
| [`oldman.web.components.selects`](oldman.web.components.selects.md) | 13 | Oldman 后端 Select/Autocomplete 组件入口。 |
| [`oldman.web.components.tables`](oldman.web.components.tables.md) | 26 | Oldman 后端 Table 组件入口。 |
| [`oldman.web.i18n`](oldman.web.i18n.md) | 22 | Web internationalization service. |
| [`oldman.web.messages`](oldman.web.messages.md) | 16 | Public browser user-message APIs. |
| [`oldman.web.messages.notifications`](oldman.web.messages.notifications.md) | 20 | Public strong types for persistent and realtime user notifications. |
| [`oldman.web.middlewares`](oldman.web.middlewares.md) | 6 | Web middleware entry points. |
| [`oldman.web.security`](oldman.web.security.md) | 13 | Web-facing fingerprint security helpers. |
| [`oldman.web.security.csrf`](oldman.web.security.csrf.md) | 7 | @author:alex |
| [`oldman.web.security.rate_limiter`](oldman.web.security.rate_limiter.md) | 7 | HTTP path and browser-fingerprint rate-limiting policies. |
| [`oldman.web.session`](oldman.web.session.md) | 5 | Public Web session extension and typed request accessor. |
| [`oldman.web.sse`](oldman.web.sse.md) | 18 | Server-Sent Events support. |
| [`oldman.web.staticfiles`](oldman.web.staticfiles.md) | 19 | Static asset bundle registry. |
| [`oldman.web.template`](oldman.web.template.md) | 15 | Template integration. |
| [`oldman.web.websocket`](oldman.web.websocket.md) | 2 | WebSocket routing and connection protocol. |
