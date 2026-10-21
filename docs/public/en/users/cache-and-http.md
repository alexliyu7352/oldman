# Cache Examples and External HTTP

Caching reduces repeated calculations; the backend HTTP Client accesses the upstream system; the Redis/NATS provider provides specific infrastructure. They do not replace database records that must be retained long-term.

## What the demo currently uses

The EPG demo's configuration, services, and Apps already integrate Redis Session, SSE, and user notifications. The realtime chart publishing entry point is in [views/charts.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/charts.py). It publishes through SSEPublisher, without business code directly operating Pub/Sub.

The actual page of the general cache is `/examples/cache/redis`. Statistics are generated from the real project table, and then Redis is used to save short-term snapshots. The following can be operated directly in the Demo; it is not a Session or SSE cache.

The backend HTTP page is `/examples/http/client`: Python requests the configured upstream, and the browser displays diagnostics. The browser HTTP Client is not the backend MultiHttpClient. Background NATS events/RPC have a separate [Communication tutorial](service-communication.md), outside this page's HTTP protocol.

## Run project statistics cache example

First follow [Running the demo](getting-started.md) to initialize, migrate, import the `demo` fixture, and create a staff account. The public [web_settings.example.yaml](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/web_settings.example.yaml) contains:

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
| [views/__init__.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/__init__.py) | page list and specific routing module import; continue to use the existing Examples App to register |

