"""Redis cache for SQLAlchemy models: single rows by primary key or unique fields, and query results.

A model opts in with ``@cached_model``; only the explicit ``cached_*`` calls and
``AsyncQueryCache.execute_query`` read or fill the cache, every other query goes to the
database as usual. What the cache returns is a detached, read-only snapshot of each row.

Correctness rests on generations rather than deletes. Every entry records the values of the
generation counters it depends on when it was filled; a read is a hit only when those values
are still current. A committed write only increments counters - the model's ``any``, the
written rows' ``row:<pk>``, the partitions it left and entered - and never has to find the
entries it affects. Entries are filled only from the database manager's own cache pool, in
a transaction that starts after the generations were read, so a concurrent write costs at
most one extra miss and never leaves stale data under a current generation.
"""

__author__ = "alex"

import asyncio
import enum
import hashlib
import secrets
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any, ClassVar, Generic, Self, TypeVar, cast

import orjson
from redis.exceptions import RedisError
from sqlalchemy import (
    Column,
    Enum,
    Select,
    Table,
    event,
    inspect,
    select,
)
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper, Session, SessionTransaction, configure_mappers, make_transient_to_detached, object_session
from sqlalchemy.orm.attributes import instance_dict
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import AsBoolean, BinaryExpression, BindParameter, BooleanClauseList, False_, Null, True_
from sqlalchemy.sql.selectable import ScalarSelect, SelectBase, Subquery

from oldman.db.schemas import PageResult
from oldman.db.sqlalchemy.codec import column_codec
from oldman.db.sqlalchemy.models import DatabaseModel
from oldman.logging import logger
from oldman.providers.redis import redis_client, redis_key

if TYPE_CHECKING:
    from oldman.db.session import DatabaseManager

# 使用具体的 DatabaseModel 作为边界,而不是 Protocol
T = TypeVar("T", bound=DatabaseModel)
R = TypeVar("R")

#: A generation key lives this long after its last write. One that expires or is evicted comes
#: back as a new random value, which no entry cached against the old one can match.
GENERATION_TTL = 7 * 24 * 3600
#: How long the invalidation after a commit may take before it is abandoned and logged.
INVALIDATION_TIMEOUT = 5.0

#: session.info keys: the writes a transaction made to cached models, and whether this session
#: object already has the listeners that turn them into invalidations or drop them.
_RECORDS = "oldman.model_cache.records"
_LISTENING = "oldman.model_cache.listening"

#: Invalidations this process has started and not finished, by model. While a model has one,
#: cached reads of it go to the database: a request that just committed must see its write.
_pending_invalidations: Counter[str] = Counter()
#: The invalidation tasks themselves, held until they end (see _spawn_invalidation).
_invalidation_tasks: set[asyncio.Task[None]] = set()

_REDIS_ERRORS = (RedisError, OSError, asyncio.TimeoutError)


class _Unknown:
    """A value the flush did not load, so the write cannot say which partition it touched."""


_UNKNOWN = _Unknown()


def _configured_cache_alias() -> str:
    from oldman.conf import settings

    return settings.cache.client


async def _cache_redis_connection() -> Any:
    return await redis_client.using(_configured_cache_alias()).async_get_bin_conn()


def _model_cache_name(model: type) -> str:
    """Name a model in cache keys by its import path, not its bare class name.

    Two Apps may each define a `Category` (one of them with an explicit `__tablename__`).
    Keyed by `__name__`, both read and invalidate one set of keys and serve each other's
    rows. The import path is unique within a process and identical in every process that
    runs the same code, which is what a shared cache needs.
    """
    return f"{model.__module__}.{model.__qualname__}"


def model_primary_key_value(instance: DatabaseModel) -> Any:
    """Return the value of a model's single mapped primary key."""
    primary_keys = inspect(type(instance)).primary_key
    if len(primary_keys) != 1 or primary_keys[0].key is None:
        raise ValueError("SQLAlchemy cache requires exactly one named primary key column")
    return getattr(instance, primary_keys[0].key)


