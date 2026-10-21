# Demo page and source index

This page indexes actual pages in the [EPG Dashboard Demo](https://github.com/alexliyu7352/oldman-epg-dashboard). Follow [Run the EPG dashboard demo](getting-started.md) to migrate the database, import data, create an account, build the frontend, and start the service. Paths below are relative to `http://127.0.0.1:17997`; use your own address if you change the port.

These paths are entry points for reading and trying examples, rather than a claim that every scenario has passed acceptance. Descriptions on a page do not establish that its features are implemented. Advanced Table features explicitly listed as gaps are not complete examples to copy.

## How to compare

1. Open the corresponding page in a browser and try the feature you want to reuse. First establish whether it displays static content, only validates input, or writes to the database.
2. Follow the view to the actual Form, Table, or Service, then find its template. Do not copy only a button.
3. Ordinary components come from shared Dashboard loaders. Inspect `frontend/src/components/examples/` only for private behavior such as realtime table display.
4. After making changes, verify them on the same demo page. Also navigate there from another page through the sidebar to check dynamic mounting.

[`views/__init__.py`](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/__init__.py) defines the common example entry point and categories and imports each concrete view module. Do not interpret every URL as a wildcard route that renders only an empty shell.

## Custom App commands

This example runs in the terminal and has no separate web page. First follow [Run the EPG dashboard demo](getting-started.md) to install the environment, prepare configuration, migrate the database, and run `./run.sh web loaddata demo`. You do not need to build the frontend, create a sign-in account, or start the Web service. If the database is already prepared, use it as it is; do not reimport data just to run statistics.

Run in the demo root directory:

```sh
./run.sh web --help
./run.sh web project-stats --help
./run.sh web project-stats
./run.sh web project-stats --team-id 1
```

The first command lists `project-stats` under the localized “Dashboard Examples” group. The statistics command outputs the total number of projects and counts by status. `--team-id 1` limits the query to team 1; replace it with the actual team ID you want to query. Counts come from the current database, rather than hardcoded fixture sizes. Create or edit a project in [the project table](tutorial-dashboard.md), then rerun the command to compare totals or status counts. The command does not change projects, write caches, or submit tasks.

The demo enables `nats_bus` and `taskiq` by default, so the existing asynchronous command entry point first connects to the configured infrastructure. Prepare it as described in the demo README; you do not need to start the NATS receiving service, task Worker, or Scheduler. If you are not trying communication or distributed tasks, set both `nats_bus.enabled` and `taskiq.enabled` to false in the local service YAML. The statistics command itself needs only the database; enabling Session or SSE in the Web settings does not make it connect to those Redis channels.

To safely test invalid arguments, run `./run.sh web project-stats --team-id 0`. It should report an invalid argument and exit with code 2, rather than display zero projects. A nonexistent team produces an explicit error and exit code 1. Only an existing team with no projects displays zero and exits successfully. Missing migrations or database connection failures also produce errors and a failed exit, without silently creating tables. Do not delete a database in use to test failure.

The command is implemented in [commands.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/commands.py) and shares the [ExampleProject/ExampleTeam](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/models.py) models with the web pages. See [CLI reference](../developers/cli.md#custom-app-commands) for registration and the complete code explanation. Dedicated checks are in [test_examples_commands.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/tests/test_examples_commands.py) and use their own temporary database.

### Other terminal examples

These commands also come from the Examples App and run in the demo root. `web` selects the current configuration without starting an HTTP service. Each command runs a finite demonstration and exits; none requires another persistent service. When NATS or Taskiq is enabled, the prerequisites are the same as for project-stats above.

| Command | Actual behavior, results, and full instructions |
| --- | --- |
| `./run.sh web background-stats` | Takes two real SQL samples, shows running and stopped states, and demonstrates cancellation cleanup in `finally`. See [background work](background-work.md). |
| `./run.sh web python-process` | Aggregates projects through a top-level function in a spawn child process. Also demonstrates error, timeout, and cancellation modes and reaping the child PID. See [background work](background-work.md). |
| `./run.sh web subprocess-demo` | Runs a fixed external program with stdin and stdout, demonstrating nonzero exit, timeout, cancellation, and process-group cleanup. See [background work](background-work.md). |
| `./run.sh web worker-demo` | Uses a long-lived Worker to write a project snapshot and confirm the result. Also provides error and stop modes. See [background work](background-work.md). |
| `./run.sh web cache-levels` | Demonstrates Memory and TwoLevel cache hits and TTL, including a local copy remaining stale after another process updates Redis. See [the cache tutorial](cache-and-http.md). |
| `./run.sh web django-cache` | Reads and writes in both directions through a real Django backend. First follow [the cache tutorial](cache-and-http.md) to install optional Django in isolation, without adding it to production dependencies. |
| `./run.sh web image-cache` | Uses its own PNG and WebP images and exclusive Storage, demonstrating expiry renewal on hits and cleanup on the next write. See [the cache tutorial](cache-and-http.md). |
| `./run.sh web cached-stats` | Demonstrates cache hits and actual expiry for the same SQL function. See [the cache tutorial](cache-and-http.md). |

Follow the detailed tutorials above to prepare the database and required Redis aliases; ImageCache does not query the database. Commands write only their own temporary reports, random cache keys, and temporary files, and clean them up when finished. They do not modify project records. Error modes deliberately demonstrate failure: do not treat their expected nonzero exits as successful completion, or create failures in the user's real resources.

## Redis cache

`/examples/cache/redis` uses existing ExampleProject data. The upper buttons read statistics, recompute, and clear one key. An initial miss queries the database; subsequent reads share a 30-second JSON snapshot. Hits neither extend TTL nor query projects. Empty tables show zero projects; GET neither warms statistics nor writes projects.

The same page also has an HTTP response cache. GET `/examples/cache/response` caches the entire JSON action response for 5 seconds. POST to the same path invalidates it; the next read has a new computation time. This is separate from the statistics-value cache above. Authentication precedes language-specific caching, and POST retains CSRF. Do not use caching to bypass permissions.

See [the cache tutorial](cache-and-http.md) for the complete operation sequence, shared-data boundaries, and failure messages. Source files are [cache_example.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/cache_example.py), [views/cache.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/cache.py), and the [cache template directory](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/cache). The page reuses the ordinary ExamplesPage rather than introducing a frontend cache component.

## Dynamic configuration

`/examples/config/file` demonstrates `YamlStore`. `ChannelOverrides` declares fields, types, and defaults for `example_channel_overrides.yaml` under the data directory. Opening the page first writes a default file. “Change the channel (get, assign, save)” uses `get()`, assignment, and `save()`; “Set the announcement (update)” uses `update()`. Neither calls `on_file_changed`, so the hook counter stays unchanged. “Edit the announcement in the file, outside the store” replaces the entire file as an editor would. Read again after at most 2 seconds to see the new announcement, an incremented hook counter, and the previously saved channel offset. After “Write a wrong type into the file”, the page keeps the last valid value; the raw file at the right shows the corrupt line, and the service logs an ERROR.

`/examples/config/redis` demonstrates `RedisStore` and `RedisSet`. `SiteFlags` is stored as a whole at `<core.namespace>:store:example_site_flags`, and every read accesses Redis: after “Write the banner from another instance”, the next read sees it. `update()` rejects “Try to save text into the number field”, writing nothing and showing validation errors. The device list below is a Redis set: add, remove, membership, and random selection each use one set command; membership does not read the whole list. The example stores its values under the CACHE alias (`REDIS_ALIAS` in `dynamic_config.py`). Production runtime settings should use Redis without key eviction.

Both pages require sign-in and submit with CSRF protection. Source files are [dynamic_config.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/dynamic_config.py), [views/config.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/config.py), and the [config template directory](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/config); see [the developer reference](../developers/configuration.md#mutable-runtime-configuration) for the interfaces.

## Backend HTTP

`/examples/http/client` uses Python MultiHttpClient to call a configurable httpbin upstream. Four buttons demonstrate JSON, upstream 404, timeout, and chunked reads. Only clicks make network requests. No sign-in Cookies or database records are forwarded. Upstream failures remain failures; an upstream 404 is not treated as a missing demo route.

See [the HTTP tutorial](cache-and-http.md#running-the-backend-http-example) for operations, third-party access, and error boundaries. Source files are [http_example.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/http_example.py), [views/http.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/http.py), [App settings](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/settings.py), and the [HTTP template directory](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/http). The actual WebService initializes and closes the client, and the page reuses ExamplesPage. There is no new background service or HTTP-specific TypeScript.

## Service communication

First follow [Let running services communicate with each other](service-communication.md) to prepare configuration and the database, then start nats_a, nats_b, and Web separately. `/examples/communication/rpc` queries real project data and the PID from the specified node and can publish reports. `/examples/communication/events` manually sends competing-consumer and broadcast events and queries counts from two nodes. `/examples/communication/failures` demonstrates no responders, timeouts, and receiver exceptions. Event counts live only in the receiving process, reset to zero on restart, and create no database records.

Source files are apps/examples/nats_messages.py, nats_example.py, views/communication.py, apps/communication/events.py, services/nats_a.py and services/nats_b.py, and templates/pages/examples/communication/. Pages share ordinary Forms and Actions, sign-in, and CSRF protection, and operate only on fixed targets and business records. The project_rpc example on `/examples/tasks/results` also calls the same shared RPC function from a Taskiq execution process, retaining the existing result-ownership checks. Browsers do not connect directly to NATS.

## Distributed tasks

First follow [Distributed background tasks](distributed-tasks.md) to configure and start the actual Workers and Schedulers separately; Web does not start them. `/examples/tasks/results` demonstrates database summaries, Storage exports, failures, and result queries. `/examples/tasks/schedules` demonstrates execution when due, cancellation, fixed and dynamic intervals, and retries. `/examples/tasks/queues` demonstrates concurrency shared by queues, online broadcasts, and duplicate effects with conditional UPDATE.

Source files are [tasks.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/tasks.py), [views/tasks.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tasks.py), the [task templates](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/tasks), services/task_worker.py, and services/task_scheduler.py. The examples reuse ExampleProject and ExampleTask without adding a task-history model. GET requests do not submit tasks. Result and schedule IDs are checked against the current user's ownership first; browsers can invoke only fixed, allowlisted business operations.

## Table and data manipulation

Common source code: [models.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/models.py), [tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/tables.py), [views/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tables.py), [table template directory](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/tables). For a complete explanation, see [Demo HTML/JSON tables and Modal forms](tutorial-dashboard.md).

| Page | What can be operated or checked |
| --- | --- |
| `/examples/tables/static` | First HTML render of real project data; not hardcoded rows |
| `/examples/tables/responsive` | Responsive table layout of the same database |
| `/examples/tables/html`, `/examples/tables/json` | Presents the same query in two formats, with filtering, search, pagination, sorting, and Modal creation, editing, and deletion. |
| `/examples/tables/states` | Displays initial loading, empty results, errors, and permission errors. Some states are explicitly constructed by the view and do not indicate an actual endpoint failure. |
| `/examples/tables/realtime` | Replays database samples through SSE and applies partial page updates using row IDs and column markers. Opening the page adds no monitoring records. |
| `/examples/tables/advanced` | **Known gaps**: export, pinned headers/columns, column visibility, and bulk actions are not treated as implemented |

For realtime tables, also read [realtime-table.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/components/examples/realtime-table.ts) and [services.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/services.py). The display replays database samples; it is not a background service collecting actual CPU metrics from a production server.

## Forms and input

Field declarations are in [forms.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/forms.py), normal submissions are in [views/forms.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/forms.py), and templates are in [forms directory](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/forms).

| Page | Actual use and data boundaries |
| --- | --- |
| `/examples/forms/basics` | Shows static controls alongside HTML and JSON submissions. Ordinary fields are validated without creating a project. |
| `/examples/forms/choices`, `/examples/forms/layouts`, `/examples/forms/validation` | Demonstrates selection controls, form layout, and field-level and whole-form validation. These pages currently submit JSON. |
| `/examples/forms/date-time`, `/examples/forms/masks` | Enhances date, time, and input formatting while retaining backend field validation. |
| `/examples/forms/sliders` | Links a Slider to numeric form input; this is not a Carousel for horizontal browsing. |
| `/examples/forms/slug`, `/examples/forms/input-spinner`, `/examples/forms/tags` | Supports both HTML and JSON submission and displays values after server-side cleaning. Tags covers both delimited text and multiple-selection tags. |
| `/examples/forms/color-picker`, `/examples/forms/rich-text` | Mounts and cleans up controls in HTML and JSON forms and remote Modals. |
| `/examples/forms/multi-step` | Uses a multi-step ExampleProjectForm; both submission formats save a real project, beyond animating a move to the next step. |
| `/examples/forms/json-list` | Adds, removes, and edits a variable number of sources. JSONListField converts between a Text field and structured lists, saving ExampleStreamProfile. |
| `/examples/forms/selects`, `/examples/forms/autocomplete` | Searches logos in the database, displays images and names with paginated loading, and saves the selected logo association. |
| `/examples/forms/upload` | Shares the Storage upload page's model and save flow |
| `/examples/forms/containers` | Places an ordinary Form in different containers, including a remote Modal, without introducing another FormModal. |

For remote selection, also read [providers.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/providers.py) and [views/data_inputs.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/data_inputs.py). Do not copy only the candidate HTML and omit server-side option validation.

The Rich Text example accepts HTML content. The application backend still decides whether publication is allowed and how to handle untrusted content. Successful submission in an ordinary demo does not establish that the content was saved to the database or was approved for public rendering.

## Containers, actions and lifecycle

| Page | Source and key points |
| --- | --- |
| `/examples/modals/basics`, `/examples/modals/remote` | [views/modals.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/modals.py): demonstrates ordinary containers, remote parts, and content changes. |
| `/examples/modals/workflows` | Submits steps and replaces content within one Modal, remounting the new ordinary Form. |
| `/examples/modals/actions` | Demonstrates five built-in actions and the private `example_mark` action, including explicit cases of missing targets, unknown actions, and failure midway through execution. |
| `/examples/navigation/lifecycle`, `/examples/navigation/actions`, `/examples/navigation/loading` | [views/navigation.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/navigation.py), [navigation-probe.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/components/examples/navigation-probe.ts): page switching, loading, and releasing old resources |

The page class is [ExamplesPage](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/pages/examples.ts). Private actions are handled by its `handleResponseAction()`; actions built into the framework still use the shared Runner. Discard old UI work when leaving the page, allowing navigation without waiting for all actions to complete.

## Messages, notifications, identity, and language

| Page | Source and key points |
| --- | --- |
| `/examples/messages/page` | [views/messages.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/messages.py): shows one-time page messages in Cookies, without writing to the notification center. |
| `/examples/messages/feedback` | Demonstrates toast, alert, and message fallbacks, plus real project updates through confirm for review and prompt for renaming. See [operation and failure boundaries](components.md#confirmation-and-input-modify-real-projects); these are not static success messages. |
| `/examples/notifications/generator`, `/examples/notifications/realtime` | [views/notifications.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/notifications.py): sends persistent and temporary notifications. Sending has actual effects rather than displaying a static preview. |
| `/examples/notifications/center`, `/user-notifications` | Shows the same user's database notification records and shared notification center. |
| `/examples/auth/login`, `/examples/auth/guards`, `/examples/auth/identity` | [views/auth_session_i18n.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/auth_session_i18n.py): Authentication, permissions, current identity |
| `/examples/session/lifecycle`, `/examples/session/revoke`, `/examples/session/expiry` | Uses the same view module. Revocation and expiry buttons change real Sessions, so you may need to sign in again afterwards. |
| `/examples/i18n/server`, `/examples/i18n/browser`, `/examples/i18n/coverage` | Demonstrates server and browser translations and current language coverage. Changing only the html lang attribute is insufficient. |

The framework's `AccountFlow` installs the shell's user SSE routes ([apps/accounts/routes.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/accounts/routes.py)); services/web.py initializes notifications. Do not create another dedicated notification subscription system.

## Files, charts and drag and drop

| Page | Source and key points |
| --- | --- |
| `/examples/storage/upload`, `/examples/storage/lifecycle` | [views/storage.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/storage.py): demonstrates two file fields, replacement, clearing a preview, record deletion, and failure boundaries. These operations change real files. |
| `/examples/storage/api` | Calls `run_storage_api_demo()` in services.py to actually save, open, query, and delete files. |
| `/examples/sortable/workflow` | [views/sortable.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/sortable.py): moves ExampleTask and persists its state and order. |
| `/examples/charts/trends`, `/examples/charts/composition`, `/examples/charts/distribution` | [chart_views.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/chart_views.py), [views/charts.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/charts.py): Database aggregation and different chart types |
| `/examples/charts/states` | Displays loading, empty data, errors, and permission states. Deliberate demonstration errors do not indicate random failures. |
| `/examples/charts/realtime` | [realtime-chart.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/components/examples/realtime-chart.ts): updates through SSE. The explicit publish button writes monitoring samples, unlike read-only table playback. |
| `/examples/data-inputs/lists`, `/examples/data-inputs/autocomplete`, `/examples/data-inputs/providers` | Demonstrates dynamic lists, remote selection, and provider wiring. See the forms and data_inputs source files above. |

## UI, plug-ins and icons

The UI's HTML is in [templates/pages/examples/ui/](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/ui), with entry points in [views/ui.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/ui.py). Do not guess URLs from titles alone:

- Visual foundations: `/examples/ui/foundations`, `typography`, `buttons`, `badges-avatars`, `cards`, `lists`.
- Status and content: `/examples/ui/alerts`, `progress-loading`, `timeline`, `images`, `system-states`.
- Interaction: `/examples/ui/carousel`, `tabs-disclosure`, `dropdowns-overlays`, `countdown`, `gallery`, `video`, `navigation-shell`.
- Icons: `/examples/ui/icons`, with source [icons.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/ui/icons.html). See [the assets reference](../developers/assets.md#icons) for library links, usage, and collection rules. The page does not bundle every library icon into production CSS.
- Plug-in index: `/examples/plugins`, not `/examples/plugins/index`.

Short names on each line above use the `/examples/ui/` prefix shown at the beginning of that line. These pages validate shared components and visuals. Static Cards and buttons should not require database writes or empty shell components merely to be displayed.

## Rules for documentation examples

User tutorials, the Developer Reference, and Agent Guides take examples from these actual files. Excerpts retain real symbols and routes and explain required imports, initialization, and consumers. Label excerpts explicitly; do not present them as complete standalone files.

If a capability has only a reference interface and no complete demo scenario, state the gap and add a real example before documenting it as runnable. Do not invent a similar interface with the same name or change established demo behavior merely to match documentation.

<!-- source: zh/users/demo-examples.md @ d06f9281 -->
