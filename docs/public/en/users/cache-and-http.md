# Cache examples and external HTTP

Caching reduces repeated computation; the backend HTTP Client calls upstream systems; Redis/NATS providers supply specific infrastructure. None replaces database records that need long-term persistence.

## What the demo currently uses

The EPG demo's configuration, services, and Apps already integrate Redis Session, SSE, and user notifications. The realtime chart publishing entry point is in [views/charts.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/charts.py). It publishes through SSEPublisher, without business code directly operating Pub/Sub.

The general cache page is `/examples/cache/redis`. It derives statistics from actual projects and stores a short-lived snapshot in Redis. You can operate it directly in the demo as described below; it is not a Session or SSE cache.

The backend HTTP page is `/examples/http/client`: Python requests the configured upstream, and the browser displays diagnostics. The browser HTTP Client is not the backend MultiHttpClient. Background NATS events/RPC are covered in a separate [communication tutorial](service-communication.md), outside this page's HTTP protocol.

## Run project statistics cache example

First follow [Run the EPG dashboard demo](getting-started.md) to initialize, migrate, import the `demo` fixture, and create an account. The public [web_settings.example.yaml](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/web_settings.example.yaml) contains:

```yaml
redis:
  CACHE:
    redis_url: redis://localhost:6379/2
```

This is an excerpt from existing YAML, not a replacement for the whole configuration. Keep aliases such as Session and SSE. For existing local `web_settings.yaml`, check the actual `redis.CACHE` address. The demo neither starts Redis nor modifies configuration in use. Start `./run.sh web start`, sign in, and choose “Cache → Redis Cache” in the sidebar. The default address is `http://127.0.0.1:17997/examples/cache/redis`.

Follow this sequence:

1. When the page is first opened, it only has buttons and descriptions, no statistics are queried, and the cache is not filled in advance.
2. Click “Read statistics”. Without a snapshot, the backend counts projects grouped by `ExampleProject.status`, displays “Calculated from database”, the total project count, and the UTC computation time, then writes a JSON cache with a 30-second TTL.
3. Read again within 30 seconds. “Redis cache hit” should appear with the same counts and computation time. This does not query the project table or extend expiry. After 30 seconds, read again to recompute.
4. Open `/examples/tables/html` or `/examples/tables/json`, edit a project's status in its existing Modal, and save. Return to the cache page and click “Recalculate from database”. The corresponding two status counts and computation time should change. This example does not automatically watch CRUD; ordinary reads before expiry may show the old snapshot.
5. Click “Clear this example cache” to delete only this statistics key. Clearing again displays “There was no cached snapshot to clear.” The next read queries the database again. Do not replace this operation with clearing the Redis database.

An empty project table displays and caches zero results, without filling in fixed demonstration numbers. All signed-in users share these statistics; clearing them affects other users' next read too. Do not copy this directly for private per-user data, permissions, or billing caches. The page does not write projects; only the CRUD in step 4 changes data.

## Looking at the calling relationship from the actual code

| File | Responsibility |
| --- | --- |
| [cache_example.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/cache_example.py) | holds RedisCache; read snapshot, database group query, write TTL, delete single key |
| [views/cache.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/cache.py) | GET page; three statistics POST; independent response cache GET/invalidation POST; sign in check and write operation CSRF |
| [cache template directory](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/cache) | Buttons, descriptions, independent result areas and fragments for two cache partitions |
| [`views/__init__.py`](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/__init__.py) | page list and specific routing module import; continue to use the existing Examples App to register |

