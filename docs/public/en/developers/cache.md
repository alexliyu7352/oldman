# Caching

`oldman.cache` caches data that can be recomputed. It does not manage Sessions, task queues, or browser messages. Redis connections themselves belong to the [Redis provider](providers.md#redis-connections). A successful cache write does not mean business data has been durably stored.

Agents: before writing code, read the [caching and networking guide (in Chinese)](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/agents/cache-and-network.md) (`docs/public/zh/agents/cache-and-network.md`). It says which interface the task needs, how to wire it and what counts as done.

Database model rows and query results are cached by `oldman.db.sqlalchemy.cache`, with automatic invalidation after writes commit; see [model caching](#model-caching).

## Choosing objects and settings

Public entry points are BaseCache, MemoryCache, RedisCache, TwoLevelCache, memory_cache, redis_cache, cache_async_response, and cache_response.

| Object | Data location | Suitable use |
| --- | --- | --- |
| `memory_cache` / `MemoryCache()` | A dictionary in the current Python process | Small temporary results that may briefly differ between workers |
| `redis_cache` / `RedisCache(...)` | The configured Redis database | Recomputable results shared across processes |
| `TwoLevelCache(memory, redis)` | Process-local memory plus Redis | Read-heavy workloads that explicitly tolerate stale local copies |

The EPG demo's public YAML explicitly configures a CACHE connection (excerpt, not a complete configuration):

```yaml
redis:
  CACHE:
    redis_url: redis://localhost:6379/2
```

The demo's statistics cache uses an explicit RedisCache object, described below, rather than reading namespace/serializer from the root cache section. The framework also supplies a process-wide `redis_cache`, which reads and binds root cache settings on first use. Importing it alone does not connect to Redis. The root cache section contains only client and serializer, without enabled or a default ttl. Its key prefix is `<core.namespace>:cache` under the service namespace and is not configured separately.

For multiple business cache spaces, construct RedisCache objects with distinct namespaces. A provider object implementing async_get_bin_conn can be passed directly; no second cache factory needs to be registered. RedisCache requires a nonempty namespace that cannot change after binding.

MemoryCache has no default capacity limit or eviction algorithm. Its default NullSerializer stores object references rather than copying dicts/lists. Do not treat it as a cross-process cache or expect automatic isolation for shared objects other code still modifies.

## Actual use in the demo

The implementation is in [apps/examples/cache_example.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/cache_example.py), called by the protected [views/cache.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/cache.py). Complete service bootstrap before running it; do not call its database functions from an uninitialized Python Shell.

Below is a continuous excerpt from that module. Omitted imports remain available in the original file: `datetime as dt`, `Literal/TypedDict/cast`, SQLAlchemy's `func/select`, the actual `ExampleProject` model, `oldman.cache.RedisCache`, and `oldman.db.db_manager`. This business code depends on the database and provider; it is not a standalone program without prerequisites.

```python
CACHE_TTL = 30
CACHE_KEY = "counts"
# This namespace owns only the Demo statistic, never Session or other cache keys.
project_cache = RedisCache(
    "CACHE",
    namespace="oldman_epg_dashboard:examples:project-statistics",
    serializer="json",
    timeout=5,
)


class ProjectStatistics(TypedDict):
    """JSON-compatible snapshot; its source is determined on each read."""

    counts: dict[str, int]
    total: int
    calculated_at: str


async def read_project_statistics(
    *, refresh: bool = False,
) -> tuple[ProjectStatistics, Literal["cache", "database"]]:
    """Use a cached snapshot unless missing or explicitly recalculating it."""
    if not refresh:
        cached = await project_cache.get(CACHE_KEY)
        if cached is not None:
            return cast(ProjectStatistics, cached), "cache"

    statistics = await calculate_project_statistics()
    await project_cache.set(CACHE_KEY, statistics, ttl=CACHE_TTL)
    return statistics, "database"


async def calculate_project_statistics() -> ProjectStatistics:
    """Read one fresh snapshot; cache and process examples share this same query."""
    # Concurrent misses may repeat this small read-only query; no lock is needed.
    async with db_manager.get_read_session() as session:
        rows = await session.execute(
            select(ExampleProject.status, func.count())
            .group_by(ExampleProject.status)
            .order_by(ExampleProject.status)
        )
        # The result has keys() — its column names — so dict() would read it as a mapping; take the rows.
        counts = dict(rows.all())
    return ProjectStatistics(
        counts=counts,
        total=sum(counts.values()),
        calculated_at=dt.datetime.now(dt.UTC).isoformat(),
    )


async def clear_project_statistics() -> int:
    """Delete just this shared Demo snapshot; do not clear the Redis database."""
    return await project_cache.delete(CACHE_KEY)
```

The returned `source` describes only this read and is not stored in Redis. The initial calculation performs one SELECT grouped by status. With no rows, counts={} and total=0, but a complete timestamped snapshot is still saved. A hit neither queries the database nor touches the TTL. Explicit refresh bypasses get, recalculates, and resets the TTL to 30 seconds.

After a successful POST, the view renders `_result.html` and calls `replace_html_response(html)`. The ordinary ExamplesPage executes the action; the target comes from the button's `data-om-target="#cache-result"`. The GET page does not query statistics. All three POST endpoints require sign-in and CSRF protection. All signed-in users share one key; this is not a private cache isolated by user.

RedisCache's timeout=5 is an operation timeout, unrelated to TTL=30. Cache/database exceptions propagate rather than becoming misses or empty statistics; existing HTTP/Feedback handling displays the failure. Clearing calls only delete. CRUD does not invalidate this example's snapshot automatically; manual refresh demonstrates data changed through existing Table/Modal operations. See [the user tutorial](../users/cache-and-http.md) for detailed instructions.

A missing key returns default. A cached None also counts as a miss, whereas 0, False, empty strings, and empty lists are valid hits. To distinguish None from a missing cache entry, wrap it in a business object such as `{"value": None}`.

## BaseCache operation contract

All operations are asynchronous. key accepts str or int. With a nonempty namespace, the actual key is `namespace:key`.

| Interface | Return value and caveats |
| --- | --- |
| `get(key, default=None, loads_fn=None)` | Decoded value or default |
| `set(key, value, ttl=..., dumps_fn=None)` | bool; overwrites an existing value |
| `add(key, value, ttl=..., dumps_fn=None)` | bool; adds only an absent key; raises ValueError if it exists |
| `multi_get(keys, loads_fn=None)` | A list in input order, with None for missing entries |
| `multi_set(pairs, ttl=..., dumps_fn=None)` | bool; pairs is a sequence of `(key, value)` pairs |
| `delete(key)` | Number of entries actually deleted |
| `delete_match(pattern)` | Number of matching entries deleted in the current namespace; pattern is a glob, not a regular expression |
| `exists(key)` | bool |
| `expire(key, ttl)` | Whether the backend set expiration; ttl=0 removes expiration |
| `ttl(key)` | Remaining seconds; -1 means no expiration, -2 means absent |
| `clear()` | Clears the namespace owned by this instance; not a general database-clearing command |
| `close()` | Releases resources owned by this instance |

Constructor defaults are timeout=5 seconds and ttl=None. Each operation also accepts a keyword timeout; timeout=None or 0 disables the operation timeout. TTL is data lifetime, not request timeout. Omitting ttl on set/add uses the constructor default; explicit None or 0 means no expiration. Use positive TTLs rather than relying on backend-specific negative-value behavior. Batch inputs must be nonempty; callers should skip empty collections.

Redis clear/delete_match uses SCAN to delete entries in batches within the current namespace, treating glob characters in the namespace literally. It is neither FLUSHDB nor a database snapshot isolated from concurrent writes. MemoryCache.clear clears its entire dictionary and timers.

RedisCache.close does not close provider connections. Shared Redis is closed during Application shutdown, or by `await redis_client.close()` in standalone scripts. MemoryCache.close discards this instance's data. Both support async with. Owners must close MemoryCache instances they create; Application closes only the global memory_cache by default.

## Serialization and errors

RedisCache defaults to pickle; the example explicitly selects json. Available names are pickle, json, msgpack, and null, case-insensitively. Classes can be imported from `oldman.serializers.cache`, or a BaseSerializer subclass instance can be passed.

- JSON/MessagePack suit structured values but do not guarantee reconstruction of arbitrary Python classes.
- Pickle can store Python objects, but only read it from trusted storage. Untrusted clients must not write these keys.
- NullSerializer performs no encoding. It suits memory or bytes/scalars already prepared for Redis; it cannot write arbitrary dicts directly to Redis.
- dumps_fn/loads_fn override only the current operation. Callers must pair compatible read/write formats; changing serializers does not convert existing data.

Connection, encoding, decoding, and timeout errors in ordinary Cache operations propagate rather than automatically returning a miss. Business code that permits fallback can catch relevant errors around its own cache reads/writes, but must not swallow actual database or business-function exceptions.

## Two-level caching has no global invalidation notifications

The actual demo is the CacheLevels Command in [cache_levels.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/cache_levels.py), run with `./run.sh web cache-levels`. It imports MemoryCache, RedisCache, and TwoLevelCache. The command owns its MemoryCache; RedisCache uses the CACHE alias, JSON, and a UUID namespace for each run. Statistics come from calculate_project_statistics above, without database writes. `levels = TwoLevelCache(memory, shared)` combines these two concrete objects without another global proxy.

It first saves a real snapshot in MemoryCache with a 0.15-second TTL to demonstrate a hit and expiration after 0.2 seconds. Then levels.set(..., ttl=30) writes both layers. A controlled child process runs `_peer` in the same module: it first calls bootstrap_service("web"), then imports the model query function. Its MemoryCache is empty, so it recalculates and updates the same Redis key. The parent prints both actual PIDs, calculated_at before/after, and local_stale=true. Reading Redis directly returns the new snapshot, while levels.get still returns the old local snapshot. Identical counts are normal: the database has not changed, and the timestamps come from two actual queries.

Only after deleting its own memory key does the parent receive the updated value from levels.get. It then shortens the Redis TTL, clears and refills memory, and waits for both layers to expire. Finally it sets and deletes again, confirming both layers are absent. Short TTLs make this finite demo observable quickly; they are not production recommendations. Every assertion checks actual Cache results. Exceptions propagate and the command exits nonzero. The parent's finally block clears only its UUID namespace and closes memory timers and this process's Redis/database connections; the child likewise closes its own connections. Cleanup does not touch the Web page's existing statistics, Sessions, or other commands' namespaces.

get reads memory first, then Redis. By default it refills memory with Redis's remaining TTL; if Redis has no expiration, neither does memory. An explicit ttl on get changes that refill's lifetime. set/delete/clear operate on Redis before current-process memory. Omitting ttl on set gives both layers no expiration rather than inheriting either constructor's default TTL.

**Other workers' existing memory copies are not invalidated by this update.** Therefore this cache is unsuitable for permissions, sign-in revocation, or billing state requiring immediate consistency. Use RedisCache directly when shared updates must be immediately visible. Do not infer broadcast subscriptions from the name TwoLevelCache.

## Function-result and HTTP-response caching

The actual function example is CachedStats in [cache_functions.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/cache_functions.py). `./run.sh web cached-stats` invokes it after service-command bootstrap. Its local asynchronous statistics function only calls calculate_project_statistics above and uses `@cache_async_response(timeout=1, prefix=prefix)`. The UUID prefix isolates runs. Two consecutive timestamps match, then change after 1.1 seconds. Final delete_match removes only this run's prefix, and finally closes the command's database and Redis resources. Here the decorator's timeout is the result TTL, not a function-execution timeout.

`@cache_async_response(timeout=3600, prefix="cache_fun_response")` caches asynchronous return values. Keys concatenate the prefix, function name, and argument strings; this is not a collision-free structural argument encoding. Give business functions distinct prefixes and avoid complex objects or unstable repr values in arguments. Cache read/write failures log warnings and continue with business execution; the function's own exceptions still propagate. Concurrent misses are not coalesced, so expensive computation may run several times simultaneously.

`@cache_response(key_prefix="response", expiration=3600, invalidate_paths=(), vary_by=None, use_pickle=True)` decorates Sanic views:

- GET/HEAD share keys built from the raw path, normalized query parameters, and vary_by results. Parameter names are sorted; repeated-value order is retained.
- Only status-200, non-streaming handler responses without Set-Cookie are saved. Stored data includes the body, status, content-type, and eligible headers, not the entire Request.
- After a POST/PUT/PATCH/DELETE handler returns normally, all query/vary versions of the current path and invalidate_paths are cleared. A returned business error still invalidates if no exception was raised. GET/HEAD cannot configure invalidate_paths.
- Placeholders in invalidate_paths come from view kwargs. Use the same key_prefix as readers.
- Cache failures log warnings and continue the original view or return its already-generated response. Business writes and invalidation do not become an atomic transaction.

It does not automatically isolate results by browser Vary, language, Cookies, permissions, or tenants. Use it only for explicitly cacheable responses. User data requires a complete vary_by, and authentication/authorization must run before a cache hit. Pages that acquire Cookies in later middleware or contain CSRF are not suitable merely because the handler has no Set-Cookie yet.

The actual Web consumer remains [views/cache.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/cache.py), not another hypothetical view. GET `/examples/cache/response` uses router.get → login_required → cache_response. RESPONSE_PREFIX is a dedicated example constant, expiration=5, use_pickle=False, and vary_by returns request.ctx.locale. On a miss it queries SQL, asynchronously renders `_response_result.html`, and calls replace_html_response. Hits reuse the whole JSON action response. It contains only project counts/timestamps shared by all signed-in users, without identity, tokens, or Set-Cookie. A hit never skips permission checks.

POST on the same path uses router.post → csrf_protect → login_required → cache_response with the same key_prefix/use_pickle. After the handler returns an invalidation-result fragment, the decorator deletes all GET query/locale variants without duplicated handwritten deletion rules. The button targets #cache-response-result, separately from #cache-result, using data-om-action and the existing replacement lifecycle. Statistics HTML is escaped normally, translation happens during fragment generation, and the cache key preserves language isolation. The original 30-second RedisCache page and this 5-second HTTP cache do not invalidate one another.

Both decorators use the root redis_cache, whose connection comes from settings.cache.client and whose keys live under `<core.namespace>:cache`. The public demo YAML does not override cache, whose default client is CACHE. use_pickle=False controls HTTP-response envelope encoding rather than changing providers. Web requests leave shared pools open for Application shutdown; CLI examples close their own connections in finally. Real hits/expiration, POST invalidation, language isolation at the same URL, anonymous 401, and invalid-CSRF 403 have been verified in an isolated demo. See [the user tutorial](../users/cache-and-http.md#observe-function-results-and-the-entire-http-response-cache) for instructions.

`oldman.cache.utils` also supplies underscore-joined key helpers: set_cache/get_cache/get_cache_expiration/delete_cache/delete_cache_many. They use the native redis_cache namespace, not Django keys, and provide no distributed locks.

## Django cache interoperability

This is the specific purpose of `oldman.compat.django.cache`, not Oldman's native default format. Both sides must use the same Redis database and Django's built-in Redis backend with default empty KEY_PREFIX, VERSION=1, and default codec. Custom KEY_FUNCTION, prefixes, versions, and third-party backend codecs are unsupported. [Django cache configuration](https://docs.djangoproject.com/en/5.2/topics/cache/#redis)

Oldman still uses the **binary** provider selected by settings.cache.client, but ignores its native namespace/serializer and reads/writes `:1:<key>`. Ordinary integers retain integer encoding; bool/None/other values use Pickle. Redis and its writers must be trusted.

The actual entry point is DjangoCacheDemo in the demo's [django_cache.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/django_cache.py). For execution and optional isolated installation, see [the user tutorial](../users/cache-and-http.md#optional-exchange-cache-with-django). It calls importlib.import_module("django.core.cache.backends.redis") only during Command execution. Missing Django produces a clear module-import explanation rather than making all of commands.py unloadable because of an optional dependency.

It reads URL and protocol from settings.redis[settings.cache.client] and constructs a real backend.RedisCache(..., {"OPTIONS": {"protocol": config.protocol}}). Django's aget/aset/adelete use its native asynchronous entry points; this example does not call synchronous network methods directly on the event loop. Project statistics come from calculate_project_statistics. incoming/outgoing use UUID keys for this run, and missing is a distinct object sentinel. Excerpt from the actual loop:

```python
                await django.aset(incoming, value, timeout=30)
                received = await get_django_cache(incoming, missing)
                assert received == value and type(received) is type(value)
                await set_django_cache(outgoing, value, lock_timeout=30)
                received = await django.aget(outgoing, missing)
                assert received == value and type(received) is type(value)
```

value iterates through real statistics and boundary values; no homemade byte generator stands in for Django. The command also verifies permanent None, missing keys, short-TTL expiration, deletion with 0/-1, version=2 isolation, and errors from corrupted pickle. It never clears the entire database. finally deletes its known version=1/2 keys individually. Django 5.2's Redis backend close does not actually release pools, so this optional example explicitly disconnects native pools in `_cache._pools`, then closes the Oldman provider/database. These Django internals are used only for example resource cleanup and do not enter Oldman's production adapter.

Here lock_timeout means expiration seconds, not a lock: None never expires; 0 or negative values delete the existing key. This **differs** from native Cache ttl=0. get_django_cache can distinguish missing keys from stored None with an explicit default. Corrupt-data decoding errors propagate rather than becoming misses.

set_api_cache/get_api_cache/delete_api_cache/delete_api_cache_many in this module use underscore concatenation and Django keys. Its cache_async_response also writes Django keys but does not swallow Redis errors. Random-ID mapping helpers are not secure token generators and must not be used for authentication.

## Image caching

`oldman.cache.images.ImageCache(storage=None)` stores originals/WebP through existing Storage and expiration metadata in a Redis sorted set using settings.cache.client. Bootstrap before construction; default Storage also requires storages.init_app. Storage can be passed explicitly.

`await cache_image(url, image_content)` accepts bytes already obtained and returns a format-to-logical-filename dictionary. It does not download the URL. `await get_cached_image(url)` returns still-valid filenames or None; hits extend their lifetime. Defaults are cache_timeout=30 seconds and resize_percent=30. Expiration cleanup runs on image writes, not as an automatic background service. Count cleanup does run before writing: max_cache_size defaults to 10000 and counts **format-file entries** in the Redis set. A subsequent write can add original and WebP entries, so this is neither an exact image count nor a total-byte limit, and it provides no hard capacity guarantee under concurrent writes.

The Redis image-set key is `<core.namespace>:image_cache`, isolated by service namespace. Storage names still start with `image_cache/`; applications sharing Storage must isolate their storage locations themselves. Business code must select download routes for returned logical names rather than treating them as absolute URLs.

The actual `ImageCacheDemo` in [image_cache.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/image_cache.py) runs through `./run.sh web image-cache`. Pillow generates its own PNG bytes, TemporaryDirectory supplies a FileSystemStorage root, and ImageCache(storage=storage) selects it explicitly without global storages.init_app. cache_prefix is a single-level random directory name, and cache_set_key is random for this run. Neither default user media directories nor shared image indexes are touched.

The command first calls cache_image("demo:first", content), reads the original with `async with await storage.open(name)` to compare bytes, and confirms the other output is recognized as WebP. cache_timeout=1 second only speeds the demonstration; a hit actually checks that the Redis score increases. After expiration, get returns None while files remain. Only the next cache_image("demo:second", content) deletes old files and set entries. Do not describe this sequence as automatic scheduled background deletion. Finally it deliberately passes non-image bytes: the current implementation saves original, logs the WebP failure, and returns only original. It is neither upload validation nor a guarantee that failure saves nothing.

ImageCache owns no connection pool and has no close interface. The command's finally block deletes its set and closes this process's Redis provider; TemporaryDirectory removes all files from this run. Normal output is `Image Demo temporary files removed.` When adapting it for Web services, leave shared providers open for Application shutdown. This example performs no database reads/writes and introduces no new Storage facade or image downloader.

## Model caching

`oldman.db.sqlalchemy.cache` caches model rows and query results in Redis using `settings.cache.client`, with keys under `<core.namespace>:model_cache`. Unlike the caches above, it does not require callers to delete keys: ORM writes automatically invalidate affected entries after commit. The EPG demo enables it for `ExampleTask`; `/examples/cache/models` demonstrates the invalidation rules below. See [the user tutorial](../users/cache-and-http.md#observe-model-cache) for instructions. `Channel` / `Programme` in this section are illustrative models, not demo files.

### Enabling and calling

Inherit from `CacheableModel` and apply `@cached_model(...)`. Only explicit calls to the cache methods below read/write the cache. `db_manager.get_session()`, `get_read_session()`, `WriteSession`, and their ordinary queries do not use caching or execute extra code merely because a cache exists.

```python
from datetime import datetime

from sqlalchemy import ForeignKey, String, select
from sqlalchemy.orm import Mapped, mapped_column

from oldman.db import db_manager
from oldman.db.sqlalchemy.cache import CacheableModel, cached_model


@cached_model(partition_by=("channel_id",), invalidate_on=(Channel,))
class Programme(CacheableModel):
    __tablename__ = "programme"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channel.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(80))
    starts_at: Mapped[datetime]


async def read_guide(day_start: datetime) -> None:
    async with db_manager.get_read_session() as session:
        rows = await Programme.cached_filter(session, Programme.channel_id == 5, Programme.starts_at >= day_start)
        one = await Programme.cached_get(session, id=10)
        many = await Programme.cached_get_many(session, [1, 2, 3])
        plain = (await session.execute(select(Programme))).scalars().all()  # Ordinary query; bypasses the cache
```

`Channel` is another model in the same App, referenced with `ondelete="CASCADE"`, so it must appear in `invalidate_on` (see "Writes" below).

| `@cached_model` parameter | Default | Meaning |
| --- | --- | --- |
| `instance_expire_seconds` | 3600 | Expiration in seconds for row and field-lookup entries |
| `query_expire_seconds` | 300 | Expiration in seconds for query-result entries; `cached_filter(expire_seconds=...)` overrides it per call |
| `partition_by` | `()` | Partition columns; see [partitions](#partitions) |
| `invalidate_on` | `()` | ORM updates/deletions of these models invalidate all entries for this model |
| `db_manager` | Process-wide `db_manager` | Supplies the cache connection pool on misses; the caller's session must connect to the same database |

| Method | Return value | Notes |
| --- | --- | --- |
| `cached_get(session, *, use_cache=True, **fields)` | One row or None | Looks up one row by fields. The entry records that row's primary key and is invalidated by writes to it. Missing rows are not cached. Multiple matches raise `sqlalchemy.exc.MultipleResultsFound` with or without caching, so use only unique fields |
| `cached_get_many(session, ids, *, use_cache=True)` | A primary-key-to-row dict retaining the caller's key representation (`"1"` remains `"1"`, on hits and misses) | One entry per primary key, invalidated only by writes to that row; absent database keys are excluded |
| `cached_filter(session, *conditions, page=None, page_size=None, use_cache=True, expire_seconds=None)` | A list, or PageResult when both `page` and `page_size` are supplied | Generated statements have no ORDER BY |
| `Programme.get_cache_manager().execute_query(session, statement, page=None, page_size=None, *, use_cache=True, expire_seconds=None)` | As above | Use for statements requiring ordering, LIMIT, or other features unavailable through `cached_filter` |

With caching enabled, hits, misses, and bypasses described below all return **detached snapshots**: complete column attributes and primary-key identity, but no attachment to the caller's session. Accessing unloaded relationships raises `DetachedInstanceError` rather than silently returning empty data. `use_cache=False` performs an ordinary query and returns objects attached to the caller's session. All four methods use this same keyword-only switch. `cached_get(session, True)` raises `TypeError` rather than treating True as a query condition.

Snapshots are for reading. They come from committed data and may be newer than the caller transaction's view or behind by one invalidation window. For read-then-modify logic, read through the ordinary session (with `with_for_update()` if needed) before modifying. Calling `save(session)` on a snapshot can write it back and trigger normal invalidation. `update(session, ...)` instead raises `InvalidRequestError` because the snapshot is not in that session.

### Reads

| Situation | Behavior |
| --- | --- |
| Hit | One Redis round trip; no database connection |
| Miss | Borrows a cache-pool connection, queries in a new short transaction (count and page share a transaction when paginating), and writes to Redis |
| Caller session has uncommitted changes to this model (inserts, updates, deletes, or an `invalidate_cache_on_commit` call) | Queries through the caller's session to see its changes; neither reads nor writes the cache |
| This process just committed this model and invalidation has not reached Redis | Queries through the caller's session; neither reads nor writes the cache |
| Redis error | Queries through the caller's session and logs WARNING |
| No cache-pool connection available within 1 second | Queries through the caller's session without writing the cache and logs WARNING |

Data written to Redis always comes from a new cache-pool transaction, never the caller's session. The caller's transaction may have started earlier and retain an old snapshot, or contain uncommitted writes. Caching either could expose stale data or never-committed rows to other requests.

### Writes

Insert, update, and delete code stays unchanged; invalidation happens automatically after commit. Only writes bypassing the ORM unit of work need explicit declarations.

| Write operation | Invalidation |
| --- | --- |
| `session.add(obj)`, attribute changes, `session.delete(obj)`, `merge`, and `save()` / `update()` / `delete()`, after commit | Automatic: the row, its partitions before/after the write, and all non-partitioned queries |
| `session.execute(insert(M)...)`, `update(M)...`, `delete(M)...`, raw SQL | These statements emit no mapper events and are invisible to the cache. Call `M.invalidate_cache_on_commit(session)` in the same transaction: commit invalidates the whole model; rollback does nothing |
| Database cascades: foreign keys with `ondelete="CASCADE"` / `"SET NULL"` / `"SET DEFAULT"` or `onupdate="CASCADE"` | Include the referenced model in `invalidate_on`; ORM updates/deletions of that target invalidate this entire model. Follow any such foreign-key chain to its end. Deleting a team can delete its projects and therefore their tasks, so tasks need `invalidate_on=(ExampleProject, ExampleTeam)`. Missing a level raises `TypeError` at `@cached_model` declaration, as does a table not yet defined along that chain (import its model first). Self-referencing cascades (tree-table `parent_id`) need no entry and cannot have one: every update/deletion then invalidates the entire model. Lower hit rates on tree tables are required for correctness. Bulk updates/deletions of a target likewise require this model's `invalidate_cache_on_commit` |
| Other programs, manual database changes, database triggers | `await M.invalidate_cache()` immediately invalidates all entries for the model |

Commit does not wait for Redis. After the outermost transaction commits, a task invalidates entries with one pipeline, waiting up to 5 seconds. Releasing a savepoint (`begin_nested()`) does not invalidate; it waits for the outermost commit, otherwise another request could repopulate old data before commit. Transactions ending without commit (rollback or closing an uncommitted session) do not invalidate. Rolling back only a savepoint, or a flush failure within one, retains tracking records. The outer commit also invalidates writes undone in the savepoint: extra invalidation rather than missed invalidation. If the old partition value is unavailable during a write (an expired attribute assigned directly), the entire model is invalidated.

### Partitions

Without `partition_by`, any model write invalidates all its cached queries; row and field lookups are invalidated only by their own row. Models with frequent reads and writes can declare partition columns, usually foreign keys:

- If every partition column appears in the query WHERE's top-level AND as `column == value` or `column IS NULL` (boolean columns also accept `flag == True`, `flag.is_(False)`, bare `flag`, and `~flag`), only that partition invalidates the query. Only rows belonging to it before or after a write affect it. Additional conditions are allowed; results remain within the partition.
- Other queries (missing partition columns, `IN` / `OR` / range comparisons, or subqueries in WHERE) are invalidated with the whole model.
- Partition columns must be integers, booleans, UUIDs, or enums, checked at declaration. Strings, dates/times, decimals, and floats are unsupported: database collation/precision rules (case insensitivity, trailing spaces, truncation) differ from Python `==` and could miss invalidation.

### Boundaries

| Error point | Cause |
| --- | --- |
| `TypeError` at `@cached_model` declaration | Not a `CacheableModel` subclass; not a single-column primary key; mapped inheritance; unsupported column types (project-defined `TypeDecorator`, `ARRAY`, etc.); deferred columns (`deferred=True`, not loaded with the row, preventing complete caching); missing/invalid partition columns; a table in a database-cascade foreign-key chain absent from `invalidate_on` or not yet defined |
| `ValueError` when calling a cache method | Statement reads other tables (JOIN/subquery), selects only some columns, uses `with_for_update()`, or has loader options (`selectinload`, `load_only`, etc.); callable-valued bind parameters (`bindparam(..., callable_=...)`, whose computed values are absent from SQLAlchemy's statement cache key and could share a cache entry); caller session connects to a database different from `db_manager`; in-memory SQLite (the cache-pool connection sees a different empty database) |

Supported column types are integers, strings, booleans, floats, `Numeric`, dates, times, datetimes, `Interval`, `Uuid`, enums, `LargeBinary`, and JSON (including `JSONText`). Values and types match direct database reads: dates remain `datetime`, decimals remain `Decimal` (including `Float(asdecimal=True)`), and floating-point NaN and positive/negative infinity are preserved. If an enum column is assigned a member-name string in the same transaction, its snapshot restores the enum member. Adding/removing/renaming columns or changing their type representation changes cache keys, so new deployments do not read rows saved by old code. Changing `partition_by` or `invalidate_on` does not change keys. During rolling deployment, old/new processes invalidate by their own rules, so old-process writes may leave stale rows cached for new processes until expiration. Old code cannot know new rules; this limitation is unavoidable. Run `await M.invalidate_cache()` once after the entire deployment completes.

The following do not raise errors and require user attention:

- Cache keys contain statement structure and parameter values. Time-dependent conditions such as `Programme.starts_at >= func.now()` generate the same key every time and keep returning the result from cache population. Pass time as a parameter, rounded to an acceptable granularity such as minutes; otherwise every call creates a new key and never hits.
- All columns are stored in Redis as plaintext JSON. Do not enable caching on models containing password hashes, tokens, or keys.
- Commits writing cached models must run in the event-loop thread. A commit in a thread without a running event loop (synchronous scripts or `asyncio.to_thread` code) cannot start invalidation and only logs ERROR.

### Timing windows

- Another process may read an old value between write commit and Redis invalidation (roughly one Redis round trip plus background-task scheduling). This process has no such window: its cached reads for that model query the database directly until invalidation finishes.
- Invalidation failure (Redis error or exceeding 5 seconds) does not affect committed writes and logs ERROR. Affected entries may remain stale until expiration: 300 seconds by default for queries and 3600 for rows.
- At process exit, unfinished invalidations are cancelled when the event loop ends. Framework CLI commands, Web/long-lived services, and Taskiq Workers wait for this process's invalidations before closing Redis (up to 5 seconds each). Cancellation while waiting, such as Ctrl+C, still closes resources. Scripts using `asyncio.run` or `bootstrap_service()` must call `await wait_for_invalidations()` (from `oldman.db.sqlalchemy.cache`) before exit, or invalidations from their last commits may be lost.
- After Redis evicts or expires an invalidation counter key, its rebuilt counter uses a new random value. Old entries become misses rather than coming back to life.

### Cache connection pool

Cache misses query through a separate pool inside `DatabaseManager`, created lazily on the first miss with the same database and engine options. It has `database.cache_pool_size` connections (default 5, no overflow), waits at most `database.cache_pool_timeout` seconds (default 1.0), and is released by `close()`. Requests already occupy a main-pool connection. Borrowing a second from that pool can make concurrent requests wait on one another; a separate pool avoids that contention. If no connection becomes available, this read uses the caller's session.

```yaml
database:
  cache_pool_size: 5
  cache_pool_timeout: 1.0
```

Both values must exceed 0. They are read when the cache pool is first created; changes require a service restart. Explicit `DatabaseManager` construction can override them with same-named parameters, also strictly positive; otherwise construction raises `ValueError`. Each service process may consume up to `cache_pool_size` additional database connections. Include them when assessing database connection limits.

### Is caching worthwhile?

Local measurements used Redis over a Unix socket, a SQLite file database, and 50 rows queried by channel, over two runs.

| Operation | Time |
| --- | --- |
| `cached_filter` hit | 578–607 µs |
| Same query executed directly on the session | 554–581 µs |
| `cached_filter` miss (database query plus cache write) | 1.5–1.7 ms |
| One commit's invalidation (background, one pipeline) | About 225 µs |

Hits are about as fast as simple local SQLite queries. Time goes into the Redis round trip, cache-key generation, and restoring 50 objects. Hits save database connections and computation. Caching is worthwhile when queries themselves are slow (large tables/complex conditions), the database is remote, or its pool is under pressure. Do not enable it for write-heavy, read-light models: a miss costs about three times a direct query.

Inspect actual hit rates through `Programme.get_cache_manager().stats`. It returns a `CacheStats` counter snapshot since this process started, counting each entry read (`cached_get_many` counts per primary key). `use_cache=False` is excluded:

| Field | Meaning |
| --- | --- |
| `hits` | Returned from Redis |
| `misses` | Queried through the cache pool and written to cache (absent rows are not written) |
| `bypassed` | Caller has uncommitted model changes or this process has unfinished invalidation; queried through the caller's session |
| `fallbacks` | Redis error or unavailable cache-pool connection; queried through the caller's session |

Counters only increase. Compare snapshots to measure an interval; each process counts independently. Counter overhead is about 0.1 µs per increment, with no observable effect on measured hit time.

<!-- source: zh/developers/cache.md @ 84e6ddf1 -->