class RowCodec:
    """Encode a loaded row as JSON-native values and rebuild it as a detached snapshot.

    Built from the mapper's columns when the model is declared, so an unsupported column
    type fails at import rather than on the first cached read. Every column must be loaded
    to be encoded: a row missing one (``load_only``, a deferred column) is not cached, since
    reading it back would show the missing value as None.
    """

    def __init__(self, model: type) -> None:
        mapper: Mapper[Any] = inspect(model)
        if mapper.inherits is not None or mapper.polymorphic_on is not None:
            raise TypeError(f"{model.__name__} uses mapper inheritance, which the model cache does not support")
        primary_key = [key for key, column in mapper.columns.items() if column.primary_key]
        if len(primary_key) != 1:
            raise TypeError(f"{model.__name__} needs exactly one primary key column to be cached")
        self.mapper = mapper
        self.primary_key = primary_key[0]
        self.columns: list[tuple[str, Callable[[Any], Any], Callable[[Any], Any]]] = []
        self.kinds: dict[str, str] = {}
        #: Column name to attribute key: a WHERE clause names columns, a row names attributes.
        self.keys_by_column: dict[str, str] = {}
        for key, column in mapper.columns.items():
            if not isinstance(column, Column) or column.table is not mapper.local_table:
                raise TypeError(f"{model.__name__}.{key} is not a column of {mapper.local_table}; the model cache stores table columns only")
            # get_property, not column_attrs: the decorator runs while the module is still defining
            # classes, and column_attrs configures every mapper, failing on a relationship to a later one.
            if getattr(mapper.get_property(key), "deferred", False):
                # Never loaded with the row, so every cached read would find the row incomplete.
                raise TypeError(f"{model.__name__}.{key} is deferred; the model cache stores complete rows, so it cannot cache this model")
            kind, encode, decode = column_codec(column)
            self.columns.append((key, encode, decode))
            self.kinds[key] = kind
            self.keys_by_column[column.name] = key
            if key == self.primary_key:
                self.encode_primary_key = encode
        #: Changes whenever a column is added, removed, renamed or changes representation, so a
        #: deploy that changes the model never reads rows cached by the previous code.
        #: Not fixed (G3-3): ``partition_by`` and ``invalidate_on`` are not part of it. During a rolling
        #: deploy that changes them, old processes invalidate by the old rules and bump counters the new
        #: entries do not depend on, so a new process can keep a stale entry until it expires. Putting the
        #: rules into the key would not help, as the old code still writes by its own rules; the docs ask
        #: for ``M.invalidate_cache()`` once the deploy has finished.
        self.fingerprint = hashlib.sha1(orjson.dumps(sorted(self.kinds.items())), usedforsecurity=False).hexdigest()[:12]

    def encode(self, instance: Any) -> dict[str, Any]:
        loaded = instance.__dict__
        missing = [key for key, _, _ in self.columns if key not in loaded]
        if missing:
            raise ValueError(f"{type(instance).__name__} row has unloaded columns {missing}; the model cache stores complete rows only")
        return {key: None if loaded[key] is None else encode(loaded[key]) for key, encode, _ in self.columns}

    def decode(self, data: dict[str, Any]) -> Any:
        """A detached instance: it has an identity, and reaching a relationship raises instead of reading as empty."""
        if not self.mapper.configured:
            # Attribute instrumentation is completed by mapper configuration, which normally
            # happens on the first query; a snapshot can be built before any query ran.
            configure_mappers()
        instance = self.mapper.class_manager.new_instance()
        # Filled the way the ORM fills a loaded row: into the instance dict, then committed as
        # a whole by make_transient_to_detached - twice as fast as set_committed_value per column.
        instance_dict(instance).update({key: None if data[key] is None else decode(data[key]) for key, _, decode in self.columns})
        make_transient_to_detached(instance)
        return instance


class _Invalid:
    """A partition value that does not have the column's own Python type."""


_INVALID = _Invalid()


def _partition_normalizer(key: str, kind: str, column: Column[Any]) -> Callable[[Any], Any]:
    """Turn a partition column's value into the JSON value its generation key is named by.

    Only types whose Python equality is the database's equality qualify. Strings do not: a
    case- or accent-insensitive collation matches rows Python's `==` would not, so a write
    to `News` would miss the query cached for `news`. Floats, decimals and datetimes can be
    rounded by the database. Any of those used in a condition makes the query whole-model.
    """
    if kind == "int":
        return lambda value: value if value is None or type(value) is int else _INVALID
    if kind == "bool":
        return lambda value: value if value is None or type(value) is bool else _INVALID
    if kind == "uuid":

        def normalize_uuid(value: Any) -> Any:
            if value is None or isinstance(value, uuid.UUID):
                return None if value is None else str(value)
            try:
                return str(uuid.UUID(str(value)))
            except ValueError:
                return _INVALID

        return normalize_uuid
    if kind.startswith("enum:"):
        members = cast(type[enum.Enum], cast(Enum, column.type).enum_class)

        def normalize_enum(value: Any) -> Any:
            if value is None:
                return None
            if isinstance(value, members):
                return value.name
            return value if isinstance(value, str) and value in members.__members__ else _INVALID

        return normalize_enum
    raise TypeError(f"partition column {key!r} is {kind}; only integer, boolean, UUID and enum columns compare in the database exactly as in Python")


def _and_terms(clause: Any) -> Iterator[Any]:
    """The terms of a WHERE clause's top-level AND, nested ANDs flattened."""
    if isinstance(clause, BooleanClauseList) and clause.operator is operators.and_:
        for inner in clause.clauses:
            yield from _and_terms(inner)
    else:
        yield clause


def _fixed_values(term: Any) -> Iterator[tuple[Any, Any]]:
    """The (column, value) pairs one WHERE term pins a column to.

    `column == value`, `column IS NULL`, and for booleans the spellings SQLAlchemy code
    usually writes: `flag == True`, `flag.is_(False)`, a bare `flag` and `~flag`. Only
    rows holding that value can match, so the term keeps the query inside its partition.
    """
    if isinstance(term, AsBoolean):
        if term.operator in (operators.is_true, operators.is_false):
            yield term.element, term.operator is operators.is_true
        return
    if not isinstance(term, BinaryExpression) or term.operator not in (operators.eq, operators.is_):
        return
    for column, other in ((term.left, term.right), (term.right, term.left)):
        if isinstance(other, Null):
            yield column, None
        elif isinstance(other, True_ | False_):
            yield column, isinstance(other, True_)
        elif isinstance(other, BindParameter) and other.callable is None and not other.expanding:
            yield column, other.effective_value


def _new_generation() -> int:
    """A random starting value: a key recreated after eviction never repeats an old one (62 bits leave room to count)."""
    return secrets.randbits(62)


def _token(encoded: Any) -> str:
    """An encoded value as a generation key names it: a string as it is, anything else as JSON (`5`, `true`)."""
    return encoded if isinstance(encoded, str) else orjson.dumps(encoded).decode()


def _generation_values(raw: Iterable[Any]) -> list[str]:
    return [value.decode() if isinstance(value, bytes) else str(value) for value in raw]


async def _bump(keys: Iterable[str]) -> None:
    """Advance each generation, creating it at a random value first if Redis no longer has it."""
    conn = await _cache_redis_connection()
    pipe = conn.pipeline()
    for key in sorted(keys):
        pipe.set(key, _new_generation(), nx=True, ex=GENERATION_TTL)
        pipe.incr(key)
        pipe.expire(key, GENERATION_TTL)
    await pipe.execute()


