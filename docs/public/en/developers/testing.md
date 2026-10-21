# Test isolation requirements

This chapter constrains testing/verification environments without adding production APIs. Services still run with one process, one root configuration, and one set of Apps/models. Test convenience does not justify changing that model.

## Choose isolation by the tested boundary

| Test target | Suitable environment |
| --- | --- |
| Pure functions, serialization, unconfigured objects | Ordinary unit tests with explicit inputs |
| Functions reading current settings | Temporarily bind global settings within tests, restore afterwards, and check actual behavior |
| Settings, App Registry, model loading, service discovery | Complete temporary project plus separate Python process |
| Transactions, foreign keys, file cleanup | Separate database/Storage directories with actual flush/commit/rollback |
| Redis/NATS cross-process semantics | Task-owned instances or explicitly isolated resources with actual publishing/reading |
| UI, building, installation | Isolated application, actual artifacts, browser interaction, and data results |

Existing tests/test_oldman_service_bootstrap.py demonstrates temporary projects/subprocesses. Reuse this boundary rather than making it a new application-runtime configuration protocol.

## Configuration and imports

- Do not read conf.settings or unbound app.settings before bootstrap. Startup tests should verify actual-entry initialization.
- One process must not switch between api/web service configurations. Compare services in separate processes without production reset/configuration proxies.
- Narrow unit tests directly binding settings must automatically restore original values even after assertion failure. Do not attach fake settings to app.ctx.settings.
- Actual App/model loading affects sys.modules and SQLAlchemy metadata. Clearing only registry dictionaries does not reset complete bootstrap state.
- For independent project packages, service files, or model ownership, subprocess cwd must be the temporary project root. Do not write temporary config packages at framework root.

Tests may patch external I/O to trigger precise exceptions, but patched database/Redis behavior does not establish correct cross-process/transaction semantics. Distinguish actual integration verification explicitly.

## Resources and failure paths

Retain handles for test-created processes; stop/await them in finally. Close browser profiles and shut down databases, pools, and background tasks normally. Do not kill user services in bulk by process name.

Use TemporaryDirectory or mktemp -d for temporary directories, track ownership, and delete only this task's directories. Release tools' persistent evidence requires explicit cleanup; see [Source development, verification, and releases](maintenance.md#full-verification-in-serial-stages).

Failure tests should at least verify what did not happen: invalid input wrote no data, rollback retained original files, unauthorized requests read no other users' data, failed actions stopped later actions, etc. An error-message assertion alone is insufficient.

Real UI changes require manual operation. DOM/source assertions assist protocol checks but cannot prove visible layouts, Modal dimensions, clicks, or loading-failure feedback. Dashboard/Admin must use the same public component protocols.

## Limit verification scope

After a small module, run only checks required to continue safely. Centralize remaining full release checks and execute serially. Do not create duplicated state, permanent screenshot caches, or elaborate test-only production branches just for green checks.

For outdated expectations, check current contracts/behavior before correcting or deleting tests. Do not restore removed interfaces to satisfy old assertions or use historical internal wording as production-correctness gates.

## Real-service checks

Redis/NATS/Taskiq checks in the Python gate (pnpm verify:python) start their own service processes and require two executables:

| Program | Discovery | Requirement |
| --- | --- | --- |
| redis-server | REDIS_SERVER environment variable, otherwise PATH | 6.2 or newer; taskiq-redis uses GETDEL for results/schedules |
| nats-server | NATS_SERVER environment variable, otherwise PATH | JetStream support (-js) |

Missing executables or Redis below 6.2 fail relevant checks with configuration instructions rather than skipping. Skips would appear successful without actual verification.
Discovery lives in require_redis_server() in tests/redis_support.py and require_nats_server() in tests/nats_support.py. New real-service tests reuse them rather than skipUnless. They only locate executables; each check starts its own service on its own port/Unix socket, never connecting to running Redis/NATS.
Only two checks still skip: NATS credentials require NATS_TEST_CREDS_DIR pointing to nats.py repository public nkeys examples; Django cache interoperability requires installed Django.

## Browser and process gate tools

Real-browser verification, process-tree cleanup, and PNG evidence checking live in oldman.testing, using only the standard library and reading no configuration/starting no services at import:

| Entry point | Purpose |
| --- | --- |
| ChromePage / CDPClient / navigate / configure_viewport / save_screenshot | Opens pages, screenshots, and client.evaluate(...) assertions through local Chrome DevTools Protocol |
| BrowserResult | Collects console/page errors and bad responses separately from business assertions |
| find_free_port | Finds an available temporary-service port |
| tracked_popen / ProcessTreeTracker | Starts subprocesses and confirms whole-tree exit afterwards |
| require_png | Confirms a screenshot is a sufficiently large PNG, not an empty file |

Use oldman.testing.gates for completely owned temporary environments that avoid running development services/data:

| Entry point | Purpose |
| --- | --- |
| minimal_environment() | Keeps only local-tool startup environment, fixing TZ=UTC and PYTHONHASHSEED=0 |
| owned_redis_server(state_root, environment=...) | Starts nonpersistent Redis and confirms group/port release on exit |
| gate_settings(example, state_root, service_port=, redis_url=, namespace=, customize=) | Rewrites example configuration to owned temporary paths; namespace becomes core.namespace and contributes to Cookie names |
| use_owned_redis(payload, redis_url) | Redirects **every** Redis alias in one configuration to owned Redis with separate DBs, retaining everything else. Adds omitted built-in DEFAULT/CACHE/SESSION too, preventing fallback to localhost:6379. Useful for real commands in temporary projects without complete gate settings |
| migrate_gate_database(...) / ensure_gate_admin(...) | Applies migrations as first-time setup and creates gate administrators through public APIs |
| owned_service(config_file, ...) + wait_for_service(...) | Starts services in foreground, waits for listening, confirms complete group reaping afterwards |
| run_browser_child(command, ...) | Runs real-browser children and requires empty console/page/response errors |

Projects must not copy these scripts into scripts/: copies do not follow framework upgrades. Demo scripts/verify-*.py retain only page assertions/configuration differences and import the rest from oldman.testing.

## Preventing copied second implementations

oldman.testing.duplication turns existing-code duplication into tests rather than relying on memory:

| Entry point | Finds |
| --- | --- |
| duplicate_functions(left, right, min_lines=6) | Same-named functions with identical body structure across source trees; copies usually retain names, limiting false positives |
| identical_files(left, right, suffixes=...) | Byte-identical copied scripts, templates, and type declarations |
| forbidden_imports(root, modules=..., allowed_names=...) | Imports bypassing public APIs, such as non-Admin business functionality from oldman.apps.admin |
| forbidden_attributes(root, attributes=("app.ext.environment",)) | Attribute access bypassing public entry points |

The framework compares Admin against oldman.web/oldman.auth; projects compare their code against framework packages. Checks read source without importing inspected modules.

On finding duplication, **first determine who owns the capability**. Framework functionality moves into the framework with docs/tests, leaving project calls only. Retain genuinely project-specific logic. Making copies look different just to pass is precisely what this guard opposes.

<!-- source: zh/developers/testing.md @ 60ab2b58 -->
