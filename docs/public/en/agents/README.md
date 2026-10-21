# Agent guide: application development

This directory helps agents develop applications with the current Oldman without earlier conversations. It does not define another framework API or require reading the entire source repository first.

## Start with your task

| Task | Reading and deliverables |
| --- | --- |
| Create an API or background service | [Creating a service](create-service.md): complete configuration, Apps, entry points, and verification with actual requests or commands |
| Add persistent data to a service | [Real demo data, migrations, and queries](../users/tutorial-tasks.md): follow ExampleProject's models, migrations, and transaction wiring |
| Add settings to an App | [Configuration reference](../developers/configuration.md#app-settings): import the App's strongly typed instance directly |
| Add project commands | [CLI reference](../developers/cli.md#custom-app-commands): use the Registry's existing discovery mechanism |
| Handle initialization or import errors | [Applications and lifecycle](../developers/applications.md#actual-loading-order): distinguish configuration, model, and Web phases |
| Develop dashboard CRUD/Modal Forms | [Wiring guide](dashboard-crud.md): cover permissions, the database, both Table formats, responses, and browser verification |
| Add existing UI or field enhancements | [Dashboard UI and interactive components](../users/components.md) and the [Forms, fields, and remote choices](../developers/forms.md): reuse the current loader/Widget |
| Build application styles, icons, and translations | [Frontend assets, styles, icons, and translation](../developers/assets.md): install and build in the application project, without copying framework release artifacts |
| Modify models, prepare fixtures, or integrate files | [Data and files guide](data-and-files.md): check migration scope, transactions, and the file lifecycle |
| Cache data, request upstream services, or use Redis/NATS | [Caching and networking guide (in Chinese)](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/agents/cache-and-network.md): choose existing clients, configure isolation, and manage connections and failures |
| Integrate events/RPC between services | [Let running services communicate with each other](../users/service-communication.md) and [Wiring checklist (in Chinese)](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/agents/cache-and-network.md#nats按真实-demo-接线): follow the receiving App, shared messages, configuration, and actual processes |
| Execute background work or external programs | [Background work guide](background-work.md): choose interfaces by process lifetime, and verify results and shutdown |
| Hand asynchronous work to a durable queue or schedule it | [Taskiq wiring (in Chinese)](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/agents/distributed-tasks.md): follow the demo's configuration, tasks, services, permissions, and actual execution |
| Update Tables with SSE or integrate notifications | [Realtime page guide (in Chinese)](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/agents/realtime.md): reuse stable DOM, request permissions, user connections, and persistent notification APIs |
| Integrate an admin site or extend ModelAdmin | [Admin guide (in Chinese)](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/agents/admin.md): distinguish App registration, model administration, and route installation |
| Prepare application deployment | [Deployment and Operations](../users/deployment.md) and [Security boundaries and rate limiting](../developers/security.md): check actual dependencies, permissions, and cleanup responsibilities |
| Maintain the framework and verify release artifacts | [Source development, verification, and releases](../developers/maintenance.md) and [Test isolation requirements](../developers/testing.md): keep these separate from application development tasks |

## Establish only the necessary facts before starting

Determine whether you are working in an application repository or the framework repository. Check Git status, the project's `pyproject.toml`, `services/`, and the service YAML. Do not write business code into the installed `oldman` package.

For existing applications, prefer existing services, Apps, tables, and public components. Check whether something already exists before creating it. Implement the capability the user requested, without changing other modules along the way.

When you need examples, check the [Demo page and source index](../users/demo-examples.md) first. Use real class names, routes, and DOM markers, and explain excerpt dependencies. Do not invent another teaching application. If the demo has no runnable scenario yet, report the gap first. Assembling code from reference interfaces alone does not establish that it has been verified in the demo.

Actual choices for the user include the service's purpose, whether access is public, the database, which Apps to install, and the data scope of interfaces. Users fill in passwords and connection details in runtime configuration; do not include them in example commits.

## Fixed facts that do not depend on past context

- The Python package is `oldman`; the browser package is `oldman-web`. Ordinary APIs and background services do not need a frontend build for this.
- The service name comes from `services/<name>.py`; its default configuration is `data/<name>_settings.yaml`.
- Each service process has one root Settings instance; the project defines one root Settings type.
- `settings.apps` is an explicit list of package paths. Each package's `apps.py` exports a single `app` object.
- App Settings are read from `app.settings`; they do not dynamically become attributes of the global Settings.
- `bootstrap_service()` handles unified configuration and model initialization. Do not add a second setup mechanism or start services automatically on module import.
- Models are declared during the Registry's model phase. Business views and commands can import loaded models, but must not declare tables in their own modules.
- Database structure is managed through project-level `oldman db ...` commands. Starting a service does not run migrations automatically.
- Server implementations of templates, forms, and Tables belong to `oldman.web`; browser interactions belong to `oldman-web`. Admin and dashboard do not maintain separate public implementations.

## Minimum delivery checklist

1. List added or changed application files. Helpers in code must either be defined in the example or use real public imports.
2. Explain App registration, configuration completion, and preparation of required data. Creating a subclass without a loading entry point is incomplete.
3. Run the commands or requests needed for the current task. Check real results and one representative failure path; do not run full-project gates for a small feature.
4. Explain when writes commit, who handles exceptions, and who closes connections or background tasks.
5. Use a real browser for frontend interactions. Source string assertions do not constitute visual acceptance.
6. Preserve user changes. Do not commit secrets, databases, virtual environments, dependency directories, or temporary files for this task.

These rules do not authorize deleting user data, resetting the workspace, or starting sub-agents. Changes in the framework repository must also follow that repository's contribution rules.

<!-- source: zh/agents/README.md @ 8079563f -->
