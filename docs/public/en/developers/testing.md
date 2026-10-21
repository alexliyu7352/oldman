# Test isolation requirements

This chapter sets requirements for test and verification environments without adding production APIs. A service still uses one process, one root configuration, and one set of Apps and models. Test convenience does not justify changing this model.

## Choose isolation by the tested boundary

| Test target | Suitable environment |
| --- | --- |
| Pure functions, serialization, or objects without configuration | Use ordinary unit tests with explicit inputs. |
| Functions reading current settings | Bind global configuration temporarily within the test, check actual behavior, and restore it afterwards. |
| Settings, App Registry, model loading, or service discovery | Use a complete temporary project and a separate Python process. |
| Transactions, foreign keys, or file cleanup | Use an independent database and Storage directory with actual flush, commit, and rollback operations. |
| Redis or NATS behavior across processes | Use task-owned instances or explicitly isolated resources, with actual publishing and reading. |
| Page interaction, builds, or installation | Use an isolated application and verify actual artifacts, browser interaction, and data results. |

The existing `tests/test_oldman_service_bootstrap.py` demonstrates temporary projects and subprocesses. Reuse that isolation boundary without introducing a new application-runtime configuration protocol.

## Configuration and imports

- Do not read `conf.settings` or an unbound App's `app.settings` before bootstrap. Service-startup tests should verify that the actual entry point completes initialization.
- Do not switch between api and web service configurations in one process. Start separate processes to compare services instead of adding production reset operations or configuration proxies.
- Narrow unit tests that bind configuration directly must restore original values automatically, including after assertion failure. Do not attach fake configuration to `app.ctx.settings`.
- Real App and model loading affects `sys.modules` and SQLAlchemy metadata. Clearing only a registry dictionary does not reset the complete bootstrap state.
- When simulating independent project packages, service files, or model ownership, set the subprocess cwd to the temporary project root. Do not write temporary config packages into the framework root.

Tests may patch external I/O to trigger a specific exception precisely. However, patched database or Redis behavior cannot establish correct cross-process or transaction semantics. Distinguish the corresponding real integration verification explicitly.

## Resources and failure paths

Retain handles for test-created processes and stop and await them in finally. Close browser profiles and shut down databases, connection pools, and background tasks normally. Do not kill user services in bulk by process name.