@dataclass
class _PendingInvalidation:
    """What one transaction's writes to one cached model require once it commits."""

    manager: "AsyncQueryCache[Any]"
    rows: set[str] = field(default_factory=set)
    partitions: set[tuple[Any, ...]] = field(default_factory=set)
    everything: bool = False

    def keys(self) -> set[str]:
        manager = self.manager
        if self.everything:
            # Every entry of the model depends on its epoch.
            return {manager._generation_key("epoch")}
        keys = {manager._generation_key("any")}
        keys.update(manager._generation_key(f"row:{pk}") for pk in self.rows)
        keys.update(manager._generation_key(manager._partition_scope(values)) for values in self.partitions)
        return keys


def _pending_for(session: Session, manager: "AsyncQueryCache[Any]") -> _PendingInvalidation:
    """This transaction's record for one model; the first one attaches the commit listener to this session only."""
    records: dict[str, _PendingInvalidation] | None = session.info.get(_RECORDS)
    if records is None:
        records = session.info[_RECORDS] = {}
        if not session.info.get(_LISTENING):
            event.listen(session, "after_commit", _after_commit)
            event.listen(session, "after_transaction_end", _after_transaction_end)
            session.info[_LISTENING] = True
    pending = records.get(manager.name)
    if pending is None:
        pending = records[manager.name] = _PendingInvalidation(manager)
    return pending


def _after_commit(session: Session) -> None:
    # Releasing a savepoint fires after_commit too, while the transaction around it is still
    # open: invalidating then lets another request store the old rows again before the commit.
    if session.in_nested_transaction():
        return
    for pending in session.info.pop(_RECORDS, {}).values():
        _spawn_invalidation(pending)


def _after_transaction_end(session: Session, transaction: SessionTransaction) -> None:
    """The outermost transaction ended without committing - rolled back, or the session closed - so nothing is invalidated.

    A savepoint's end keeps the records, and so does a failed flush: its subtransaction is
    neither nested nor outermost. A committed transaction already took its records in
    ``_after_commit``. A savepoint rolled back inside a committed transaction still costs its
    rows one invalidation - an extra miss, never a stale entry.
    """
    if transaction.parent is None:
        session.info.pop(_RECORDS, None)


def _spawn_invalidation(pending: _PendingInvalidation) -> None:
    """Start the invalidation as a task this module holds until it ends; the commit does not wait for Redis.

    Held here rather than by BackgroundTaskManager: the manager cancels its tasks when a service
    stops, and a cancelled invalidation leaves entries stale until they expire. The framework calls
    ``wait_for_invalidations()`` before it closes Redis instead. The strong reference in
    ``_invalidation_tasks`` keeps the loop's weak one from letting the task be collected early.
    """
    name = pending.manager.name
    keys = pending.keys()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError as exc:
        logger.error("Model cache %s: cannot invalidate after commit (%s); its cached entries may be stale until they expire", name, exc)
        return
    task = loop.create_task(_apply_invalidation(name, keys), name=f"model-cache-invalidation:{name}")
    _invalidation_tasks.add(task)
    # Counted only once the task exists, and released by a done callback, which runs even if
    # the task is cancelled before it starts - a finally inside it would not.
    _pending_invalidations[name] += 1
    task.add_done_callback(partial(_finish_invalidation, name))


def _finish_invalidation(name: str, task: asyncio.Task[None]) -> None:
    _invalidation_tasks.discard(task)
    _pending_invalidations[name] -= 1
    if _pending_invalidations[name] <= 0:
        del _pending_invalidations[name]
    if task.cancelled():
        logger.error("Model cache %s: invalidation was cancelled; its cached entries may be stale until they expire", name)
    elif (error := task.exception()) is not None:
        logger.error("Model cache %s: invalidation failed (%r); its cached entries may be stale until they expire", name, error)


async def _apply_invalidation(name: str, keys: set[str]) -> None:
    try:
        await asyncio.wait_for(_bump(keys), INVALIDATION_TIMEOUT)
    except _REDIS_ERRORS as exc:  # includes TimeoutError: asyncio.TimeoutError is TimeoutError
        logger.error("Model cache %s: invalidation failed (%s); its cached entries may be stale until they expire", name, exc)


async def wait_for_invalidations() -> None:
    """Wait until the invalidations this process started after its commits have reached Redis.

    Call it before closing Redis or leaving the event loop - the end of a script, say. The
    framework's CLI commands, services and Taskiq workers call it themselves when they stop.
    Each invalidation gives up after ``INVALIDATION_TIMEOUT`` seconds, so this returns within
    that long of the last commit; an invalidation that fails is logged, not raised.
    Once it returns, cached reads of those models no longer bypass the cache.
    """
    loop = asyncio.get_running_loop()
    # A task leaves the set in its done callback, which also ends the post-commit bypass; that
    # callback runs one loop turn after the task finishes, so waiting for "done" returned early.
    while running := [task for task in _invalidation_tasks if task.get_loop() is loop]:
        # Commits made while waiting start new invalidations; wait for those too.
        await asyncio.wait(running)


def _values(state: Any, key: str, when: str) -> list[Any]:
    """A column's value before (`old`) or after (`new`) the flush, read from attribute history without I/O."""
    history = state.attrs[key].history
    if when == "new":
        if history.added:
            return [history.added[0]]
        return [history.unchanged[0]] if history.unchanged else [_UNKNOWN]
    if history.deleted:
        return [history.deleted[0]]
    if history.added:
        # Changed without the old value loaded (an expired attribute set blindly).
        return [_UNKNOWN]
    return [history.unchanged[0]] if history.unchanged else [_UNKNOWN]


