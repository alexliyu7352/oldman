# Project database migrations

Oldman reads project configuration, loads models, manages each App's migration directory, and then calls Alembic. The output remains readable Python revisions. Users do not need to write alembic.ini, env.py, asynchronous engine wiring, or version_locations. The framework does not modify the database automatically at service startup.

## Commands and scope

Run these commands at the application project root containing pyproject.toml, services/, and data/:

```sh
./run.sh db makemigrations
./run.sh db migrate
./run.sh db status
./run.sh db history
```

| Command | Purpose |
| --- | --- |
| `makemigrations` | Compares current models with the actual database; interactively selects the App and rename/deletion intent, then generates one candidate revision |
| `migrate` | Shows pending branches and lets you select all Apps or one App, applying dependencies as well |
| `status` | Reads the database owner, internal-table status, and each App's current revision, heads, and pending revisions without modifying them |
| `history` | Shows migration source history without connecting to the database; still requires valid project configuration and loadable models |
| `downgrade` | Interactively selects an App and a target revision/base, then runs reverse operations after confirmation; may delete data |
| `retire` | Interactively removes an App's migration-management records while retaining its tables; does not uninstall business code |

These are project commands, not `web db`. The target App and destructive intent are selected interactively in a real terminal. There are no --app, --empty, --rename-table, --yes, or separate merge commands. Pipes and non-TTY input fail when an answer is required. Do not treat disabling interactive safety checks as a deployment option. When nothing is pending, the command reports that normally without forcing a new file or DDL.

Once the database is initialized and no special recovery or adoption decisions are needed, non-interactive migrate applies all pending branches by default and can be used in deployment. An interactive terminal offers scope selection instead. This does not permit unattended confirmation of first-time setup or state recovery.

## Which services make up a project

The migration entry point reads actual services identified in `services/*.py` and their corresponding `data/<filename>_settings.yaml` files without importing or starting those services. Each actual service must have its default YAML file. Alternative files used by tests are excluded from this set.

It reads only schema-related apps, database.url, and app_settings.auth.user_model settings. It does not bind full runtime Settings or initialize Sessions, SSE, Redis, or Web. Model/App metadata imports must still follow the loading contract and must not start external resources as an import side effect.

All nonempty database.url values must be **exactly identical strings**. Services without a database supply no URL, but their registered Apps still belong to the project's combined App set. The framework does not resolve whether two URLs ultimately identify the same database and does not support migrating multiple databases in one project.

`[tool.oldman].migration_apps` can add App packages whose migrations are still needed even though no service currently enables them. It does not replace actual Auth configuration. Normally, maintain only service apps lists rather than keeping a second list for every App.

App order does not determine database dependency order. The generator analyzes actual table foreign keys for structural dependencies. The executor uses standard down_revision and depends_on graphs rather than inferring execution order from YAML order.

## One project owns database maintenance

The scaffold generates a stable `[tool.oldman].project_id` UUID in pyproject.toml; commit it with the source. A database has one migration-maintenance project. Its owner is recorded on the first migration, and projects with other project_id values cannot take over its migrations.

When API and Web are separate code projects sharing one database, choose one project to maintain the entire schema. The other can access the database normally but must not independently run migrations for "its own tables." Do not copy the owner UUID to bypass this restriction or try to transfer ownership merely by changing the project name.

Internal records use three tables:

| Table | Stored data |
| --- | --- |
| oldman_migration_owner | UUID and name of the project maintaining the schema |
| oldman_alembic_version | Standard Alembic current-revision state |
| oldman_schema_registry | Table ownership, managed status, and the revision that changed ownership |

These names are reserved by the framework. Do not declare them as business models or manage them through fixtures.

## Generate, inspect, and apply separately

1. Change a registered App's models.
2. Ensure the database has applied every migration head in the existing source before running makemigrations. A new project with no revisions can generate its first one. If the source already has migrations but the database is uninitialized, run migrate first.
3. If several Apps have changed, select one interactively. Only that App's migration is written in one run. Generate and apply migrations in dependency order before proceeding to later Apps.
4. Read the generated file and inspect upgrade, downgrade, constraints, defaults, and effects on existing data.
5. Run migrate separately. Production deployments apply committed migrations; they do not regenerate model differences on site.

An App's default directory is `<package>/migrations/`. AppConfig.migrations_module can select another relative module. Revisions live directly in that package, without a per-App env.py or extra versions directory. Each App has its own branch. The initial revision uses the App label in branch_labels; later down_revision values point to the previous revision on that branch.

A new cross-App foreign key adds depends_on for the other App's applied head. If the target App has no migrations, has not reached its head, or has multiple heads, resolve that App first. Reordering apps does not resolve a missing dependency.

If development branches create multiple heads in one App, makemigrations first asks whether to generate a standard merge revision; it only writes the file. migrate does not generate merges for users. When installing a third-party package, choose a version whose author has merged its heads.

With no schema changes, you can interactively generate an empty revision for handwritten operations. No extra --empty option is required. The framework does not generate data-conversion logic. Review handwritten data operations and verify their rollback yourself. Do not make migrations depend on business ORM class definitions that change over time.