Use standard TemporaryDirectory or mktemp -d for temporary directories, track their ownership, and delete only directories owned by this task. Release tools retain evidence that requires explicit cleanup; see [the maintenance instructions](maintenance.md#full-verification-in-serial-stages).

Failure tests should at least verify what did not happen: invalid input did not write data, rollback retained the original file, unauthorized requests did not read another user's data, or a failed action did not run later actions. Do not assert only an error message.

Changes to actual UI require manual interaction. DOM and source assertions can assist protocol checks but cannot prove that layouts, Modal sizes, click responses, or loading-failure feedback are visible. Dashboards and Admin must use the same public component protocols.

## Limit verification scope

After completing a small module, run only checks required to continue safely. Run remaining full release checks together and sequentially. Do not introduce duplicate state, permanent screenshot caches, or complex test-only production branches merely to make checks pass.

When a test expectation is outdated, examine the current contract and actual behavior before deciding whether to correct or remove it. Do not restore removed interfaces for old assertions or treat historical internal documents as requirements for production correctness.

## Real-service checks

The Redis, NATS, and Taskiq checks in the Python gate, `pnpm verify:python`, start their own service processes. They require two executables:

| Program | Discovery | Requirement |
| --- | --- | --- |
| `redis-server` | Use environment variable `REDIS_SERVER`, otherwise search PATH. | Version 6.2 or later is required because taskiq-redis uses `GETDEL` to read results and schedules. |
| `nats-server` | Use environment variable `NATS_SERVER`, otherwise search PATH. | The server must support JetStream through `-js`. |

Missing executables or Redis older than 6.2 make the corresponding checks fail with configuration instructions rather than skip. A skipped check would appear successful in the gate despite performing no verification.
Discovery uses `require_redis_server()` in `tests/redis_support.py` and `require_nats_server()` in `tests/nats_support.py`. New real-service tests must use them too, rather than `skipUnless`. They only locate executables. Each check starts services on its own ports or Unix sockets and never connects to an already-running Redis or NATS.
Only two checks still skip: the NATS credentials test requires `NATS_TEST_CREDS_DIR` pointing to the public nkeys examples in the nats.py repository, and Django cache interoperability requires Django to be installed.

## Browser and process gate tools

`oldman.testing` provides real-browser verification, process-tree cleanup, and PNG evidence checks. It uses only the standard library and neither reads settings nor starts services on import:

| Entry point | Purpose |
| --- | --- |
| `ChromePage`, `CDPClient`, `navigate`, `configure_viewport`, and `save_screenshot` | These use local Chrome's DevTools Protocol to open pages, capture screenshots, and run `client.evaluate(...)` assertions. |
| `BrowserResult` | This collects console errors, page errors, and bad responses separately from business assertions. |
| `find_free_port` | This finds an available port for a temporary service. |
| `tracked_popen` and `ProcessTreeTracker` | These start child processes and confirm that the entire process tree has exited afterwards. |
| `require_png` | This confirms that a screenshot is a sufficiently large PNG rather than a zero-byte file. |

Use `oldman.testing.gates` when you need a fully owned temporary environment that does not touch active development services or data:

| Entry point | Purpose |
| --- | --- |
| `minimal_environment()` | This retains only variables needed to start local tools and fixes `TZ=UTC` and `PYTHONHASHSEED=0`. |
| `owned_redis_server(state_root, environment=...)` | This starts nonpersistent Redis and confirms release of its process group and port on exit. |
| `gate_settings(example, state_root, service_port=, redis_url=, namespace=, customize=)` | This rewrites project example configuration to use only temporary paths. `namespace` becomes the service's `core.namespace` and is used in Cookie names. |
| `use_owned_redis(payload, redis_url)` | This redirects **every** Redis alias in one configuration to owned Redis, with a separate database per alias and everything else unchanged. It also adds omitted built-in DEFAULT, CACHE, and SESSION aliases so they cannot fall back to `localhost:6379`. Use it for real commands in temporary projects that do not need the full gate configuration. |
| `migrate_gate_database(...)` and `ensure_gate_admin(...)` | These apply migrations as first-time setup and create the required administrator through public APIs. |
| `owned_service(config_file, ...)` and `wait_for_service(...)` | These start a foreground service, wait for it to listen, and confirm that the whole group is reaped afterwards. |
| `run_browser_child(command, ...)` | This runs a real-browser subprocess and requires no console errors, page errors, or bad responses. |

Projects must not copy these scripts into their own `scripts/`: copies do not follow framework upgrades. Demo `scripts/verify-*.py` files retain only their pages' assertions and configuration differences, importing the rest from `oldman.testing`.

## Preventing copied second implementations

`oldman.testing.duplication` tests whether code already exists elsewhere instead of relying on memory:

| Entry point | What it finds |
| --- | --- |
| `duplicate_functions(left, right, min_lines=6)` | This finds same-named functions with structurally identical bodies across two source trees. Copies usually retain names, so false positives are uncommon. |
| `identical_files(left, right, suffixes=...)` | This finds byte-identical files, such as copied scripts, templates, and type declarations. |
| `forbidden_imports(root, modules=..., allowed_names=...)` | This finds imports that bypass public APIs, such as importing functionality unrelated to Admin business from `oldman.apps.admin`. |
| `forbidden_attributes(root, attributes=("app.ext.environment",))` | This finds attribute access that bypasses public entry points. |

The framework compares Admin against `oldman.web` and `oldman.auth`; projects compare their own code against framework packages. Checks read source without importing the inspected modules.

When duplication is found, **first determine who owns the capability**. Framework functionality belongs in the framework, with documentation and tests, leaving only calls in project code. Keep code in the project only when it is genuinely project-specific business logic. Changing duplicate implementations to look different merely to pass a test is exactly what this guard is intended to prevent.

<!-- source: zh/developers/testing.md @ 60ab2b58 -->