@dataclass(frozen=True)
class CacheStats:
    """How one cached model's reads were served in this process, counted per entry read.

    A lookup or a query is one entry; ``cached_get_many`` counts one per requested key.
    Reads with ``use_cache=False`` are not counted. The counts start at zero when the
    process starts and only grow; compare two snapshots to see what happened between them.
    """

    #: Served from Redis.
    hits: int = 0
    #: Read from the database through the cache pool, and stored unless nothing was found.
    misses: int = 0
    #: Read through the caller's session because it holds uncommitted changes to the model,
    #: or because this process's invalidation of the model has not landed yet.
    bypassed: int = 0
    #: Read through the caller's session because Redis failed or no cache connection came in time.
    fallbacks: int = 0


class AsyncQueryCache(Generic[T]):  # noqa: UP046 -- preserve the existing Generic declaration during mechanical migration
    """One cached model's rows, field lookups and query results."""

    def __init__(
        self,
        model: type[T],
        instance_expire_seconds: int = 3600,
        query_expire_seconds: int = 300,
        *,
        partition_by: Sequence[str] = (),
        db_manager: "DatabaseManager | None" = None,
    ):
        self.model = model
        self.instance_expire_seconds = instance_expire_seconds
        self.query_expire_seconds = query_expire_seconds
        self._db_manager = db_manager
        try:
            self.codec: RowCodec | None = RowCodec(model)
        except NoInspectionAvailable:
            # Key helpers also run on plain classes (tests of key uniqueness); those never store rows.
            self.codec = None
        name = _model_cache_name(model)
        self.name = f"{name}#{self.codec.fingerprint}" if self.codec is not None else name
        self.partition_by = tuple(partition_by)
        self._partition: list[tuple[str, Callable[[Any], Any]]] = []
        if self.partition_by:
            codec = self._require_codec()
            columns = dict(codec.mapper.columns.items())
            for key in self.partition_by:
                if key not in columns:
                    raise TypeError(f"{model.__name__} has no column {key!r} to partition by")
                self._partition.append((key, _partition_normalizer(key, codec.kinds[key], cast(Column[Any], columns[key]))))
        #: SQL text by statement structure, for query keys; bounded, since structures are few.
        self._statement_sql: dict[Any, str] = {}
        self._counts: Counter[str] = Counter()

    @property
    def stats(self) -> CacheStats:
        """A snapshot of how this model's cached reads were served in this process."""
        return CacheStats(**self._counts)

    # -- keys ---------------------------------------------------------------------------

    def _key(self, kind: str, value: Any) -> str:
        """Every model cache key: ``<namespace>:model_cache:<kind>:<model import path>#<fingerprint>:<value>``."""
        return redis_key("model_cache", kind, self.name, value)

    def _generation_key(self, scope: str) -> str:
        return self._key("gen", scope)

    def _partition_scope(self, values: tuple[Any, ...]) -> str:
        digest = hashlib.sha1(orjson.dumps(list(values)), usedforsecurity=False).hexdigest()[:16]
        return f"part:{digest}"

    def _get_instance_cache_key(self, instance_id: Any) -> str:
        return self._key("i", instance_id)

    def _generate_fields_key(self, fields: dict[str, Any]) -> str:
        """Key of the cached row that one set of field conditions resolved to.

        Two different sets of conditions must never share a key, or a lookup is answered
        with another lookup's row. So the full field names go in — not a prefix of them
        (`email` and `employee_id` would both be `em`) — and the pairs are JSON-encoded, so a
        value containing `,` or `:` cannot pass for a second condition and `None` (IS NULL)
        stays apart from the string "None". Values JSON cannot express fall back to `str`.
        Each value's type goes in too: JSON writes an enum member as its value, so
        `shape=Shape.ROUND` and `shape="r"` would share a key although the database finds
        the row for the member only.
        """
        typed = sorted((name, type(value).__qualname__, value) for name, value in fields.items())
        return self._key("f", orjson.dumps(typed, default=str).decode())

    def _query_key(self, query: Select, page: int | None, page_size: int | None) -> str:
        """Key of one statement's result: SQLAlchemy's cache key renders it with its parameters, without literal SQL."""
        cache_key = query._generate_cache_key()
        if cache_key is None:
            raise ValueError("this statement has parts SQLAlchemy cannot cache, so the model cache cannot key it")
        if len(self._statement_sql) > 512:
            self._statement_sql.clear()
        rendered = cache_key.to_offline_string(self._statement_sql, query, {})
        digest = hashlib.sha1(f"{rendered}|{page}|{page_size}".encode(), usedforsecurity=False).hexdigest()
        return self._key("q", digest)

    # -- rows ---------------------------------------------------------------------------

    def _require_codec(self) -> RowCodec:
        if self.codec is None:
            raise TypeError(f"{self.model.__name__} is not a mapped model")
        return self.codec

    def _snapshot(self, instance: T) -> T:
        codec = self._require_codec()
        return codec.decode(codec.encode(instance))

    def _encode_result(self, result: list[T] | PageResult[T]) -> Any:
        codec = self._require_codec()
        if isinstance(result, PageResult):
            return {"items": [codec.encode(item) for item in result.items], "total": result.total, "page": result.page, "page_size": result.page_size}
        return [codec.encode(instance) for instance in result]

    def _decode_result(self, data: Any) -> list[T] | PageResult[T]:
        codec = self._require_codec()
        if isinstance(data, dict):
            return PageResult(items=[codec.decode(row) for row in data["items"]], total=data["total"], page=data["page"], page_size=data["page_size"])
        return [codec.decode(row) for row in data]

    # -- when the cache stays out of the way --------------------------------------------

    def _must_bypass(self, session: AsyncSession) -> bool:
        """Read the database directly: the caller holds uncommitted changes, or this process just committed some."""
        if _pending_invalidations.get(self.name):
            return True
        sync_session = session.sync_session
        if self.name in sync_session.info.get(_RECORDS, {}):
            return True
        return any(isinstance(instance, self.model) for instance in (*sync_session.new, *sync_session.dirty, *sync_session.deleted))

    async def _database(self, session: AsyncSession) -> "DatabaseManager":
        """The manager whose cache pool fills entries, after checking the caller reads the same database."""
        if self._db_manager is not None:
            database = self._db_manager
        else:
            from oldman.db.session import db_manager as database
        await database.initialize()
        bind = session.sync_session.get_bind(mapper=self._require_codec().mapper)
        caller_url = bind.engine.url.render_as_string(hide_password=False)
        if caller_url != database.engine.url.render_as_string(hide_password=False):
            raise ValueError(f"{self.model.__name__} is cached from {database.engine.url!r}, but this session reads another database")
        return database

    def _check_query(self, query: Select) -> None:
        """A cached statement reads whole rows of this model and nothing else, and does not lock."""
        table = self._require_codec().mapper.local_table
        tables: set[str] = set()
        for element in visitors.iterate(query):
            if isinstance(element, Table):
                tables.add(element.fullname)
            elif isinstance(element, BindParameter) and element.callable is not None:
                # SQLAlchemy's cache key carries the parameter, not what the callable returns,
                # so two different results would share one entry.
                raise ValueError("a bound parameter computed by a callable cannot key a cached query; pass the value itself")
        if tables != {cast(Table, table).fullname}:
            raise ValueError(f"a cached query may read only {table}; this one reads {sorted(tables)}")
        descriptions = query.column_descriptions
        if len(descriptions) != 1 or descriptions[0].get("expr") is not self.model:
            raise ValueError(f"a cached query must select whole {self.model.__name__} rows and nothing else")
        if query._for_update_arg is not None:
            raise ValueError("a locking read (with_for_update) cannot come from a cache")
        if query._with_options:
            raise ValueError("cached rows carry the model's own columns only; loader options do not apply to them")

    def _partition_of(self, query: Select) -> tuple[Any, ...] | None:
        """The declared partition this query stays inside, or None when it may read across partitions.

        Every partition column must appear in the WHERE's top-level AND pinned to one value
        (see `_fixed_values`); other conditions may narrow the result further. A subquery
        anywhere in the WHERE could read other partitions, so it disqualifies the query.
        """
        where = query.whereclause
        if not self._partition or where is None:
            return None
        if any(isinstance(element, SelectBase | ScalarSelect | Subquery) for element in visitors.iterate(where)):
            return None
        codec = self._require_codec()
        table = codec.mapper.local_table
        found: dict[str, Any] = {}
        for term in _and_terms(where):
            for column, value in _fixed_values(term):
                if getattr(column, "table", None) is not table:
                    continue
                key = codec.keys_by_column.get(getattr(column, "name", ""))
                if key is not None and key not in found:
                    found[key] = value
        normalized = []
        for key, normalize in self._partition:
            if key not in found:
                return None
            value = normalize(found[key])
            if value is _INVALID:
                return None
            normalized.append(value)
        return tuple(normalized)

    # -- Redis --------------------------------------------------------------------------

    async def _read(self, entry_key: str, generation_keys: list[str]) -> tuple[list[str], bool, Any]:
        """One round trip: create missing generations, then read the entry and the current generations atomically."""
        conn = await _cache_redis_connection()
        pipe = conn.pipeline()
        for key in generation_keys:
            pipe.set(key, _new_generation(), nx=True, ex=GENERATION_TTL)
        pipe.get(entry_key)
        pipe.mget(generation_keys)
        results = await pipe.execute()
        current = _generation_values(results[-1])
        raw = results[-2]
        if raw is None:
            return current, False, None
        entry = orjson.loads(raw)
        if entry.get("g") != current:
            return current, False, None
        return current, True, entry["d"]

    async def _store(self, entry_key: str, generations: list[str], data: Any, expire_seconds: int, **extra: Any) -> None:
        await self._store_many([(entry_key, {"g": generations, "d": data, **extra})], expire_seconds)

    async def _store_many(self, entries: list[tuple[str, dict[str, Any]]], expire_seconds: int) -> None:
        """Store entries in one round trip; a failure is logged, since the caller already has its rows."""
        if not entries:
            return
        try:
            conn = await _cache_redis_connection()
            pipe = conn.pipeline()
            for entry_key, entry in entries:
                pipe.set(entry_key, orjson.dumps(entry), ex=expire_seconds)
            await pipe.execute()
        except _REDIS_ERRORS as exc:
            logger.warning("Model cache %s: could not store an entry (%s)", self.name, exc)

    async def _fill(self, database: "DatabaseManager", load: Callable[[AsyncSession], Awaitable[R]], encode: Callable[[R], Any]) -> tuple[bool, Any]:
        """Load and encode through the cache pool; (False, None) when no cache connection came in time."""
        try:
            async with database.cache_fill_session() as fill:
                return True, encode(await load(fill))
        except PoolTimeoutError:
            logger.warning("Model cache %s: no cache connection within the pool timeout; reading without the cache", self.name)
            return False, None

    # -- reads --------------------------------------------------------------------------

    async def get_by_fields(self, session: AsyncSession, *, use_cache: bool = True, **fields: Any) -> T | None:
        """The one row matching `fields`, which should name a unique key: more than one raises MultipleResultsFound."""
        if not use_cache:
            return await self.model.get_by_fields(session, **fields)  # type: ignore[return-value]
        codec = self._require_codec()
        if self._must_bypass(session):
            self._counts["bypassed"] += 1
            found = await self.model.get_by_fields(session, **fields)
            return None if found is None else self._snapshot(found)  # type: ignore[arg-type]
        database = await self._database(session)
        entry_key = self._generate_fields_key(fields)
        guard_keys = [self._generation_key("epoch"), self._generation_key("any")]
        try:
            conn = await _cache_redis_connection()
            pipe = conn.pipeline()
            for key in guard_keys:
                pipe.set(key, _new_generation(), nx=True, ex=GENERATION_TTL)
            pipe.get(entry_key)
            pipe.mget(guard_keys)
            *_, raw, guard_values = await pipe.execute()
            before = _generation_values(guard_values)
            if raw is not None:
                entry = orjson.loads(raw)
                row_keys = [guard_keys[0], self._generation_key(f"row:{_token(entry['pk'])}")]
                pipe = conn.pipeline()
                pipe.set(row_keys[1], _new_generation(), nx=True, ex=GENERATION_TTL)
                pipe.mget(row_keys)
                *_, row_values = await pipe.execute()
                if entry.get("g") == _generation_values(row_values):
                    self._counts["hits"] += 1
                    return codec.decode(entry["d"])
        except _REDIS_ERRORS as exc:
            logger.warning("Model cache %s: Redis unavailable (%s); reading without the cache", self.name, exc)
            self._counts["fallbacks"] += 1
            found = await self.model.get_by_fields(session, **fields)
            return None if found is None else self._snapshot(found)  # type: ignore[arg-type]

        filled, data = await self._fill(
            database,
            lambda fill: self.model.get_by_fields(fill, **fields),
            lambda row: None if row is None else codec.encode(row),
        )
        if not filled:
            self._counts["fallbacks"] += 1
            found = await self.model.get_by_fields(session, **fields)
            return None if found is None else self._snapshot(found)  # type: ignore[arg-type]
        self._counts["misses"] += 1
        if data is None:
            return None
        # The row's key was unknown until the read; store only if no write to the model was
        # invalidated meanwhile, and against the row generation read after the fill.
        pk = data[codec.primary_key]
        row_keys = [guard_keys[0], guard_keys[1], self._generation_key(f"row:{_token(pk)}")]
        try:
            pipe = conn.pipeline()
            pipe.set(row_keys[2], _new_generation(), nx=True, ex=GENERATION_TTL)
            pipe.mget(row_keys)
            *_, after = await pipe.execute()
            after_values = _generation_values(after)
            if after_values[:2] == before:
                await self._store(entry_key, [after_values[0], after_values[2]], data, self.instance_expire_seconds, pk=pk)
        except _REDIS_ERRORS as exc:
            logger.warning("Model cache %s: could not store an entry (%s)", self.name, exc)
        return codec.decode(data)

    async def get_many(self, session: AsyncSession, ids: list[Any], *, use_cache: bool = True) -> dict[Any, T]:
        """Rows by primary key; each is cached on its own and invalidated by writes to that row."""
        if not use_cache:
            return await self.model.get_many_by_ids(session, ids)  # type: ignore[return-value]
        if self._must_bypass(session):
            self._counts["bypassed"] += len(ids)
            rows = await self.model.get_many_by_ids(session, ids)
            return {pk: self._snapshot(row) for pk, row in self._keyed_as_requested(ids, rows).items()}  # type: ignore[arg-type]
        codec = self._require_codec()
        database = await self._database(session)
        epoch_key = self._generation_key("epoch")
        row_keys = [self._generation_key(f"row:{self._row_token(pk)}") for pk in ids]
        try:
            conn = await _cache_redis_connection()
            pipe = conn.pipeline()
            for key in (epoch_key, *row_keys):
                pipe.set(key, _new_generation(), nx=True, ex=GENERATION_TTL)
            for pk in ids:
                pipe.get(self._get_instance_cache_key(pk))
            pipe.mget([epoch_key, *row_keys])
            results = await pipe.execute()
        except _REDIS_ERRORS as exc:
            logger.warning("Model cache %s: Redis unavailable (%s); reading without the cache", self.name, exc)
            self._counts["fallbacks"] += len(ids)
            rows = await self.model.get_many_by_ids(session, ids)
            return {pk: self._snapshot(row) for pk, row in self._keyed_as_requested(ids, rows).items()}  # type: ignore[arg-type]
        epoch, *row_values = _generation_values(results[-1])
        entries = results[-1 - len(ids) : -1]

        found: dict[Any, T] = {}
        current: dict[Any, list[str]] = {}
        missing: list[Any] = []
        for pk, raw, row_value in zip(ids, entries, row_values, strict=True):
            current[pk] = [epoch, row_value]
            entry = orjson.loads(raw) if raw is not None else None
            if entry is not None and entry.get("g") == current[pk]:
                found[pk] = codec.decode(entry["d"])
            else:
                missing.append(pk)
        self._counts["hits"] += len(ids) - len(missing)
        if not missing:
            return found

        filled, data = await self._fill(
            database,
            lambda fill: self.model.get_many_by_ids(fill, missing),
            lambda rows: {pk: codec.encode(row) for pk, row in rows.items()},
        )
        if not filled:
            self._counts["fallbacks"] += len(missing)
            rows = await self.model.get_many_by_ids(session, missing)
            found.update({pk: self._snapshot(row) for pk, row in self._keyed_as_requested(missing, rows).items()})  # type: ignore[arg-type]
            return found
        self._counts["misses"] += len(missing)
        entries = []
        for pk, row in self._keyed_as_requested(missing, data).items():
            if pk in current:
                entries.append((self._get_instance_cache_key(pk), {"g": current[pk], "d": row}))
            found[pk] = codec.decode(row)
        await self._store_many(entries, self.instance_expire_seconds)
        return found

    def _keyed_as_requested(self, ids: list[Any], rows: dict[Any, R]) -> dict[Any, R]:
        """Rows by the key the caller passed for them, as hits are: `"1"` stays `"1"`, not the database's `1`.

        A row found under a spelling of its key that encodes differently (an upper-case UUID
        string) keeps the database's key; `get_many` does not store it, as its entry would be
        named apart from the row's generation.
        """
        requested = {self._row_token(pk): pk for pk in ids}
        return {requested.get(self._row_token(pk), pk): row for pk, row in rows.items()}

    async def execute_query(
        self,
        session: AsyncSession,
        query: Select,
        page: int | None = None,
        page_size: int | None = None,
        *,
        use_cache: bool = True,
        expire_seconds: int | None = None,
    ) -> list[T] | PageResult[T]:
        """Run `query` (whole rows of this model) through the cache; `use_cache=False` is an ordinary query."""
        if not use_cache:
            return await self.model.execute_query_with_select(session, query, page, page_size)  # type: ignore[return-value]

        def load(target: AsyncSession) -> Awaitable[Any]:
            return self.model.execute_query_with_select(target, query, page, page_size)

        self._check_query(query)
        if self._must_bypass(session):
            self._counts["bypassed"] += 1
            return self._decode_result(self._encode_result(await load(session)))
        database = await self._database(session)
        partition = self._partition_of(query)
        scope = self._partition_scope(partition) if partition is not None else "any"
        generation_keys = [self._generation_key("epoch"), self._generation_key(scope)]
        entry_key = self._query_key(query, page, page_size)
        try:
            current, hit, data = await self._read(entry_key, generation_keys)
        except _REDIS_ERRORS as exc:
            logger.warning("Model cache %s: Redis unavailable (%s); reading without the cache", self.name, exc)
            self._counts["fallbacks"] += 1
            return self._decode_result(self._encode_result(await load(session)))
        if hit:
            self._counts["hits"] += 1
            return self._decode_result(data)
        filled, data = await self._fill(database, load, self._encode_result)
        if not filled:
            self._counts["fallbacks"] += 1
            return self._decode_result(self._encode_result(await load(session)))
        self._counts["misses"] += 1
        await self._store(entry_key, current, data, expire_seconds or self.query_expire_seconds)
        return self._decode_result(data)

    # -- writes -------------------------------------------------------------------------

    def _row_token(self, pk: Any) -> str:
        """A primary key as its row generation is named: encoded the way the row is stored, as reads name it.

        `str()` would name an enum key `Region.NORTH` and a datetime `2026-09-01 08:00:00` where
        the stored row says `NORTH` and `2026-09-01T08:00:00`, and a write would advance a
        generation no entry depends on. Integers, strings, UUIDs and dates come out as `str()`
        gave them, so their existing entries stay valid.
        """
        try:
            encoded = self._require_codec().encode_primary_key(pk)
        except (AttributeError, TypeError, ValueError):
            # A caller's key in another spelling (an enum member's name as a string): as given.
            encoded = pk
        return _token(encoded)

    def _record_write(self, target: Any, when: Sequence[str]) -> None:
        """Note, from inside the flush, which generations this row's write must advance once the transaction commits."""
        session = object_session(target)
        if session is None:
            return
        codec = self._require_codec()
        state = inspect(target)
        pending = _pending_for(session, self)
        for moment in when:
            for pk in _values(state, codec.primary_key, moment):
                if isinstance(pk, _Unknown):
                    pending.everything = True
                else:
                    pending.rows.add(self._row_token(pk))
            if not self._partition:
                continue
            values = []
            for key, normalize in self._partition:
                value = _values(state, key, moment)[0]
                value = _INVALID if isinstance(value, _Unknown) else normalize(value)
                if value is _INVALID:
                    pending.everything = True
                    break
                values.append(value)
            else:
                pending.partitions.add(tuple(values))

    def _record_everything(self, target: Any) -> None:
        """A write to a model this one depends on: the database may have changed any of this model's rows."""
        session = object_session(target)
        if session is not None:
            _pending_for(session, self).everything = True

    async def invalidate_cache(self) -> None:
        """Invalidate every cached row, lookup and query of this model now, for writes the cache could not see."""
        await _bump({self._generation_key("epoch")})

    def invalidate_cache_on_commit(self, session: AsyncSession | Session) -> None:
        """Invalidate the whole model when `session` commits, and not at all if it rolls back.

        For writes that bypass the ORM's unit of work inside the transaction: bulk
        ``insert()``/``update()``/``delete()`` statements and raw SQL fire no mapper events.
        """
        sync_session = session.sync_session if isinstance(session, AsyncSession) else session
        _pending_for(sync_session, self).everything = True


