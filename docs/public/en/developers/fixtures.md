# JSON data import and export

Fixtures are for example data, development/test data, and deliberate small data transfers. They are not database backups, schema migrations, Excel tools, or seed services that automatically populate business data. Prepare tables with [Project database migrations](migrations.md) before importing JSON.

## Commands belong to a service

The following uses the [Real demo data, migrations, and queries](../users/tutorial-tasks.md#4-import-repeatable-real-data)'s services and models directly. Run it at the demo root. Before exporting, check that the output path will not overwrite a file you need to retain:

```sh
./run.sh web dumpdata examples.ExampleProject --output /tmp/projects.json
./run.sh web dumpdata examples --output /tmp/examples.json
./run.sh web loaddata /tmp/examples.json
./run.sh web loaddata demo
```

The framework supplies these commands; no App commands.py is needed. They load the current service's configuration and App models without starting a listener. They access only models registered with this service, rather than the union of Apps across the project. This differs from project-level db commands.

A selector is an App label or an exact `label.ModelClassName`, not a database table name. Model class names are case-sensitive. Without --output, stdout contains pure JSON suitable for redirection; logs must not be mixed into fixtures. The --output parent directory must exist, and existing files are overwritten. Check the path before running the command.

loaddata first treats its argument as an existing file path. If it does not exist and is a simple name without an extension, it searches installed Apps for fixtures/<name>.json. Matching names in multiple Apps cause an ambiguity error; use an explicit path. Passing `demo.json` does not trigger a search across all Apps.

## Format

The following single-record list contains the first record from the demo's apps/examples/fixtures/demo.json. Prefer the original file for a complete import:

```json
[
  {
    "model": "examples.ExampleLogo",
    "pk": 1,
    "fields": {
      "name": "Atlas US",
      "slug": "atlas-us",
      "country_code": "US",
      "svg_path": "/static/examples/logos/atlas.svg",
      "is_available": true
    }
  }
]
```

The root must be an array. Each record has exactly model, pk, and fields, with no other top-level properties. fields uses mapped model attribute names, excluding primary keys and relationship objects. Foreign keys contain actual column values, such as team_id=12, rather than a nested team object.

Rules:

- Only registered, managed=True mapped models with single-column primary keys are supported. Composite primary keys, standalone association Tables, and unmanaged models cannot be imported or exported with this tool.
- Duplicate model+pk pairs within a file are rejected. Unknown models, unknown fields, and incorrect types raise errors rather than being silently ignored.
- Records are created or updated by model+pk. Existing records update only fields supplied in fields; missing fields are not automatically cleared.
- For new records missing required fields, model defaults and database constraints determine the result. The absence of early missing-field validation does not mean arbitrary incomplete data can be inserted.
- Existing records absent from the file remain unchanged. Tables are not cleared, and deletions are not synchronized.
- The entire file runs in one write transaction. A unique-constraint violation or other write error rolls back that file's business changes.

Values are restored according to SQLAlchemy column types: strings, integers, booleans, finite floats, date/time/datetime, Decimal, UUID, Enum, and JSON. Dates and times use ISO text; Decimal and UUID use strings. Booleans are not integers: true must not stand in for primary key 1. bytes/BLOB and arbitrary inferred conversions for custom types are unsupported. Actual file contents are not packaged in JSON; file columns export only logical names.

## Foreign keys, ordering, and scope

Export orders selected models by foreign-key dependencies and records within each model by primary key, producing UTF-8 JSON. Selecting one App does not recursively export all dependent Apps' data. The destination must already contain referenced records, or the necessary records must be explicitly included in the same fixture.

Import validates the file and foreign-key targets before ordering dependencies among new records. References can target records in the same file or existing database records. Missing references and unresolvable cycles among new records raise errors; foreign-key constraints are not temporarily disabled. After importing explicit integer primary keys, PostgreSQL sequences are advanced accordingly; SQLite/MySQL follow their native behavior. Sequence numbers need not be contiguous, and rollback does not guarantee restoration of their previous values.

Import writes through an ORM Session without calling ModelForm cleaning, ModelAdmin.save_model, or password-creation commands. Password fields do not automatically hash plaintext. Prefer createsuperuser/changepassword for account creation. Changes to file columns may trigger model-file cleanup. Understand [File storage and model file fields](storage.md#model-file-replacement-and-deletion) first; importing is not a side-effect-free string copy.

The entire JSON document and all selected export records are held in memory. This is not a streaming backup tool for large datasets. Developers should limit model scope and protect export files containing personal data, password hashes, or private paths.

## Python entry points

`oldman.db.fixtures` exposes:

- `await dump_data(registry, database_manager, selector) -> str`
- `resolve_fixture_path(registry, value: str | Path) -> Path`
- `await load_data(registry, database_manager, fixture_path: Path) -> int`

registry comes from `bootstrap_service("web").apps` or an existing service context. Do not construct a model list manually to bypass service scope. The returned count is the number of records in the file, not the number of newly inserted rows. For a one-off script, bootstrap before importing business modules and close the database resources you use when finished.

For practical data preparation, see [Real demo data, migrations, and queries](../users/tutorial-tasks.md). For uploads and file-column usage, see [Demo data import and file upload](../users/data-and-files.md).

<!-- source: zh/developers/fixtures.md @ 60ab2b58 -->
