# Deployment and Operations

This chapter deploys applications built with Oldman, rather than running the framework source repository as a business project. Complete the relevant tutorial first and prepare your own permission and data rules. Linux is the current runtime target. Drivers, software versions, and dependency locks follow the release obtained by the project.

## Four things to know before deployment

1. **Which service runs**: the EPG demo's `services/web.py` corresponds to `./run.sh web start`. Each command runs only the specified service. This actual entry point is used below; substitute your application's file name when different. Services use separate YAML files, without switching configuration within a process.
2. **Who manages database structure**: one project owns migrations for a shared database. Other projects must not independently modify the same migration state. Deployment applies reviewed migration files, without running ad hoc makemigrations on the server.
3. **Where data lives**: service configuration, databases, uploaded files, and log directories must persist, be writable, and have backups. Releasing code or replacing containers must not clear those directories.
4. **Which external connections are required**: a pure API may not need Redis; Session and distributed SSE do. Taskiq requires NATS with JetStream enabled and Redis 6.2 or newer (taskiq-redis uses `GETDEL` for results and schedules). Enable external HTTP and remote Storage according to business needs. settings check validates configuration without establishing connection reachability.

## Prepare the operating environment and configuration

Use the application's own Python environment and lock files, installing an Oldman version matching the documentation. Editable source is suitable for development. For production, prefer verified release artifacts with fixed versions; symlinks to development directories are not a deployment strategy.

The EPG demo's installer is `python3 scripts/bootstrap.py`; see [Run EPG Dashboard Demo](getting-started.md) for its local-source and published-package paths. The current demo commits neither uv.lock nor frontend pnpm-lock.yaml, so a frozen installation cannot be run directly and claimed to lock deployment dependencies. Pin and verify dependencies in the application's release process, rather than upgrading them ad hoc on a production host to bypass failures.

These two commands are **installation interfaces after the application prepares and commits the corresponding lock files**, rather than steps already supported by the current demo:

```sh
uv sync --frozen
pnpm -C frontend install --frozen-lockfile
```

Pure API or background applications need no frontend installation. Source-linked development projects without a pinned release source must finish dependency release preparation first; do not run these commands directly to switch dependency sources.

In a new environment without YAML, initialize from a reviewed same-name `.example.yaml`, edit real connections and keys, then check before starting. Use sync to add fields to existing YAML. Back up and inspect differences first; do not overwrite it with init.

```sh
./run.sh web settings init
# Edit data/web_settings.yaml and check again
./run.sh web settings check
```

The web security root key is generated and written during init/sync and does not change randomly when the worker starts. All workers must read the same service configuration. Do not commit real YAML, passwords, session cookies, or notification private content to public repositories.

HTTPS deployments check at least the following existing fields:

```yaml
core:
  debug: false
web:
  auto_reload: false
  listen_host: 127.0.0.1
  listen_port: 18080
  domain: https://dashboard.example.com
  fallback_error_format: auto
  session:
    cookie_secure: true
    cookie_httponly: true
    cookie_samesite: Lax
```

Merge this excerpt into existing configuration and replace the domain. Do not remove other fields such as session.enabled or Redis settings. On a development machine using HTTP, do not enable Secure Cookies and then mistake the resulting behavior for failed sign-in.

## Databases and static resources

Create a recoverable backup and verify the current connection before database migration. First use or internal state recovery may require interaction; do not present initial setup as entirely unattended deployment.

```sh
./run.sh db status
./run.sh db migrate
./run.sh db status
```

Deployment must include migration files for every registered App, rather than models.py alone. Do not run migrations independently at startup in each Sanic worker. Fixtures provide preset data, not database backups; dumpdata does not replace full backups for business data recovery.

Business Dashboard performs its own installation and construction in the application frontend project, and then collects resources from the application root. For example when using the tutorial script:

```sh
pnpm -C frontend build
./run.sh web static collect
```

Using only the built-in Admin requires its ready-made assets in the release package and static collect. Pure APIs with no browser assets do not need this step. Production pages must not point to a Vite development server.

`web.static.root` specifies the collection directory; `web.static.url` specifies the public URL. They are different. A proxy serving static files must map the same collection directory. After upgrades, verify that hashed files referenced by HTML exist, avoiding deletion of assets still referenced by old pages.

## Starting, stopping and process hosting

```sh
./run.sh web start
```

This is a foreground process. `run.sh` selects the project environment and passes arguments unchanged. It does not start other services, Redis, databases, or frontend builds automatically.

In an ordinary terminal, use Ctrl+C. When launched by a script, the service takes foreground control only if stdin is a terminal, so Ctrl+C reaches it; this applies when the script runs it directly without redirecting input. With `&` or redirected input (`< /dev/null`, a pipe, or `nohup`), the script retains terminal control and you must use `stop`. From another terminal, `./run.sh web stop` first verifies `pids/web.identity.json` beside `pids/web.pid`, signals the main process to terminate, and waits for the entire process group, including Sanic workers and processes created during shutdown, to exit before returning and printing the main PID. If the group remains after `process.stop_timeout` (60 seconds by default), it receives SIGKILL. `restart` performs this stop before starting again.