class CacheableModel(DatabaseModel):
    """可缓存模型的基类"""

    __abstract__ = True

    _cache_manager: ClassVar[AsyncQueryCache[Any] | None] = None

    @classmethod
    def get_cache_manager(cls) -> AsyncQueryCache[Any]:
        """获取缓存管理器实例"""
        if cls._cache_manager is None:
            raise RuntimeError(f"Cache manager not initialized for {cls.__name__}")
        return cls._cache_manager

    @classmethod
    def set_cache_manager(cls, cache_manager: AsyncQueryCache[Any]) -> None:
        """设置缓存管理器实例"""
        cls._cache_manager = cache_manager

    @classmethod
    async def cached_get(cls, session: AsyncSession, *, use_cache: bool = True, **fields: Any) -> Self | None:
        manager = cls.get_cache_manager()
        return await manager.get_by_fields(session, use_cache=use_cache, **fields)

    @classmethod
    async def cached_get_many(cls, session: AsyncSession, ids: list[Any], *, use_cache: bool = True) -> dict[Any, Self]:
        manager = cls.get_cache_manager()
        return await manager.get_many(session, ids, use_cache=use_cache)

    @classmethod
    async def cached_filter(
        cls,
        session: AsyncSession,
        *conditions: Any,
        page: int | None = None,
        page_size: int | None = None,
        use_cache: bool = True,
        expire_seconds: int | None = None,
    ) -> list[Self] | PageResult[Self]:
        manager = cls.get_cache_manager()
        query = select(cls).filter(*conditions)
        return await manager.execute_query(session, query, page, page_size, use_cache=use_cache, expire_seconds=expire_seconds)

    @classmethod
    async def invalidate_cache(cls) -> None:
        await cls.get_cache_manager().invalidate_cache()

    @classmethod
    def invalidate_cache_on_commit(cls, session: AsyncSession | Session) -> None:
        cls.get_cache_manager().invalidate_cache_on_commit(session)


