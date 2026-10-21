# Oldman documentation

This documentation covers the current `oldman` and `oldman-web`: what they are, how to use them, and how to extend them. The examples require no knowledge of the framework's development history.

## Choose a starting point

| What you want to do | Start here |
| --- | --- |
| Build your first project with Oldman | [User guide](users/README.md) |
| Look up interfaces or loading order, or write extensions | [Developer reference](developers/README.md) |
| Have an agent develop an application from requirements | [Agent guide: application development](agents/README.md) |

## Common questions

- How do I run the complete example first? Read [Run EPG Dashboard Demo](users/getting-started.md). To create an empty API from scratch, see [Creating a service](agents/create-service.md).
- Where does the data on a page come from? Read [Real demo data, migrations, and queries](users/tutorial-tasks.md).
- How do sign-in, tables, and edit modals connect? Follow the [Demo HTML/JSON tables and Modal forms](users/tutorial-dashboard.md).
- Which files should I read to reuse an existing feature? See the [Demo page and source index](users/demo-examples.md).
- How do I use the UI, icons, and interactions directly? Read [Dashboard UI and interactive components](users/components.md) and the [Frontend assets, styles, icons, and translation](developers/assets.md).
- What is the difference between `services`, Apps, and configuration files? Read [Settings, Apps, and services](users/settings-and-apps.md).
- Why does importing `settings` too early raise an error? See the [Configuration reference](developers/configuration.md).
- When are models, commands, and views loaded? See [Applications and lifecycle](developers/applications.md).
- How do I add commands to an App? See the [CLI reference](developers/cli.md#custom-app-commands).
- How do I register my own request or response middleware? See [Web requests, templates, and permissions](developers/web.md#custom-middleware).
- How does the IDE's Python Shell load the application? See [Applications and lifecycle](developers/applications.md#python-shell-and-ide).
- How do I manage models directly with the built-in Admin? Read the [Run and understand the Admin Demo](users/admin.md).
- How do I manage connections and failures when caching results or calling upstream APIs? Read [Cache examples and external HTTP](users/cache-and-http.md).
- How do I run and stop local coroutines, short-lived processes, and long-lived Workers? Read the [Run jobs in the background](users/background-work.md).
- How do I queue work durably, query task results, or schedule execution? Read the [Distributed background tasks](users/distributed-tasks.md).
- How do two background services send events and make RPC calls? Read [Let running services communicate with each other](users/service-communication.md).
- How do I deploy and check resource cleanup? Read the [Deployment and Operations](users/deployment.md).
- How do I maintain, test, and package the framework? Read [Source development, verification, and releases](developers/maintenance.md).

## Conventions for reading examples

Commands run in the root of the referenced demo unless stated otherwise; a `cd` command indicates when to change directories. The core tutorials use the demo's actual code and routes. Code marked as an excerpt depends on imports and initialization in the original file; it is not another standalone program. Source links let you compare the complete implementation; they do not replace instructions for running it or handling failures.

`./run.sh` is a convenience entry point in generated projects, with the same arguments as `oldman`. Service names in commands come from actual `services/<name>.py` files, rather than arbitrary aliases.

The API reference defines interfaces; tutorials and Agent Guides connect them. Links refer to the same reference, without describing the same API with a different set of parameters or behavior.

<!-- source: zh/README.md @ 1147cb3f -->