Business function `read_project_statistics(refresh=False)` returns the snapshot and current source; it does not write "hit" into the snapshot. `clear_project_statistics()` calls `delete(CACHE_KEY)` of the same instance. For complete function and type description, see [Cache Reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/cache.md#demo-中的实际使用).

There is no cache-specific frontend TS. The current Page handles buttons' `data-om-action="post"`, `data-om-url`, and `data-om-target="#cache-result"`. The view calls `replace_html_response(html)` so the ordinary response runner replaces the result region. Preserve page loading, CSRF, and permission wiring when reusing it; do not copy only `fetch()` or expose an interface for arbitrary Redis keys.

Constructing RedisCache does not connect to Redis; its first operation obtains a connection through the provider. Cache operations time out after 5 seconds; the 30-second TTL specifies data validity, a separate setting. Connection, timeout, serialization, and database errors propagate. Existing HTTP/Feedback handling shows the failure and ends loading, without pretending a cache hit or zero projects. Reproduce faults with separate test configuration and Redis, without stopping services used by Session or other business functions.

The cache object does not own Redis's shared pool; do not close it after every request. The framework closes Redis and the database engine on shutdown. Concurrent misses may repeat this small read-only query. There is no additional distributed lock, background refresh, or two-level cache.

## Observe in-memory cache and two-level cache

The database configuration is the same as the previous Redis statistics page, but there is no need to sign in, build the front end, or start the web. After CACHE Redis has been configured and the migration is completed, run in the Demo root directory:

```bash
./run.sh web cache-levels
```

The App command will load the web configuration; if NATS/Taskiq is enabled, you must still prepare the corresponding facilities, or turn them off in your own test YAML. This example itself only requires the database and Redis, and does not start the Worker/Scheduler.

The command automatically completes a limited demonstration:

1. Calculate statistics from the real project table and store them in the MemoryCache of this process; read the hits immediately and wait for a short TTL before disappearing.
2. Create TwoLevelCache and save memory and Redis snapshots at the same time.
3. A real child process recalculates and updates Redis. Its new MemoryCache is empty, and the old memory of the parent process will not be updated accordingly. Output the real computation time of `before/shared_updated` and `local_stale=true`, not fake item number changes.
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

Interop scope is the same Redis DB, Django default empty KEY_PREFIX, VERSION=1 and default codec. Custom prefixes, versions, KEY_FUNCTION or other Redis backends are not automatically adapted. Pickle can only read data written by trusted services; this command does not prove that any external Redis is safe. [Django Redis Configuration](https://docs.djangoproject.com/en/5.2/topics/cache/#redis) and [Framework Exact Contract](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/cache.md#django-缓存互操作) describe the boundaries.

## Observe the real files of the image cache

To run `./run.sh web image-cache`, only the current CACHE Redis is required; there is no need to query business tables, import images, or start the website. The App command itself still loads the selected service configuration and enabled facilities.

Source code [image_cache.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/image_cache.py) generates a 64×64 PNG of its own in the memory and hands the bytes to ImageCache. The result shows the Storage logical name and the actual WebP size (default 30% scaling, this image is 19×19). It doesn't tell the framework to download the image from the URL; `demo:first` is just a cache identifier.

The command checks original image bytes, WebP readability, and expiry extension on hits. After 1-second expiry, reads miss while the old file temporarily remains; the next write cleans up expired files. A deliberately corrupt image logs WebP conversion failed, but the current API preserves original bytes and returns only original. This demonstrates actual partial failure, rather than failure of the whole command. The cache is not an upload image validator.

Once all five checks output true, the command deletes its random Redis set and `/tmp` image directory and prints completion of cleanup. Files serve only this inspection and do not remain in the user's media library. Image cache capacity cleanup runs before writes by format entry, rather than enforcing a strict total image count or byte limit. See the [Reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/cache.md#图片缓存) for defaults and resource ownership.

## Observe function results and the entire HTTP response cache

After you have the database and CACHE Redis, run `./run.sh web cached-stats`. The real source code [cache_functions.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/cache_functions.py) decorates the same statistical query with `cache_async_response(timeout=1, prefix=本次随机值)` in the command. Output first, cache_hit, after_expiry: The first two calculation times are exactly the same, the third time changes after waiting 1.1 seconds. The command reads only the database, finally deletes its prefix key, closes the database and Redis; there is no need to start the website first.

Another example on the web page is in the "HTTP response cache" section below `/examples/cache/redis`. It caches the entire response, not the 30 second statistic above:

1. Click “Read cached response”. The backend queries the actual project count and returns a standard JSON replace_html action containing statistics HTML.
2. Click again within 5 seconds: project counts and computation time remain unchanged. There is no “Just queried the database” badge because the entire response is reused. Its first source label cannot describe the current read.
3. Wait 5 seconds before reading again, the calculation time should be updated; of course the number can be the same if the database remains unchanged.
4. Click “Invalidate response cache”, which POSTs to the same path and displays completed invalidation. It removes this example's cached query-parameter and language variants; the next read recomputes. It neither modifies projects nor clears the statistics key above.
5. Switch language and read; results use the current language. Return from another example through the sidebar and check that buttons still work. Signed-out requests still fail authentication; POST without valid CSRF is rejected. After dismissing the shared error message, you can operate again.

Implementation is example_cached_response/example_invalidate_response in views/cache.py. Both buttons use ordinary ExamplesPage and target `#cache-response-result`, without new TS or components. GET checks staff before the cache decorator; cached responses are isolated by request.ctx.locale. Responses contain no private user data, CSRF, or Cookies; do not copy this directly to cache personal account pages.

Both decorators read root cache.client/namespace. The public YAML does not override cache, so it uses default client=CACHE. Cache failures log a warning and continue querying/returning business results; database exceptions still propagate. This differs from direct RedisCache operations above, which do not automatically fall back. Verify hits through actual computation time; a successful database query while Redis is offline is not a hit. Command checks require accessible Redis and fail otherwise. See the [Developer Reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/cache.md#函数结果与-http-响应缓存) for signatures, key rules, and content that cannot be cached.

## Observe model cache

Model caching stores database rows per model and query, invalidating automatically after writes commit without manual key deletion. The demo enables it on `ExampleTask`: `@cached_model(partition_by=("project_id",), invalidate_on=(ExampleProject, ExampleTeam))`. See [models.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/models.py) and page logic in [model_cache.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/model_cache.py). Choose “Cache → Model Cache” to open `/examples/cache/models`, select a project, then:

1. Click "Read tasks" twice. The first time it displays "Cache miss: read from the database and stored", the second time it displays "Cache hit"; each time it displays the time taken and the hit statistics of this process so far.
2. Click “Rename its first task (ORM)” and read again: a miss, with `(ORM)` appended to the first task's title. Reading shortly after commit may show “Bypassed”: this process has not yet written invalidation to Redis, so it queries directly. Read again afterward.
3. Click “Rename a task of another project (ORM)” and read this project again: it still hits. The query fixes `project_id`, so only writes to this project's tasks invalidate it.
4. Click “Rename its first task with an UPDATE statement” and read again: it still hits, with the old title. Bulk statements do not trigger ORM events, so the cache cannot see them. Click “Invalidate the task cache” and read: a miss now shows `(SQL)`. Production code writing this way must call `ExampleTask.invalidate_cache_on_commit(session)` in the same transaction, as the demo Worker task `complete_example_task` does.
5. Click “Rename the project (ORM)” and read: a miss. The database cascades task deletion from projects and project deletion from teams (two levels of `ON DELETE CASCADE`). The cache can only learn this from project/team writes, so any update or deletion of either invalidates all task queries once.
6. Click "Restore example data" to remove the mark added by the above operation. The ORM is also used for recovery, and the relevant cache becomes invalid.

Concurrent staff operations may mix another user's reads into statistics deltas, displaying “Source unknown”. See the [Developer Reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/cache.md#模型缓存) for read/write rules, boundaries, and measured timings.

## When caching is needed

- To share recalculable results among multiple workers, use [RedisCache/redis_cache](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/cache.md).
- To cache database rows and query results and hope to automatically invalidate them after writing, use [Model Cache](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/cache.md#模型缓存).
- Only temporary results for this process can be used with MemoryCache; it does not provide cross-process Session or permission invalidation.
- Use independent namespace and limited TTL to express data ownership and staleness; shared Redis cannot be cleared to reset an example.
- The cache is updated or invalidated after the database modification is successful, and it does not claim that the two systems can commit atomically.
- Whether a cache failure degrades is determined by the business; it cannot swallow real database or calculation errors.
- For Django cache interoperability, see [Cache Reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/cache.md). Its key/codec/TTL rules cannot be confused with the native Oldman Cache.

Specific contracts for configuring operations with hits, expiration, None/False/0, multiprocessing, and resource shutdown are in the reference page. The CACHE connection is used to cache examples and does not change the original database query process of Table; TwoLevelCache is an independent CLI example and cannot be regarded as having access to all pages.

## Running the backend HTTP example

Use the same Demo that has been initialized and can be used for sign in. Enter from the sidebar "HTTP → Backend HTTP Client". The default address is `http://127.0.0.1:17997/examples/http/client`. This example does not require adding a new database table, importing additional data, or starting another Oldman service.

The upstream address in the public configuration is:

```yaml
app_settings:
  examples:
    http_base_url: https://httpbin.org
```

This is an excerpt of existing YAML and does not overwrite the entire app_settings. If the old configuration does not have this item, the default value of ExamplesSettings will be used, which can be completed by `./run.sh web settings sync`. When you need to build your own environment, change it to an httpbin-compatible instance deployed by yourself, and then restart the service; the base address can have a path prefix, but cannot have an account, password, query parameter or fragment.

Only by clicking the button can the upstream be accessed; page loading, service startup, and sidebar switching will not automatically request the external network. The public upstream will see the server exit address, Demo User-Agent, and fixed parameters, and will not receive browser sign in cookies, user input, or project database records. Public services may be unavailable, throttled, or return delayed requests early, and TLS verification cannot be turned off accordingly.

Follow this sequence:

1. Click "Read JSON". Python requests `/get` and carries fixed `example=oldman-epg-dashboard` parameters. The results area shows the actual HTTP status, Content-Type, elapsed time, and upstream JSON; not a set of demo numbers pre-populated by the page.
2. Click "Observe upstream 404". The results should clearly show the upstream 404 and failure status. The Demo page is still retained and does not jump to the Demo 404 page.
3. Click "Observe timeout". The upstream interface request is delayed for 10 seconds. In this example, the entire operation waits for about 5 seconds at most without retrying. If the upstream returns early, it should display the actual result returned; if it is indeed delayed, it should display a timeout, and it can still be operated after loading.
4. Click "Read byte stream". Requests 65536 bytes; Python counts and calculates SHA-256 chunk by chunk, displaying the actual byte count and summary when finished. Files are not saved and browser progress is not sent over SSE. Exceeding the 1 MiB limit in this example turns off the response and does not give a false full summary.
5. Read the JSON again to confirm that the previous error did not render the client unavailable. This page can be accessed from the cache page or other pages through the sidebar and checks that the same buttons still work.

There are two layers of HTTP here, which cannot be confused: the browser requests Demo, and Demo then requests the upstream. Demo returns HTTP 200 and replace_html action, indicating that the diagnosis results are sent back successfully; the upstream 404, timeout, and connection failure in the result panel are still failures and do not become successes. Failure of sign in, insufficient permissions, CSRF failure, or Demo's own program exception will still be handled by the existing authentication/shared error process.

### Source code and resource ownership

| File | Responsibility |
| --- | --- |
| [http_example.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/http_example.py) | holds the client, four requests, timeouts, diagnostic results and flow context |
| [settings.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/settings.py), [apps.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/apps.py) | Strongly typed upstream configuration and registration of Examples App |
| [views/http.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/http.py) | Sign-in/CSRF, operation whitelist, rendering of page and result fragments |
| [HTTP Template Directory](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/http) | Four buttons, target area, diagnostic text; HTML in JSON will not be executed |
| [services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py) | Initialize the HTTP Client at startup and close it on shutdown, retaining the framework's original cleanup |

There is no dedicated TS for this example: the buttons use `data-om-action="post"` and `data-om-target="#http-result"`, and the normal ExamplesPage executes the replace_html returned by the view. For the complete Python implementation, see [HTTP Reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/http-client.md#demo-中的实际使用).

Each worker owns a MultiHttpClient without user credentials, using HTTPX, 8 connections, no retries, no redirects, and TLS verification enabled. Service startup calls init_client, but actual network connections open only on the first click. Request completion closes only the current response; service shutdown calls close_client. Do not share this instance directly across users' separate upstream sign-in Cookies.

Upstream disconnections produce explicit diagnostics without disabling Session, Redis cache, or other pages. Use isolated configuration and an upstream you own for failure verification, without stopping real business services. This example does not cover multiple backend comparisons, Cookie sign-in, downloads saved through Storage, or resumable downloads; their public contracts remain in the reference.

## Call external HTTP in business

Use [MultiHttpClient](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/http-client.md) and do not duplicate another set of network layers in the business App. Make it clear who initializes, who holds the connection pool, and who closes:

- One-time commands use their own invocation lifecycle, eventually releasing the client.
- The long-running service reuses the connection pool and does not close the global client at the end of each request.
- Parsing the body after checking the HTTP status according to the upstream contract, exceptions cannot be converted to false success or empty objects.
- Write requests such as POST are not retried by default due to network failure; they may have been processed by the other party, and the business needs to clarify idempotent rules.
- URLs, authentication, proxies, and TLS come from a trusted configuration and do not treat any user-submitted URL as a secure upstream.
- Large files use streaming responses with existing Storage, without first unbounded reading into memory.

When the backend receives the business error code in JSON, it is interpreted by the backend business and is not handed over to the browser ResponseActionRunner.

## Other connections

The [Provider reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/providers.md) explains named Redis connections, Pub/Sub, and NATS publishing/RPC. Worker control messages, browser user messages, and external infrastructure have different boundaries; do not wrap them in one ambiguous MessageBus.

When supplementing the Demo, you should provide the real source, visible results, a failure path, and exit cleanup respectively; do not use a "fake upstream" that returns a fixed dictionary to pretend to complete the network wiring. For currently available operable pages, see [Demo Example Index](demo-examples.md).

<!-- source: zh/users/cache-and-http.md @ db5eb607 -->