_DATABASE_ACTIONS = {"CASCADE", "SET NULL", "SET DEFAULT"}


def _database_cascades(table: Table) -> list[tuple[str, str, frozenset[str], str]]:
    """Every foreign key along which the database may change `table`'s rows by itself, followed up the chain.

    Each entry is ``(table, column, actions, referenced table)``. A referenced table whose own rows
    the database changes by cascade changes this one in turn - a team deleted takes its projects,
    and their tasks with them - so the walk continues from every referenced table. Any action on
    the way counts, which may invalidate more than needed but never less.
    """
    metadata = table.metadata
    cascades: list[tuple[str, str, frozenset[str], str]] = []
    seen = {table.fullname}
    pending = [table]
    while pending:
        current = pending.pop()
        for column in current.columns:
            for foreign_key in column.foreign_keys:
                actions = frozenset({(foreign_key.ondelete or "").upper(), (foreign_key.onupdate or "").upper()} & _DATABASE_ACTIONS)
                if not actions:
                    continue
                target_name = foreign_key.target_fullname.rpartition(".")[0]
                cascades.append((current.fullname, column.name, actions, target_name))
                if target_name in seen:
                    continue
                seen.add(target_name)
                target = metadata.tables.get(target_name)
                if target is None:
                    raise TypeError(
                        f"{current.fullname}.{column.name} has ON {'/'.join(sorted(actions))} towards {target_name}, which is not "
                        f"defined yet: import its model before the cached model, so the whole cascade chain can be checked"
                    )
                pending.append(target)
    return cascades