Running state comes from the PID file lock. The lock is released however the process ends, including `kill -9` or power loss. A leftover PID file does not block startup, and PID reuse does not cause an unrelated process to be stopped. The identity record is replaced as a whole. If it cannot be read (for example, after manual corruption or disk failure), `stop` removes it as stale when no instance holds the lock and treats the service as stopped. If an instance is running, `stop` sends no signal, reports an error, and provides the main PID for manual termination. Forked children close inherited locks (the framework's own children already use spawn), ensuring release after main process exit. If the main process is killed while its children survive, both `start` and `stop` list those processes and refuse to proceed. Terminate them first with `kill -TERM -<process-group-id>`. Children moved into their own process groups through `setsid` or `setpgid` are outside the service group; `stop` neither waits for nor terminates them, so the service must handle them on exit. Do not delete a running service's PID file to force a fix: `start` still detects the running service and refuses to start. Use `stop` as usual; it finds the service through the identity record.

When the service runs as a container's entry process (PID 1), let the container stop/restart it. `docker stop` and `docker restart` send SIGTERM, and the service exits normally. Running `stop`/`restart` inside the container is rejected without sending signals, because signaling process group 1 would affect every process in the container.

In production, a system process manager can supervise the same foreground command. Explicitly configure the application root as working directory, a user with data-directory permissions, the project's `.venv/bin/oldman web start` command, the exit signal, and a reasonable stop timeout. The supervisor restarts the service main process; do not add another main-process watchdog. Taskiq's internal supervision of its execution children is a separate responsibility; retain that keepalive mechanism.

`prepare_server()` determines how to hand over settings such as workers to Sanic. Check the database pool, background tasks per worker, memory cache, and SSE subscriptions before adding workers; do not assume that in-process objects are automatically shared.

## Distributed task service

See [Distributed background tasks](distributed-tasks.md#7-stopping-troubleshooting-and-scope) for Taskiq Worker/Scheduler. Run each with its own foreground command, with one Scheduler per namespace. Multiple Worker services can consume the same or different queues. JetStream file storage and Redis dynamic schedules need persistence policies; results expire automatically after 24 hours by default. Like ordinary services, Taskiq stop waits and then force-stops the entire verified process group after the total deadline (`taskiq.stop_timeout`); no second kill command is needed. systemd is an optional outer supervisor. Stop through it to prevent its Restart policy from starting the service again.

## Reverse proxies and long-lived connections

- Allow only trusted proxies to reach internal listening ports. The proxy must overwrite client-supplied real-IP headers; do not trust X-Real-IP supplied directly by Internet requests.
- TLS, trusted forwarding headers, and public domain names must be consistent, otherwise secure cookies, redirects, and CSRF origin checks may fail.
- The SSE path needs to forward continuously, not buffer events, and allow sufficient idle timeout for connections; heartbeats cannot pass through a proxy that caches responses all the time.
- The WebSocket path must also correctly forward Upgrade. SSE is not the same proxy protocol as WebSocket.
- Static directories can be public; attachment directories must not all be public. Default framework media routes do not enforce download permissions; private attachments need protected views.

The framework will not automatically verify your public network boundaries against a proxy sample. Before going online, verify sign in, cookies, uploads, and SSE/WS from the actual external network path, not just curl the loopback address on the server.

## Shutdown responsibilities and failure observation

Resources are cleaned up by the service that owns them. The framework closes process-shared caches, Redis, and database engines on shutdown. The demo's WebService closes its HTTP example client in `after_server_stop()`. Cleanup runs in awaitable service lifecycle hooks, without destroying process-level pools after every request. SimpleApplication has its own before_stop/after_stop. Do not rely on the framework guessing how to close HTTP/NATS connections, scheduled tasks, or subscriptions. See [Backend HTTP client](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/http-client.md#创建初始化关闭), [Applications and lifecycle](../developers/applications.md), and [Processes and background tasks](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/background.md) for actual methods and relationships.

The default health extension or an open port does not establish database, Redis, or third-party availability. According to application needs, deployment checks should perform a read-only database request, a sign-in/sign-out, and a representative business operation. Do not repeatedly write business data for probes.

| Failure | Check first |
| --- | --- |
| The first database request fails after startup | Delayed database connection, check URL, driver, permissions and migration status |
| Still anonymous after sign in | Cookie Secure/domain/path, proxy protocol, Session Redis; do not replace with memory session |
| The page has styles but the new components do not. | Application construction and icon scanning include the corresponding source code and whether the product is collected |
| CSRF 403 | Request token, whether the page has expired, whether the key has been regenerated, and whether the source is consistent |
| SSE is online but cannot receive | published and subscribed Redis alias with `core.namespace`, user binding, proxy buffering, browser console |
| Error during the stop process | Let’s first look at the first resource shutdown exception and distinguish between business tasks, connection pools and the final exit of the server |

Passing documentation examples does not establish production readiness. The deployer must still complete backup restoration drills, capacity assessment, monitoring and alerts, permission review, and application-specific failure paths.

<!-- source: zh/users/deployment.md @ 8c13fdcf -->
