# Models and database sessions

Oldman uses SQLAlchemy mappings and asynchronous database drivers, without introducing another query language. Declaring models, generating database schemas, and running request transactions are separate operations. For first-time setup, see [Real demo data, migrations, and queries](../users/tutorial-tasks.md); for schema changes, see [Project database migrations](migrations.md).

This chapter uses ExampleTeam/ExampleProject and the real-time charts in the EPG demo. All code runs inside Apps registered with that demo. First follow the tutorial to run migrations, import fixtures, and create an account. Importing a class alone does not mean its database schema exists.

## Where models are loaded from

The complete ExampleTeam declaration in [apps/examples/models.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/models.py) is shown below. That file enables `from __future__ import annotations`. Mapped/mapped_column/relationship come from sqlalchemy.orm; column types, constraints, and indexes come from SQLAlchemy; DatabaseModel comes from oldman.db.models; and `_` is gettext_lazy. ExampleProject and other mapped classes follow it in the file. Do not copy Team without the class at the other end of its relationship:

```python
class ExampleTeam(DatabaseModel):
    """Team used to group projects in table and form examples."""

    __tablename__ = "example_team"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_example_team_slug"),
        Index("ix_example_team_region", "region"),
        Index("ix_example_team_is_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    projects: Mapped[list[ExampleProject]] = relationship(
        back_populates="team",
        cascade="all, delete-orphan",
    )

    class Meta:
        """Provide labels for automatic Admin presentation."""

        verbose_name = _("Example Team")
        verbose_name_plural = _("Example Teams")
```

`oldman.db` exposes `Base`, `DatabaseModel`, `ModelMetadata`, `DatabaseManager`, `DatabaseNotConfiguredError`, the `AsyncSession` session type, and the process-wide `db_manager`. DatabaseModel is an abstract subclass of the shared Base and has no automatic id: business models declare their own primary keys. Without an explicit table name, Base uses the lowercase class name. Real projects should name tables explicitly.

Time columns store naive UTC values. For the current time, use `oldman.utils.date.naive_utcnow`: `default=naive_utcnow` and `onupdate=naive_utcnow` in declarations, and `naive_utcnow()` in code. Do not repeat `datetime.now(UTC).replace(tzinfo=None)` throughout the project or mix aware and naive values in one column.

The App Registry loads models from the models modules of registered packages and records their owning App, Table, display name, and managed status. It does not scan every installed package. Do not import models early in an App metadata module. Each Table belongs to exactly one App; standalone association Tables must also be declared within that App's model module tree. When models are split into a package, its `models/__init__.py` must explicitly import the submodules.

The demo service's YAML apps list includes `apps.examples`, whose [apps.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/apps.py) declares the label `examples`. The package path, App label, Python class name ExampleTeam, and database table name example_team are distinct identifiers and must not be used interchangeably. Existing migrations are stored in [migrations](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/apps/examples/migrations); you do not need to regenerate them each time you examine the example.

Meta supports `verbose_name`, `verbose_name_plural`, and `managed`. Display names can use `gettext_lazy` for translation during each request. The default singular name comes from the class name, and the default plural adds s; specify irregular names explicitly. `managed=False` only excludes the table schema from migration management. It is **not a permission switch that prevents ORM writes**. See the migration reference for external-table rules.

Use SQLAlchemy for ordinary ForeignKey declarations, relationships, indexes, and constraints. Do not mix models from a separate DeclarativeBase into the framework Registry or declare mapped classes inside view functions.

## Configuration and lazy connections

The database section in the demo's [data/web_settings.example.yaml](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/web_settings.example.yaml) is:

```yaml
database:
  url: sqlite+aiosqlite:///data/epg_dashboard.db
  echo: false
  enable_sql_logging: false
```

Common driver combinations are SQLite/aiosqlite, MySQL/aiomysql, and PostgreSQL/asyncpg. Install the asynchronous driver selected for the service. Configuration can load without a URL, but requesting a session then raises DatabaseNotConfiguredError. Do not commit passwords embedded in URLs.

db_manager is a process-wide lazy instance. It initializes the engine when a session is first entered; an actual database operation still triggers the connection. The `engine` property does not perform asynchronous initialization and raises an error if read too early. Before using the engine directly, call `await db_manager.initialize()`.

Each service process has its own connection pool; Sanic workers do not share one pool. For non-SQLite databases, the defaults are pool_size=100, max_overflow=10, pool_timeout=30 seconds, and pool_recycle=1800 seconds. Assess database connection limits against the process count when deploying. These constructor parameters can be overridden; they are not all configurable through the current YAML schema. SQLite does not use the server-database pool defaults and enables foreign-key constraints on every connection.