def _require_cascades_declared(model: type, invalidate_on: Sequence[type]) -> bool:
    """Every table the database may change this model's rows for must have its model in `invalidate_on`.

    `ON DELETE CASCADE` / `SET NULL` / `SET DEFAULT` and `ON UPDATE CASCADE` change rows without
    any ORM event on them; only a write to the referenced table shows that they happened - and
    when that table is itself cascaded into, only a write further up the chain does.

    The model's own table needs no declaring - the class cannot name itself in its own
    decorator. Returns whether a cascade leads back to it (a tree's parent key, say): then
    each update or delete of the model may change other rows of it, and the caller makes it
    invalidate the whole model.
    """
    table = cast(Table, inspect(model).local_table)
    declared = {cast(Table, inspect(target).local_table).fullname for target in invalidate_on} | {table.fullname}
    cascades = _database_cascades(table)
    for source, column, actions, target in cascades:
        if target not in declared:
            through = "" if source == table.fullname else f", whose rows the database changes for {table.fullname} in turn"
            raise TypeError(
                f"{model.__name__}: {source}.{column} has ON {'/'.join(sorted(actions))} towards {target}{through}: the database "
                f"changes these rows without telling the cache, so list the model of {target} in invalidate_on"
            )
    return any(target == table.fullname for _, _, _, target in cascades)