Business function `read_project_statistics(refresh=False)` returns the snapshot and current source; it does not write "hit" into the snapshot. `clear_project_statistics()` calls `delete(CACHE_KEY)` of the same instance. For complete function and type description, see [Caching](../developers/cache.md#actual-use-in-the-demo).

There is no cache-specific frontend TS. The current Page handles buttons' `data-om-action="post"`, `data-om-url`, and `data-om-target="#cache-result"`. The view calls `replace_html_response(html)` so the ordinary response runner replaces the result region. Preserve page loading, CSRF, and permission wiring when reusing it; do not copy only `fetch()` or expose an interface for arbitrary Redis keys.

Constructing RedisCache does not connect to Redis; its first operation obtains a connection through the provider. Cache operations time out after 5 seconds; the 30-second TTL specifies data validity, a separate setting. Connection, timeout, serialization, and database errors propagate. Existing HTTP/Feedback handling shows the failure and ends loading, without pretending a cache hit or zero projects. Reproduce faults with separate test configuration and Redis, without stopping services used by Session or other business functions.

The cache object does not own Redis's shared pool; do not close it after every request. The framework closes Redis and the database engine on shutdown. Concurrent misses may repeat this small read-only query. There is no additional distributed lock, background refresh, or two-level cache.

## Observe in-memory cache and two-level cache

Use the same database settings as the Redis statistics page above. No sign-in, frontend build, or running Web service is needed. Once CACHE Redis and migrations are ready, run in the demo root:

```bash
./run.sh web cache-levels
```

The App command will load the web configuration; if NATS/Taskiq is enabled, you must still prepare the corresponding facilities, or turn them off in your own test YAML. This example itself only requires the database and Redis, and does not start the Worker/Scheduler.

The command performs a finite demonstration automatically:

1. Compute statistics from actual projects and store them in this process's MemoryCache. Read immediately to observe a hit, then wait for a short TTL to expire.
2. Create TwoLevelCache and save memory and Redis snapshots at the same time.
3. A real child process recomputes statistics and updates Redis. Its new MemoryCache starts empty, while the parent's existing memory remains unchanged. Output shows actual `before/shared_updated` computation times and `local_stale=true`, without fabricating changes in project counts.
4. Deleting the local copy of the parent process and reading again will backfill the new value from Redis; then actually observe two levels of expiration and explicit deletion.
5. Clean up this run's random namespace, memory timers, and both processes' connections without changing business data. Redis unavailability makes the command fail, without reporting false hits.

Assertions in [cache_levels.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/cache_levels.py) check real results. Normal output has memory_hit, memory_expired, backfilled, both_expired, and both_deleted all true. Reading an old local value after another process updates Redis is a known two-level cache limitation, rather than a demonstration bug to hide with broadcasts. Do not use this pattern for data needing immediate consistency, such as permissions or sign-in state. MemoryCache has no capacity limit by default and does not copy stored dict/list objects.

## Optional: Exchange cache with Django

EPG `django-cache` uses Django's own RedisCache, does not imitate its format, and does not start the Django website. The framework and ordinary Demo do not depend on Django; when trying this item only, provide isolated dependencies for this command in the Demo root directory:

```bash
demo_django_dir=$(mktemp -d /tmp/oldman-django-demo-XXXXXX)
uv pip install --python .venv/bin/python --target "$demo_django_dir" 'Django>=5.2,<5.3'
PYTHONPATH="$demo_django_dir" ./run.sh web django-cache
# After the command has ended, confirm that this is the directory created above, and then clean it up.
rm -r -- "$demo_django_dir"
```

PYTHONPATH only lets this Python command locate the optional library; it does not configure business Settings through environment variables. Database/Redis prerequisites match cache-levels. The Redis address comes from the alias selected by current `settings.cache.client`, without printing credentials. Missing optional dependencies cause an explicit error; other commands and pages remain usable.

The command actually checks Django writes read by Oldman and the reverse: project statistics, 0, negative integers, bool, None, Chinese text, and bytes. Output includes bidirectional_values=8 and types_preserved=true. It then checks TTL, None versus missing keys, actual 1-second expiry, and deletion with nonpositive timeout. Oldman's fixed version=1 interface cannot read Django values written with version=2; version_2_is_separate=true confirms this. Finally, it writes corrupt data to **this run's key**. Both sides must raise decoding errors, rather than treating corruption as a miss.

The source code is [django_cache.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/django_cache.py). The command only reads the business database, only writes random keys and deletes them in finally, and never calls Django.clear (which will clear Redis DB). Both parties close their own connections; the framework's default cache encoding is not changed.

Interoperability requires the same Redis DB, Django's default empty KEY_PREFIX, VERSION=1, and default codec. Custom prefixes, versions, KEY_FUNCTION, or other Redis backends are not adapted automatically. Read Pickle data only from trusted services; this command does not establish that arbitrary external Redis data is safe. See [Django Redis Configuration](https://docs.djangoproject.com/en/5.2/topics/cache/#redis) and [the framework's exact contract](../developers/cache.md#django-cache-interoperability) for exact boundaries.

## Observe the real files of the image cache

Run `./run.sh web image-cache` with the current CACHE Redis. It does not query business tables, require imported images, or start a website. The App command still loads the selected service's settings and enabled infrastructure.

[image_cache.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/image_cache.py) generates its own 64×64 PNG in memory and passes the bytes to ImageCache. Results show the Storage logical name and actual WebP dimensions (30% scaling by default, producing 19×19 here). The framework does not download an image from a URL; `demo:first` is just a cache identifier.

The command checks original image bytes, WebP readability, and expiry extension on hits. After 1-second expiry, reads miss while the old file temporarily remains; the next write cleans up expired files. A deliberately corrupt image logs WebP conversion failed, but the current API preserves original bytes and returns only original. This demonstrates actual partial failure, rather than failure of the whole command. The cache is not an upload image validator.

Once all five checks output true, the command deletes its random Redis set and `/tmp` image directory and prints completion of cleanup. Files serve only this inspection and do not remain in the user's media library. Image cache capacity cleanup runs before writes by format entry, rather than enforcing a strict total image count or byte limit. See [the reference](../developers/cache.md#image-caching) for defaults and resource ownership.

## Observe function results and the entire HTTP response cache

With the database and CACHE Redis ready, run `./run.sh web cached-stats`. [cache_functions.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/cache_functions.py) decorates the same statistics query inside the command with `cache_async_response(timeout=1, prefix=<random-per-run>)`. Output includes first, cache_hit, and after_expiry: the first two have identical computation times; the third changes after a 1.1-second wait. The command only reads the database. In finally it deletes keys under its own prefix and closes the database and Redis. No website needs to start first.

Another example on the web page is in the "HTTP response cache" section below `/examples/cache/redis`. It caches the entire response, not the 30 second statistic above:

1. Click “Read cached response”. The backend queries the actual project count and returns a standard JSON replace_html action containing statistics HTML.
2. Click again within 5 seconds: project counts and computation time remain unchanged. There is no “Just queried the database” badge because the entire response is reused. Its first source label cannot describe the current read.
3. Wait 5 seconds before reading again, the calculation time should be updated; of course the number can be the same if the database remains unchanged.
4. Click “Invalidate response cache”, which POSTs to the same path and displays completed invalidation. It removes this example's cached query-parameter and language variants; the next read recomputes. It neither modifies projects nor clears the statistics key above.
5. Switch language and read; results use the current language. Return from another example through the sidebar and check that buttons still work. Signed-out requests still fail authentication; POST without valid CSRF is rejected. After dismissing the shared error message, you can operate again.

Implementation is example_cached_response/example_invalidate_response in views/cache.py. Both buttons use ordinary ExamplesPage and target `#cache-response-result`, without new TS or components. GET checks sign-in through `login_required()` before entering the cache decorator; cached responses are isolated by request.ctx.locale. Responses contain no private user data, CSRF, or Cookies; do not copy this directly to cache personal account pages.

Both decorators read root cache.client/namespace. The public YAML does not override cache, so it uses default client=CACHE. Cache failures log a warning and continue querying/returning business results; database exceptions still propagate. This differs from direct RedisCache operations above, which do not automatically fall back. Verify hits through actual computation time; a successful database query while Redis is offline is not a hit. Command checks require accessible Redis and fail otherwise. See [the developer reference](../developers/cache.md#function-result-and-http-response-caching) for signatures, key rules, and content that cannot be cached.

## Observe model cache

Model caching stores database rows per model and query, invalidating automatically after writes commit without manual key deletion. The demo enables it on `ExampleTask`: `@cached_model(partition_by=("project_id",), invalidate_on=(ExampleProject, ExampleTeam))`. See [models.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/models.py) and page logic in [model_cache.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/model_cache.py). Choose “Cache → Model Cache” to open `/examples/cache/models`, select a project, then:

1. Click "Read tasks" twice. The first time it displays "Cache miss: read from the database and stored", the second time it displays "Cache hit"; each time it displays the time taken and the hit statistics of this process so far.
2. Click “Rename its first task (ORM)” and read again: a miss, with `(ORM)` appended to the first task's title. Reading shortly after commit may show “Bypassed”: this process has not yet written invalidation to Redis, so it queries directly. Read again afterward.
3. Click “Rename a task of another project (ORM)” and read this project again: it still hits. The query fixes `project_id`, so only writes to this project's tasks invalidate it.
4. Click “Rename its first task with an UPDATE statement” and read again: it still hits, with the old title. Bulk statements do not trigger ORM events, so the cache cannot see them. Click “Invalidate the task cache” and read: a miss now shows `(SQL)`. Production code writing this way must call `ExampleTask.invalidate_cache_on_commit(session)` in the same transaction, as the demo Worker task `complete_example_task` does.
5. Click “Rename the project (ORM)” and read: a miss. The database cascades task deletion from projects and project deletion from teams (two levels of `ON DELETE CASCADE`). The cache can only learn this from project/team writes, so any update or deletion of either invalidates all task queries once.
6. Click “Restore example data” to remove markers added by these operations. Restoration also uses ORM, invalidating the relevant cache.

Concurrent operations by other signed-in users may mix another user's reads into statistics deltas, displaying “Source unknown: another read ran at the same time”. See [the developer reference](../developers/cache.md#model-caching) for read/write rules, boundaries, and measured timings.

## When caching is needed

- To share recalculable results among multiple workers, use [RedisCache and redis_cache](../developers/cache.md).
- Use [model caching](../developers/cache.md#model-caching) to cache database rows and query results with automatic invalidation after writes.
- Use MemoryCache for temporary results within one process. It provides neither cross-process sessions nor permission invalidation.
- Use separate namespaces and finite TTLs to express ownership and acceptable staleness. Do not clear shared Redis to reset an example.
- Update or invalidate caches after database changes succeed. Do not claim atomic commits across the two systems.
- Business code decides whether to fall back after cache failure. Do not swallow actual database or computation errors.
- See [Caching](../developers/cache.md) for Django cache interoperability. Do not confuse its key/codec/TTL rules with native Oldman Cache rules.

The reference defines configuration, hits, expiry, None/False/0, multiple processes, and resource cleanup. CACHE serves the caching examples without changing Table's existing database queries. TwoLevelCache is a separate CLI example; do not assume it is integrated into every page.

## Running the backend HTTP example

Use the same Demo that has been initialized and can be used for sign in. Enter from the sidebar "HTTP → Backend HTTP Client". The default address is `http://127.0.0.1:17997/examples/http/client`. This example does not require adding a new database table, importing additional data, or starting another Oldman service.

The upstream address in the public configuration is:

```yaml
app_settings:
  examples:
    http_base_url: https://httpbin.org
```

This excerpt belongs within the existing YAML; do not replace all app_settings with it. Older configuration without this setting uses ExamplesSettings defaults; `./run.sh web settings sync` fills it in. To use your own environment, set an httpbin-compatible instance you deploy, then restart. The base URL may include a path prefix but must not contain credentials, query parameters, or a fragment.

Only button clicks call the upstream. Loading pages, starting services, and switching sidebar pages do not make external requests automatically. The public upstream sees the server's egress address, demo User-Agent, and fixed parameters, without browser sign-in Cookies, user input, or project records. Public services may be unavailable, rate-limit requests, or return delayed requests early. Do not disable TLS verification in response.

Follow this sequence:

1. Click "Read JSON". Python requests `/get` and carries fixed `example=oldman-epg-dashboard` parameters. The results area shows the actual HTTP status, Content-Type, elapsed time, and upstream JSON; not a set of demo numbers pre-populated by the page.
2. Click "Observe upstream 404". The results should clearly show the upstream 404 and failure status. The Demo page is still retained and does not jump to the Demo 404 page.
3. Click "Observe timeout". The upstream interface request is delayed for 10 seconds. In this example, the entire operation waits for about 5 seconds at most without retrying. If the upstream returns early, it should display the actual result returned; if it is indeed delayed, it should display a timeout, and it can still be operated after loading.
4. Click “Read byte stream” to request 65536 bytes. Python counts chunks and computes SHA-256, then displays the actual byte count and digest. It saves no file and sends no browser progress over SSE. Exceeding this example's 1 MiB limit closes the response without reporting a false complete digest.
5. Read the JSON again to confirm that the previous error did not render the client unavailable. This page can be accessed from the cache page or other pages through the sidebar and checks that the same buttons still work.

There are two HTTP layers: the browser requests the demo, then the demo requests the upstream. Demo HTTP 200 with a replace_html action means diagnostics were delivered, not that an upstream 404, timeout, or connection failure succeeded. Authentication, permission, and CSRF failures, plus demo programming errors, still use existing authentication/shared error handling.

### Source code and resource ownership

| File | Responsibility |
| --- | --- |
| [http_example.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/http_example.py) | holds the client, four requests, timeouts, diagnostic results and flow context |
| [settings.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/settings.py), [apps.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/apps.py) | Strongly typed upstream configuration and registration of Examples App |
| [views/http.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/http.py) | Sign-in/CSRF, operation whitelist, rendering of page and result fragments |
| [HTTP Template Directory](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/http) | Four buttons, target area, diagnostic text; HTML in JSON will not be executed |
| [services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py) | Initialize the HTTP Client at startup and close it on shutdown, retaining the framework's original cleanup |

There is no dedicated TS for this example: the buttons use `data-om-action="post"` and `data-om-target="#http-result"`, and the normal ExamplesPage executes the replace_html returned by the view. For the complete Python implementation, see [the HTTP reference](../developers/http-client.md#actual-use-in-the-demo).

Each worker owns a MultiHttpClient without user credentials, using HTTPX, 8 connections, no retries, no redirects, and TLS verification enabled. Service startup calls init_client, but actual network connections open only on the first click. Request completion closes only the current response; service shutdown calls close_client. Do not share this instance directly across users' separate upstream sign-in Cookies.

Upstream disconnections produce explicit diagnostics without disabling Session, Redis cache, or other pages. Use isolated configuration and an upstream you own for failure verification, without stopping real business services. This example does not cover multiple backend comparisons, Cookie sign-in, downloads saved through Storage, or resumable downloads; their public contracts remain in the reference.

## Call external HTTP in business

Use [MultiHttpClient](../developers/http-client.md) and do not duplicate another set of network layers in the business App. Make it clear who initializes, who holds the connection pool, and who closes:

- One-time commands use their own invocation lifecycle, eventually releasing the client.
- The long-running service reuses the connection pool and does not close the global client at the end of each request.
- Check HTTP status according to the upstream contract before parsing the body. Do not turn exceptions into false success or empty objects.
- Write requests such as POST are not retried by default due to network failure; they may have been processed by the other party, and the business needs to clarify idempotent rules.
- Take URLs, authentication, proxies, and TLS from trusted settings. Do not treat arbitrary user-submitted URLs as safe upstreams.
- Use streaming responses and existing Storage for large files; do not read unbounded data into memory first.

When the backend receives the business error code in JSON, it is interpreted by the backend business and is not handed over to the browser ResponseActionRunner.

## Other connections

The [provider reference](../developers/providers.md) explains named Redis connections, Pub/Sub, and NATS publishing/RPC. Worker control messages, browser user messages, and external infrastructure have different boundaries; do not wrap them in one ambiguous MessageBus.

When adding demo coverage, provide an actual source, visible results, a failure path, and shutdown cleanup for each scenario. A fake upstream returning a fixed dictionary does not verify network wiring. See [Demo page and source index](demo-examples.md) for existing interactive pages.

<!-- source: zh/users/cache-and-http.md @ eb6d1968 -->
