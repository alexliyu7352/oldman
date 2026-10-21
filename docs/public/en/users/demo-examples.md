# Demo page and source index

This page indexes actual pages in the [EPG Dashboard Demo](https://github.com/alexliyu7352/oldman-epg-dashboard). Follow [Run EPG Dashboard Demo](getting-started.md) to migrate, import data, create an account, build, and start. Paths below are relative to `http://127.0.0.1:17997`; use your own address if the port changes.

These paths are entry points for reading and operating examples, not a claim that every scenario has passed acceptance. Explanatory text does not establish implemented behavior. Advanced Table features explicitly listed as gaps are not completed examples to copy.

## How to compare

1. Open the corresponding page in the browser and operate the item you want to reuse; first distinguish whether it is static display, verification only, or writing to the database.
2. Find the actual Form/Table/Service from the corresponding view, and then find the template. Don't just copy a button.
3. Common components come from shared Dashboard loaders. Only continue to watch `frontend/src/components/examples/` for private actions such as realtime display of tables.
4. After modification, verify it on the same Demo page, and also enter it from other pages through the sidebar to check whether the dynamic mounting is correct.

[views/__init__.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/__init__.py) defines the common example entry point and categories and imports each concrete view module. Do not interpret every URL as a wildcard route rendering only an empty shell.

## Custom App commands

This operation is done in the terminal and there is no need to create another web page. First complete the environment installation, configuration, database migration and `./run.sh web loaddata demo` of [Run EPG Dashboard Demo](getting-started.md); there is no need to build the front end, create a sign-in account or start the Web. Once the database has been prepared, use it directly without repeatedly importing data for statistics.

Run in the Demo root directory:

```sh
./run.sh web --help
./run.sh web project-stats --help
./run.sh web project-stats
./run.sh web project-stats --team-id 1
```

The first command lists `project-stats` under the localized “Dashboard Examples” group. The command outputs total projects and counts grouped by status. `--team-id 1` limits it to team 1; replace it with the actual team ID. Counts come from the current database, rather than hardcoded fixture sizes. Create or edit a project in the [Demo HTML/JSON tables and Modal forms](tutorial-dashboard.md), then rerun to compare totals or status counts. The command neither changes projects, writes caches, nor publishes tasks.

Demo enables `nats_bus` and `taskiq` by default. The existing asynchronous command entry will first connect to the infrastructure in the configuration. Just prepare them according to the Demo README. There is no need to start the NATS receiving service, task Worker or Scheduler. If you do not try out communication and distributed tasks, set both `nats_bus.enabled` and `taskiq.enabled` to false in the local service YAML; the statistics themselves only require the database, and these Redis channels will not be connected because Session/SSE is enabled in the web configuration.

Safely test argument failure with `./run.sh web project-stats --team-id 0`: it should report an invalid argument and exit 2, rather than display zero projects. A nonexistent team explicitly fails with exit 1; only an existing team with no projects displays zero and succeeds. Missing migrations or failed database connections also fail without silently creating tables. Do not delete a database in use to test failure.

The source code is [commands.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/commands.py), and the model is shared with the web page [ExampleProject/ExampleTeam](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/models.py). For registration and complete code description, please see [CLI reference](../developers/cli.md#custom-app-commands). Special inspection is in [test_examples_commands.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/tests/test_examples_commands.py). The test uses its own temporary database.

### Other terminal examples

These commands also come from the Examples App and run in the demo root. `web` selects the current configuration without starting HTTP. Each performs a finite demonstration and exits, without another permanent service. NATS/Taskiq prerequisites when enabled match project-stats above.

| Command | Real work, results and complete description |
| --- | --- |
| `./run.sh web background-stats` | Two real SQL sampling, running/stopped, cancel finally; [Run jobs in the background](background-work.md) |
| `./run.sh web python-process` | A top-level function aggregates projects in a spawn child; error/timeout/cancel scenarios and PID reaping; [Run jobs in the background](background-work.md) |
| `./run.sh web subprocess-demo` | Fixed stdin/stdout, non-zero exit, timeout/cancellation, process group cleanup of external programs; [Run jobs in the background](background-work.md) |
| `./run.sh web worker-demo` | Long-lived Worker actually writing out the project snapshot and confirming the result, and there is an error/stop; [Run jobs in the background](background-work.md) |
| `./run.sh web cache-levels` | Memory/TwoLevel hits and TTL; the local copy stays stale after another process updates Redis; [Cache examples and external HTTP](cache-and-http.md) |
| `./run.sh web django-cache` | Bidirectional reading and writing with the real Django backend; first follow the tutorial to isolate and install optional Django without adding production dependencies; [Cache examples and external HTTP](cache-and-http.md) |
| `./run.sh web image-cache` | Own PNG/WebP, exclusive Storage, hit renewal and next write cleanup; [Cache examples and external HTTP](cache-and-http.md) |
| `./run.sh web cached-stats` | Cache hit and real expiration of the same SQL function; [Cache examples and external HTTP](cache-and-http.md) |

Prepare the database and required Redis alias according to the above detailed tutorial; ImageCache does not check the database. The command only writes its own temporary reports, random cache keys and temporary files. It is responsible for cleaning up when it is finished and does not modify the project records. Error patterns are intended to demonstrate failure, do not treat expected non-zero exits as normal success, and do not create failures in the user's real resources.

## Redis cache

`/examples/cache/redis` uses existing ExampleProject data. The upper buttons read statistics, recompute, and clear one key. An initial miss queries the database; subsequent reads share a 30-second JSON snapshot. Hits neither extend TTL nor query projects. Empty tables show zero projects; GET neither warms statistics nor writes projects.

The same page also has an HTTP response cache. GET `/examples/cache/response` caches the entire JSON action response for 5 seconds. POST to the same path invalidates it; the next read has a new computation time. This is separate from the statistics-value cache above. Authentication precedes language-specific caching, and POST retains CSRF. Do not use caching to bypass permissions.

For the complete operation sequence, shared data boundaries and failure prompts, see [Cache examples and external HTTP](cache-and-http.md). The source codes are [cache_example.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/cache_example.py), [views/cache.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/cache.py) and [cache template directory](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/cache). It reuses the ordinary ExamplesPage, not a new frontend cache component.

## Dynamic configuration

`/examples/config/file` demonstrates `YamlStore`. `ChannelOverrides` declares fields, types, and defaults for `example_channel_overrides.yaml` under the data directory. Opening the page first writes a default file. “Change the channel (get, assign, save)” uses `get()`, assignment, and `save()`; “Set the announcement (update)” uses `update()`. Neither calls `on_file_changed`, so the hook counter stays unchanged. “Edit the announcement in the file, outside the store” replaces the entire file as an editor would. Read again after at most 2 seconds to see the new announcement, an incremented hook counter, and the previously saved channel offset. After “Write a wrong type into the file”, the page keeps the last valid value; the raw file at the right shows the corrupt line, and the service logs an ERROR.

`/examples/config/redis` demonstrates `RedisStore` and `RedisSet`. `SiteFlags` is stored as a whole at `<core.namespace>:store:example_site_flags`, and every read accesses Redis: after “Write the banner from another instance”, the next read sees it. `update()` rejects “Try to save text into the number field”, writing nothing and showing validation errors. The device list below is a Redis set: add, remove, membership, and random selection each use one set command; membership does not read the whole list. The example stores its values under the CACHE alias (`REDIS_ALIAS` in `dynamic_config.py`). Production runtime settings should use Redis without key eviction.

Both pages require sign in and submit with CSRF. The source codes are [dynamic_config.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/dynamic_config.py), [views/config.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/config.py) and [config template directory](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/config); for interface description, see [Configuration reference](../developers/configuration.md#mutable-runtime-configuration).

## Backend HTTP

`/examples/http/client` uses Python MultiHttpClient to call a configurable httpbin upstream. Four buttons demonstrate JSON, upstream 404, timeout, and chunked reads. Only clicks make network requests. No sign-in Cookies or database records are forwarded. Upstream failures remain failures; an upstream 404 is not treated as a missing demo route.

See [Cache examples and external HTTP](cache-and-http.md#running-the-backend-http-example) for operations, third-party access instructions, and error boundaries. The source codes are [http_example.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/http_example.py), [views/http.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/http.py), [App Settings](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/settings.py) and [HTTP Template Directory](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/http). The client is initialized/closed by the real WebService, and the page reuses the ExamplesPage; there is no new background service or HTTP-specific TS.

## Service communication

First follow [Let running services communicate with each other](service-communication.md) to prepare the configuration, database and start nats_a, nats_b and Web respectively. `/examples/communication/rpc` queries the real project data/PID of the specified node and can publish reports; `/examples/communication/events` manually sends competing-consumer/broadcast events and queries the count of two nodes; `/examples/communication/failures` actually displays non-responders, timeouts and receiving exceptions. The event count is only within the receiving process, reset to zero upon restart, and does not create database records.

Source files are apps/examples/nats_messages.py, nats_example.py, views/communication.py, apps/communication/events.py, services/nats_a.py/nats_b.py, and templates/pages/examples/communication/. Pages share ordinary Form/Actions and sign-in/CSRF, operating only fixed targets and business records. project_rpc on `/examples/tasks/results` also calls the same shared RPC function inside a Taskiq execution process, preserving result ownership checks; the browser does not connect directly to NATS.

## Distributed tasks

Follow the [Distributed background tasks](distributed-tasks.md) to configure and start actual Workers/Schedulers separately; Web does not start them. `/examples/tasks/results` demonstrates database summaries, Storage exports, failure, and result queries. `/examples/tasks/schedules` demonstrates due execution, cancellation, fixed/dynamic intervals, and retries. `/examples/tasks/queues` demonstrates concurrency shared by queues, online broadcasts, and duplicate effects with conditional UPDATE.

Sources are [tasks.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/tasks.py), [views/tasks.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tasks.py), [Task Template](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/tasks), services/task_worker.py, and services/task_scheduler.py. Data reuses ExampleProject/ExampleTask without a task history model. GET pages publish no tasks. Result/schedule IDs are checked for current-user ownership first; browser operations are limited to a fixed business allowlist.

## Table and data manipulation

Common source code: [models.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/models.py), [tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/tables.py), [views/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tables.py), [table template directory](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/tables). For a complete explanation, see [Demo HTML/JSON tables and Modal forms](tutorial-dashboard.md).

| Page | What can be operated or checked |
| --- | --- |
| `/examples/tables/static` | First HTML render of real project data; not hardcoded rows |
| `/examples/tables/responsive` | Responsive table layout of the same database |
| `/examples/tables/html`, `/examples/tables/json` | Two formats of the same query; filter, search, paging, sorting, and Modal new/edit/delete |
| `/examples/tables/states` | Initial loading, empty results, errors, permission errors; some states are explicitly constructed by the view, which does not mean that the interface is actually failing |
| `/examples/tables/realtime` | Play back SSE from database samples, mark partial page updates by row ID and column; open the page without adding monitoring records |
| `/examples/tables/advanced` | **Known gaps**: export, pinned headers/columns, column visibility, and bulk actions are not treated as implemented |

For realtime tables, see [realtime-table.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/components/examples/realtime-table.ts) and [services.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/services.py). Database sample playback is a display source, not a background service that actually collects the production server CPU.

## Forms and input

Field declarations are in [forms.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/forms.py), normal submissions are in [views/forms.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/forms.py), and templates are in [forms directory](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/forms).

| Page | Actual use and data boundaries |
| --- | --- |
| `/examples/forms/basics` | Static control, HTML submission, JSON submission are parallel; ordinary fields are only verified and no project is created |
| `/examples/forms/choices`, `/examples/forms/layouts`, `/examples/forms/validation` | Select controls, form layout, field/overall validation; currently these pages use JSON to submit |
| `/examples/forms/date-time`, `/examples/forms/masks` | The date, time and input format are enhanced and are still verified by the backend fields |
| `/examples/forms/sliders` | Slider is linked to form value input, not Carousel for horizontal browsing |
| `/examples/forms/slug`, `/examples/forms/input-spinner`, `/examples/forms/tags` | Two submissions, HTML/JSON, and display the values after server side cleaning; Tags include text separation and multi-selection tags |
| `/examples/forms/color-picker`, `/examples/forms/rich-text` | Control mounting and cleaning in HTML/JSON forms and remote Modal |
| `/examples/forms/multi-step` | Multi-step ExampleProjectForm, both submissions save the real project; not only the next step animation |
| `/examples/forms/json-list` | Create, delete, and edit a variable number of sources; JSONListField converts between a Text field and structured lists, saving ExampleStreamProfile |
| `/examples/forms/selects`, `/examples/forms/autocomplete` | Search the logo from the database, display the picture and name, load in pages, save the selected logo association |
| `/examples/forms/upload` | Shares the Storage upload page's model and save flow |
| `/examples/forms/containers` | Put ordinary Form in different containers, including remote Modal, without setting up another FormModal |

For remote selection, please see [providers.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/providers.py) and [views/data_inputs.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/data_inputs.py). Don't just copy candidate HTML and leave out server-side option validation.

The Rich Text sample receives HTML content; whether to allow publishing and how to handle untrusted content is still determined by the application backend. Successful submission of a normal demo does not mean that the content has been saved to the database or allowed to be publicly rendered.

## Containers, actions and lifecycle

| page | source code and key points |
| --- | --- |
| `/examples/modals/basics`, `/examples/modals/remote` | [views/modals.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/modals.py): ordinary container, remote parts, content changes |
| `/examples/modals/workflows` | Submit steps and replace content within one Modal, remounting the new ordinary Form |
| `/examples/modals/actions` | Five built-in actions, `example_mark` private actions, and explicit demonstration of missing target/unknown action/failure |
| `/examples/navigation/lifecycle`, `/examples/navigation/actions`, `/examples/navigation/loading` | [views/navigation.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/navigation.py), [navigation-probe.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/components/examples/navigation-probe.ts): page switching, loading, and releasing old resources |

The page class is [ExamplesPage](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/pages/examples.ts). Private actions are handled by its `handleResponseAction()`; actions built into the framework still use the shared Runner. Discard old UI work when leaving the page, allowing navigation without waiting for all actions to complete.

## Messages, notifications, identity, and language

| page | source code and key points |
| --- | --- |
| `/examples/messages/page` | [views/messages.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/messages.py): Cookie one-time page prompt, do not write notification center |
| `/examples/messages/feedback` | toast/alert/message, as well as confirm review, prompt rename real project writing; [Dashboard UI and interactive components](components.md#confirmation-and-input-modify-real-projects), not a static success prompt |
| `/examples/notifications/generator`, `/examples/notifications/realtime` | [views/notifications.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/notifications.py): Actively send persistent/temporary notifications; sending will produce actual effects, not a static preview |
| `/examples/notifications/center`, `/user-notifications` | Database notification records and shared notification center of the same user |
| `/examples/auth/login`, `/examples/auth/guards`, `/examples/auth/identity` | [views/auth_session_i18n.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/auth_session_i18n.py): Authentication, permissions, current identity |
| `/examples/session/lifecycle`, `/examples/session/revoke`, `/examples/session/expiry` | Same view module; revoke and expiry buttons change actual Sessions and may require signing in again |
| `/examples/i18n/server`, `/examples/i18n/browser`, `/examples/i18n/coverage` | Server and browser translation, current language coverage; you cannot just change the lang attribute of html |

User SSE routing on the shell is installed by the framework's `AccountFlow` ([apps/accounts/routes.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/accounts/routes.py)), and notifications are initialized in services/web.py; do not create a second dedicated subscription system for notifications.

## Files, charts and drag and drop

| page | source code and key points |
| --- | --- |
| `/examples/storage/upload`, `/examples/storage/lifecycle` | [views/storage.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/storage.py): two file fields, replacement, clear preview, delete record and failure boundary; will change the real file |
| `/examples/storage/api` | services.py of `run_storage_api_demo()`: actually save, open, query and delete file |
| `/examples/sortable/workflow` | [views/sortable.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/sortable.py): Move ExampleTask and persist state and order |
| `/examples/charts/trends`, `/examples/charts/composition`, `/examples/charts/distribution` | [chart_views.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/chart_views.py), [views/charts.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/charts.py): Database aggregation and different chart types |
| `/examples/charts/states` | Loading, empty data, errors, permission status, do not regard demonstration errors as random failures |
| `/examples/charts/realtime` | [realtime-chart.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/components/examples/realtime-chart.ts): SSE update; explicit publish button will write monitoring samples, which is different from read-only table playback |
| `/examples/data-inputs/lists`, `/examples/data-inputs/autocomplete`, `/examples/data-inputs/providers` | dynamic list, remote selection and provider wiring, see the above forms and data_inputs source code |

## UI, plug-ins and icons

The specific HTML of the UI is in [templates/pages/examples/ui/](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/ui), and the entry is in [views/ui.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/ui.py). Don’t guess the URL based on the title alone:

- Visual foundations: `/examples/ui/foundations`, `typography`, `buttons`, `badges-avatars`, `cards`, `lists`.
- Status and content: `/examples/ui/alerts`, `progress-loading`, `timeline`, `images`, `system-states`.
- Interaction: `/examples/ui/carousel`, `tabs-disclosure`, `dropdowns-overlays`, `countdown`, `gallery`, `video`, `navigation-shell`.
- Icons: `/examples/ui/icons`, with source [icons.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/ui/icons.html). See the [Frontend assets, styles, icons, and translation](../developers/assets.md#icons) for library links, usage, and collection rules. The page does not bundle every library icon into production CSS.
- Plug-in index: `/examples/plugins`, not `/examples/plugins/index`.

The short names in the same line above all use the `/examples/ui/` prefix at the beginning. These pages are used to validate shared components and visuals; static cards/buttons should not add database writes or shell components just to be "displayable".

## Rules for documentation examples

User tutorials, the Developer Reference, and Agent Guides take examples from these actual files. Excerpts retain real symbols and routes and explain required imports, initialization, and consumers. Label excerpts explicitly; do not present them as complete standalone files.

If a capability has only a reference interface and no complete demo scenario, state the gap and add a real example before documenting it as runnable. Do not invent a similar interface with the same name or change established demo behavior merely to match documentation.

<!-- source: zh/users/demo-examples.md @ d06f9281 -->