def cached_model(
    instance_expire_seconds: int = 3600,
    query_expire_seconds: int = 300,
    *,
    partition_by: Sequence[str] = (),
    invalidate_on: Sequence[type] = (),
    db_manager: "DatabaseManager | None" = None,
):
    """Declare a `CacheableModel` cached; its writes through the ORM invalidate what they affect.

    `partition_by` names integer, boolean, UUID or enum columns - typically a foreign key.
    A query whose WHERE fixes all of them with `==` or `IS NULL` is invalidated only by writes
    to rows in that partition (before or after the write); any other query by any write to
    the model. `invalidate_on` names models whose updates and deletes invalidate this whole
    model - required for the targets of foreign keys with database-level cascades, and for
    every table further up a chain of them. A cascade back into the model's own table (a
    tree's parent key) needs no entry: its updates and deletes then invalidate the whole model. `db_manager` defaults to the process's; it must
    connect to the database the callers' sessions read.
    """

    def decorator(cls: type[T]) -> type[T]:
        if not issubclass(cls, CacheableModel):
            raise TypeError(f"{cls.__name__} must inherit from CacheableModel")
        cascades_into_itself = _require_cascades_declared(cls, invalidate_on)

        manager = AsyncQueryCache(cls, instance_expire_seconds, query_expire_seconds, partition_by=partition_by, db_manager=db_manager)
        cls.set_cache_manager(manager)  # type: ignore[attr-defined]

        # A cascade back into this table changes rows no ORM event is fired for; every update
        # or delete then invalidates the whole model, as a declared dependency's would.
        dependencies = (*invalidate_on, cls) if cascades_into_itself else tuple(invalidate_on)
        for dependency in dependencies:
            for moment in ("after_update", "after_delete"):
                event.listen(dependency, moment, lambda mapper, connection, target: manager._record_everything(target))

        @event.listens_for(cls, "after_insert")
        def after_insert(mapper: Any, connection: Any, target: T) -> None:
            manager._record_write(target, ("new",))

        @event.listens_for(cls, "after_update")
        def after_update(mapper: Any, connection: Any, target: T) -> None:
            manager._record_write(target, ("old", "new"))

        @event.listens_for(cls, "after_delete")
        def after_delete(mapper: Any, connection: Any, target: T) -> None:
            manager._record_write(target, ("old",))

        return cls

    return decorator


__all__ = [
    "CacheStats",
    "CacheableModel",
    "cached_model",
    "wait_for_invalidations",
]
