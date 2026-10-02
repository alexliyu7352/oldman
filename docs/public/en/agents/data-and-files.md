# Agent guide: model changes, fixtures and file uploads

Use this guide to change an existing model, load example records, or add file fields. It does not cover a new migration
engine, a storage implementation, background cleanup workers or a permission system. Paths such as
`docs/public/zh/developers/migrations.md` are relative to the framework repository (your `.oldman-docs/` clone). Look up
every `oldman` import in the [API index](../api/README.md). Creating a model and its first migration is the first
section of [the create-service guide](create-service.md).

| Task | Reference to check, and the application files involved |
| --- | --- |
| Models and transactions | `docs/public/zh/developers/database.md`; the App's `models.py`, the service's `apps`, the real `database.url` |
| Change, rename or take over tables | `docs/public/zh/developers/migrations.md`; the project `pyproject.toml`, every service's default YAML, the App's `migrations/` |
| Example data | `docs/public/zh/developers/fixtures.md`; the App's `fixtures/*.json`, which service registers it |
| File upload and deletion | `docs/public/zh/developers/storage.md`; the `storages` settings, the model's `file_column`, the Form, the authorized view |

## Change a model: add a field

Verified on a generated `api` project with SQLite whose table already had rows.

1. Change the model in the App that owns it. Reuse existing models for read-only needs; never declare the table twice.

   ```python
   from sqlalchemy import Boolean, false
   from sqlalchemy.orm import Mapped, mapped_column

   class Note(DatabaseModel):
       ...
       pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
   ```

   A `NOT NULL` column added to a table that has rows needs a **database-side** default: `default=` only fills new
   rows from Python, so without `server_default` the generated migration fails on the existing rows
   ("Cannot add a NOT NULL column with default value NULL"). Decide with the user what existing rows should hold.
2. Check that every service using this database has the same `database.url` in its default YAML. Do not derive the
   migration scope from a test `--config` file.
3. Run `./run.sh db status`. If existing revisions are not applied yet, `./run.sh db migrate` first.
4. The user runs `./run.sh db makemigrations` in a terminal: it asks for the migration description (Enter keeps the
   suggestion, e.g. `alter notes_note`) and, when the change is ambiguous, which App and whether a change is a rename
   or a deletion. Do not invent `--app`, `--empty` or `--yes`; they do not exist. Without a terminal it stops with
   "This migration decision requires an interactive terminal."; ask the user instead of working around it.
5. Read the generated file in `apps/<app>/migrations/` before applying it: check the columns, defaults, renames and
   deletions match what the user wants.
6. Apply it: `./run.sh db migrate`. On an initialized database this runs without a terminal and applies every pending
   revision. Then `./run.sh db status` must show `pending=none`.
7. Check the real data and schema: a rename keeps rows and values; a new non-null column has a value in every old row.

If a generated revision is wrong and has **not** been applied, delete that file, fix the model and generate again. A
failed `db migrate` leaves the migration state unchanged (`db status` still lists the revision as pending). Never
recover by creating tables yourself or editing the migration state tables.

One database has one migration owner project (the `[tool.oldman].project_id` UUID in `pyproject.toml`). If the database
belongs to another `project_id`, tell the user; do not overwrite the owner or copy its UUID.

## Fixtures

Fixtures are repeatable example records, not backups or schema migrations. Put them in
`apps/<app>/fixtures/<name>.json`; `model` is `<App label>.<Python class name>`:

```json
[
  {
    "model": "notes.Note",
    "pk": 10,
    "fields": {
      "title": "Welcome",
      "body": "Created by the notes fixture.",
      "created_at": "2026-10-01T09:00:00",
      "pinned": true
    }
  }
]
```

```sh
./run.sh api loaddata notes                                    # finds apps/*/fixtures/notes.json
./run.sh api dumpdata notes.Note --output /tmp/notes.json     # always name the App or model
```

- `loaddata` creates or updates by primary key; it never clears a table. Loading the same file twice leaves one record.
  Check first that the primary keys do not collide with real data.
- A wrong type, an unknown field (e.g. "unknown field(s): titel") or a missing foreign key fails the whole load.
- A bare name is looked up in the installed Apps' `fixtures/`; several Apps with the same name is an error, pass a path.
- File columns store a name only: a fixture cannot create the uploaded file. Do not put plaintext passwords in fixtures.
- `loaddata`, `dumpdata` and `createsuperuser` are built in; do not add copies as App commands.

## File uploads

1. Decide whether the file is public or private. Private files use a storage alias that is not published as
   `web.media`; storage itself does not check user permissions.
2. The model column is `file_column` (`from oldman.storage import file_column`). Each column stores the logical name of a
   file it owns alone; do not copy one name into several fields or records to share a file.
3. The Form is the existing `TailwindModelForm` with `Meta.fields` listing every field explicitly. A file column becomes
   an `UploadField` automatically; size and extension rules use `FileSize` and `FileExtension`
   (all from `oldman.web.components.forms`). Do not write another upload widget.
4. The view checks permission and CSRF first, then builds the form from the request; for an edit it loads an instance
   the user may access and passes it as `instance`. After `await form.validate()` succeeds, inside
   `async with db_manager.get_session() as session:` call `await form.save(commit=True)` with that same session.
5. Return the success response (JSON, actions or HTML) only after the session block exits normally. `commit=True` does not
   commit early, and `commit=False` may already have written the file.
6. The model registry and the write session already manage file lifecycles. Do not delete the old file right after
   saving, and do not add database callbacks, delayed Redis queues or whole-database file scans.
7. Page forms and modals render with `form.render` and reuse the page's form loader. Return actions only when the business
   needs a follow-up; a simple success message already shows at the top of the form.

A standalone script or shell: after `bootstrap_service("<service>")`, call `storages.init_app()` if it needs storage;
web and simple services have done that already. Find files with `storages.using(alias).open`, `.exists` and `.stat`;
there is no global file URL API.

The EPG Demo (`https://github.com/alexliyu7352/oldman-epg-dashboard`) has a complete example: the `ExampleAsset` model
with two file columns (`document_path`, `preview_path`), `ExampleAssetForm`, and the create, edit and rollback views in
`apps/examples/views/storage.py`. The user-side steps are in `docs/public/zh/users/data-and-files.md`.

## Checks for the task at hand

- Transactions: a successful write can be read back; after an exception mid-transaction no partial rows remain.
- Fixtures: reloading updates instead of duplicating; one bad record fails the whole load; cross-App references resolve.
- Files: save two different fields; replacing one keeps the other; after a successful commit the old file is deleted;
  after a rollback the database keeps the old name and the old file; new file candidates are cleaned up by the final state.
- Non-file paths: a plain title update or a read must not query file state. To check performance, watch this scenario's
  SQL only; do not add production counters or test resets for it.
- HTTP: a missing file, an unauthorized user and a missing CSRF token each fail clearly. In a browser, choose a real file
  and check the message and field errors, not just status 200.
- Clean up only this task's temporary files and database; never the user's media, a real Demo or dependency directories.

Bulk SQL and database-level cascade deletes of rows that were not loaded do not clean up files automatically; tell the
user about this limit. Do not describe the current "compare with the row's previous file name" mechanism as
whole-database reference counting for shared files.