DatabaseManager accepts a DatabaseConfig or a synchronous factory returning one, plus optional debug, pool_size, pool_class, max_overflow, pool_timeout, pool_recycle, enable_sql_logging, cache_pool_size, and cache_pool_timeout parameters. The last three read their corresponding DatabaseConfig settings when omitted. The last two set the size and wait timeout in seconds for the dedicated model-cache connection pool; see [model caching](cache.md#cache-connection-pool). DatabaseConfig comes from `oldman.conf.schemas`. This describes the constructor interface: the demo uses the framework's db_manager rather than creating another manager in business code. If an explicit manager is needed, its caller owns close. Creating a manager neither creates tables nor registers models.

## One business operation, one write transaction

The demo's [apps/examples/services.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/services.py) supplies data for the static project table with the complete function below. select/selectinload come from SQLAlchemy, db_manager comes from oldman.db, and ExampleProject comes from the same App's models:

```python
async def list_projects(limit: int = 12) -> list[ExampleProject]:
    """Return deterministic database rows for the static Table examples."""
    async with db_manager.get_read_session() as session:
        result = await session.execute(
            select(ExampleProject)
            .options(selectinload(ExampleProject.team))
            .order_by(ExampleProject.id.asc())
            .limit(limit)
        )
        return list(result.scalars())
```

The return value is a list of models whose fields and team relationships have already been loaded, rather than an unexecuted query. The views serve `/examples/tables/static` and `/examples/tables/responsive`. Do not omit relationship preloading and then let asynchronous templates query the database implicitly.

The session type is `oldman.db.AsyncSession`; import it from there for annotations. It extends SQLAlchemy's AsyncSession with `exec()`. Like `execute()`, `exec()` executes a statement, but a `select()` of one model or column returns those values directly. The example above can therefore use `return list((await session.exec(...)).all())`; `.one()` and `.first()` work the same way. Results for multiple columns, `text()`, and `update()`/`delete()` match `execute()`. Use `execute()` when you need rows (`row._mapping`) even for one column. Build statements with SQLAlchemy's `select`; the framework does not depend on SQLModel.

A view can own a write transaction and pass its session to service functions. The following is the complete publishing endpoint from [views/charts.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/charts.py), used by the button on `/examples/charts/realtime`:

```python
@router.post("/examples/charts/realtime/publish", name="example_realtime_chart_publish")
@csrf_protect()
@login_required()
async def example_realtime_chart_publish(request: Request):
    """Commit one metric, then publish it through the configured SSE Redis channel."""
    server_id = _server_id(request)
    async with db_manager.get_session() as session:
        try:
            payload = await services.create_server_metric(session, server_id)
        except ValueError as exc:
            raise BadRequest("Unknown example server") from exc
    published = await SSEPublisher.from_settings().publish_stream(
        stream=services.realtime_chart_stream(server_id),
        event=CHART_EVENT,
        payload=payload,
    )
    if not published:
        return api_response(
            DefaultApiResponse(
                error_code=ApiErrorCode.INVALID_REQUEST,
                message=_("The metric was saved, but Redis delivery failed."),
            )
        )
    return api_response(
        DefaultApiResponse(
            message=_("A new database metric was published."),
            actions=[
                FeedbackAction(title=_("Realtime metric published."), icon="success")
            ],
        )
    )
```

The route is registered with `router` from `oldman.web`. Request, BadRequest, CSRF, `login_required` (`oldman.web.auth`), and response types are imported from the framework. `_server_id()` and CHART_EVENT are defined in the same file, and services refers to apps.examples.services. SSE uses the configured Redis; see [Real-time delivery guide (in Chinese)](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/agents/realtime.md) for initialization and browser wiring. Do not add SSE to business functionality that does not need real-time delivery just to copy this database example.

`create_server_metric()` reads the server and latest sample within the caller's Session, builds an ExampleServerMetric, calls `session.add(metric)` and `await session.flush()`, and returns a strongly typed payload. It does not commit. The value is a deterministic next sample for illustration, not a measurement collected from a real server. A record is written only when the user explicitly clicks publish. Publishing happens after the transaction exits. A Redis publishing failure does not undo the committed sample and must not automatically retry the database write.

| Interface | Actual behavior |
| --- | --- |
| `get_session(request_info="")` | Creates a write Session; commits on normal exit, rolls back on exceptional exit, then closes it and handles this session's file candidates |
| `get_read_session()` | Creates a read Session with autoflush=False; does not commit automatically and closes on exit; does not enforce database-level read-only permissions |
| `transaction()` | Creates a new Session and manages its transaction: commits on normal exit and rolls back on exceptional exit; does not reuse an existing request Session |
| `initialize()` | Idempotently initializes this manager's engine and session factory |
| `close()` | Releases the engine, connection pools (including the model-cache pool), and trackers; later use can initialize them again |

flush sends SQL and obtains database-assigned ids, but the transaction can still roll back. Do not manually commit inside get_session and expect that context to continue managing the same transaction. For a savepoint within one transaction, use `session.begin_nested()` on the Session that owns it. `db_manager.transaction()` creates another Session and has no savepoint form.

An AsyncSession must not be shared between concurrent tasks. Give tasks separate sessions when they need independent transactions. For atomic operations, perform the work sequentially in one coroutine and one session. Do not store a Session in a global variable or pass it between processes.

Load relationships within the session through explicit queries or selectinload/joinedload. Accessing an unloaded relationship after an asynchronous ORM session closes does not automatically return an awaitable query. Prefer building response data inside the session.

Let business exceptions propagate through the write context to trigger rollback. If you catch an exception inside the context and exit normally, other changes that have not been rolled back may still commit. Push browser updates and make external requests after successfully exiting the write context. Do not treat the database and Redis/network as one transaction.

## Boundaries of DatabaseModel convenience methods

| Method | Return value and caveats |
| --- | --- |
| `get_by_id(session, pk)` | An object or None; supports single-column primary keys only |
| `get_by_fields(session, options=None, **kwargs)` | One matching object or None; multiple matches remain a query error |
| `get_many_by_ids(session, ids)` | A dictionary mapping primary keys to objects; empty input returns an empty dictionary; supports single-column primary keys only |
| `get_many(session, **kwargs)` | All matching objects; does not limit the amount of data for you |
| `execute_query(session, *conditions, page=None, page_size=None)` | A list without pagination, or PageResult with pagination |
| `execute_query_with_select(session, query, page=None, page_size=None)` | As above, accepting a custom Select |
| `add_to_session(session)` | Only adds the instance and returns it; does not commit |
| `save(session)`, `update(session, **kwargs)`, `delete(session)` | **Commit themselves**; unsuitable for the composite transactions above. `update()` raises `AttributeError` for a field absent from the model rather than silently skipping it |

ModelForm.save and DatabaseModel.save are different interfaces. The former only adds/flushes with commit=True; the latter commits. For composite operations, prefer session.add, session.delete, and flush so similar method names do not cause an early commit.

Models also provide model_dump_dict, model_dump_json, and model_validate_json for explicit serialization scenarios. They are not field allowlists for arbitrary HTTP input. Do not deserialize a client-supplied object and directly save permission fields.

All three use the same column-type codecs as model caching. `model_dump_dict()` returns JSON values for loaded columns: dates and times as ISO strings, Decimal and UUID as strings, enums as member names, bytes as base64, Interval as `[days, seconds, microseconds]`, and floating-point NaN and positive/negative infinity as `"nan"`, `"inf"`, and `"-inf"`. Unloaded columns and related objects are excluded. `model_dump_json()` returns that data as JSON text. `model_validate_json()` restores each value by column type (a date is still a `date`) and returns a new, unsaved object created through the constructor. Unknown column keys raise TypeError. All three methods raise TypeError when the model has columns such as project-defined `TypeDecorator` or `ARRAY` types that cannot be guaranteed to round-trip unchanged.

NativeTimestampsMixin, UtcTimestampsMixin, UUIDMixin, and SoftDeleteMixin can be imported from `oldman.db.models`, but they are not universally portable default models. Timestamp mixins make database-dialect assumptions in server expressions, and UUIDMixin uses PostgreSQL UUID/default. Check your target database before choosing them; minimal SQLite examples use ordinary mapped_column declarations. SoftDeleteMixin only provides fields. It does not rewrite delete or filter every query automatically.

## Real foreign keys to User

The setting is `app.settings.user_model` on the Auth App, or `app_settings.auth.user_model` in YAML. The selected class must inherit `oldman.auth.AbstractUser`. Its actual table is always `oldman_user`, and its primary key is always the auto-incrementing Integer id. Do not change the table name, core fields, or primary-key type.

Business models declare `ForeignKey("oldman_user.id")` directly and choose ondelete according to their data semantics. Real foreign keys do not need to infer the User class's table name dynamically. A custom User can add columns, indexes, relationships, and methods, and its App must be registered in the service's apps. Every service enabling Auth must select the same User class; see [migrations and Auth](migrations.md#migrations-for-user-extensions).

The demo actually selects `apps.accounts.models.User`. [This class](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/accounts/models.py) is the class generated in the dashboard scaffold by `startproject`: it inherits AbstractUser and only defines display Meta (verbose_name), with no additional user columns. Do not describe it as demonstrating every User-extension migration scenario.

## Shutdown and failures

When a Web service, Simple service, or App command stops, the framework closes the process's `db_manager` (along with the cache and Redis) after business shutdown hooks, even if those hooks fail. Do not close it after each HTTP request. Standalone scripts must close the manager they use in their own finally block. The framework's shutdown chain closes the shared database pool of a dedicated Taskiq Worker; see [the Taskiq lifecycle](distributed-tasks.md#app-and-service-loading) for the actual demo and differences.

The creator of an explicit DatabaseManager likewise owns its shutdown. `enable_sql_logging=True` adds query tracking and summaries, and request_info can identify a business location. Do not enable detailed SQL output unconditionally in production.

`create_db_and_tables()` only creates current managed metadata for isolated low-level tests. It neither upgrades existing tables nor establishes migration history. Production and tutorial deployments use db migrate. For additional handling of file replacement, deletion, and rollback, see [the file lifecycle](storage.md#model-file-replacement-and-deletion).

<!-- source: zh/developers/database.md @ fe264663 -->