Migration files can be written only for writable Apps within the current project's source. Packages in site-packages or outside the project can only supply migrations to read and apply. To maintain a third-party App, work in its source project rather than forcing writes into an installed dependency.

## Renames, deletions, and external tables

To rename a table, first change only its name while retaining its structure. makemigrations compares old managed tables with new tables and asks whether you intend a rename. Confirmation generates RenameTable and updates ownership records; it **does not DROP and recreate the table**. Separate renaming from complex schema changes. If a rename cannot be identified, do not force it through by confirming deletion.

To rename a column, change its model declaration and run the same makemigrations command. A single add/delete pair prompts for a rename; with multiple candidates, you select the correspondence. A confirmed rename generates ALTER/rename instead of discarding the old column's data. Still inspect generated type, default, and constraint changes, especially when existing values cannot be converted.

To actually delete a managed table or column, enter the full table name or `table.column` to confirm. Exiting, empty input, or a mismatch does not produce a confirmed deletion. Generating the file does not delete data; migrate changes the database. Do not treat this confirmation as a recycle bin that can recover business data.

The database may contain tables owned by other systems:

- Tables without a current model or framework-managed record are treated as external and ignored, rather than deleted automatically.
- For ORM access without Oldman schema management, set `Meta.managed = False`. Business rules and database accounts still determine access permissions.
- If a formerly managed model becomes managed=False, generate and apply an ownership-release migration, retaining the physical table. Do not simply delete the model and assume its historical records disappear too.
- If a current managed model's table already exists but is unregistered, the command asks whether to keep it external, adopt it, or cancel. To keep it external, change the model's Meta first. Adoption generates a dedicated adoption revision.

An adoption revision can create the table in an empty database. If the table exists and matches the current model, confirmation skips CREATE and records ownership only. A schema mismatch is rejected; do not pretend it is synchronized. Generated upgrade/downgrade functions include consistency checks. **Do not directly edit the function bodies in this adoption file**; create a separate ordinary revision for additional operations.

Managed tables currently do not support explicit SQL schemas: Table.schema must be None. Do not confuse a schema name with a database connection URL, App label, or Python package name.

## Migrations for User extensions

All services enabling Auth select the same concrete class through app_settings.auth.user_model; an omitted value uses the default User. Listing Auth only in migration_apps, without a real service enabling Auth, is not a valid configuration.

Auth owns the `oldman_user` table and its core structure. The App containing the selected custom User manages extension columns, indexes, and constraints. A custom class inherits AbstractUser and must not override the framework's core structure. Base and extension migrations live with their respective Apps. Extension foreign keys still use `oldman_user.id`.

In a new project, first apply Auth's base migrations with the default User configuration. Then register the custom User App, switch user_model, and generate extension migrations. Existing projects should apply current heads before modifying models.

When a managed App has no initial revision (a newly added App with models, or a custom User extension without generated migrations), migrate does not silently skip it. Behavior depends on the database:

- If the database is at current heads with no other pending migrations, it refuses and asks you to run `makemigrations` and select this App first.
- If other Apps have pending migrations (a never-migrated database or new migrations from a framework upgrade), `makemigrations` cannot yet run because it requires the database to be at heads. In a terminal, migrate first asks whether to apply only the other Apps' migrations. After confirmation, it applies them and instructs you to run `makemigrations`, then `migrate`. Without a terminal, it refuses and explains that a terminal is required.
- If a third-party App lacks migrations, it always refuses. Install a version that includes migrations.

Do not create a second user table, automatically switch database table names, or copy the default User's migrations into a business App to work around this.

## Downgrades, retirement, and state recovery

downgrade shows the target and impact, checks whether other applied Apps depend on revisions being undone, and then requires confirmation. It runs revision downgrade functions but does not guarantee recovery of deleted historical data. If models remain at the newer version after a downgrade, the next generation may propose upgrading again. Project maintainers are responsible for switching back to the corresponding model version as instructed.

retire retains tables and removes only the selected App's migration state/ownership. Applied dependencies may block it. Afterwards, follow the output instructions to remove the App from relevant service settings or migration_apps. Do not delete migration files before running retire: the executor may then be unable to resolve the database's current version.

If all internal state tables are missing, migrate shows database table and source revision counts, then asks whether this is first-time use or lost state. If only some internal tables are missing, it enters recovery. Recovery does not rebuild the business database:

1. Current managed tables must exist, and their actual structure must match current models.
2. It shows the table ownership to restore, source heads, and retained external tables. For unmanaged models, it asks whether they were always external or were previously released.
3. The user explicitly confirms by entering the project name and `recover migration state`.
4. Only framework-internal state is rebuilt and stamped to source heads; no business migration DDL runs.

Recovery cannot prove that handwritten data operations or empty migrations ever ran. For a schema mismatch, maintainers must first reconcile the schema or restore a reliable backup before retrying. Do not select "first-time use" to hide accidentally deleted state or fabricate version rows.

DDL atomicity depends on the database. Not every database can roll back an entire revision transactionally. A failure retains the original error and may require inspecting SQL already executed. Back up, review, and verify formal changes against the relevant database. One SQLite example does not replace MySQL/PostgreSQL deployment acceptance testing.

<!-- source: zh/developers/migrations.md @ 877dcb4e -->
