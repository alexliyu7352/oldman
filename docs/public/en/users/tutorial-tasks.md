# Real Demo Data, Migrations, and Queries

First prepare the EPG Dashboard following the [Running guide](getting-started.md). This chapter consistently uses the demo's actual models, including `ExampleTeam` and `ExampleProject`, without creating similar models with the same names.

The data source is [apps/examples/models.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/models.py); initial data is in [apps/examples/fixtures/demo.json](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/fixtures/demo.json). Browser operations and the source below use the same implementation.

## 1. App, model, and table names

The complete contents of the demo's [apps/examples/apps.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/apps.py):

```python
"""Dashboard examples application metadata."""

from oldman.apps import AppConfig
from oldman.i18n import gettext_lazy as _

from .settings import ExamplesSettings


class ExamplesAppConfig(AppConfig[ExamplesSettings]):
    """Own the Dashboard's reusable example data and views."""

    label = "examples"
    display_name = _("Dashboard Examples")
    icon = "ri-flask-line"
    settings_model = ExamplesSettings


app = ExamplesAppConfig()

__all__ = ["ExamplesAppConfig", "app"]
```

The service YAML's `apps` list includes `apps.examples`. The framework obtains the above `app` through this package path, then loads models and Web views. The metadata module does not import models or start the service itself.

Keep these names distinct:

| Name | Meaning |
| --- | --- |
| apps.examples | Python App package installed by the service |
| examples | Stable App label used in commands such as fixture operations |
| ExampleProject | Model class name |
| example_project | Model's database table name |
| examples.ExampleProject | Model identifier in fixtures, rather than a Python import path |

`display_name` and `icon` control UI presentation without changing table names or model identifiers. The model's own `Meta.verbose_name` and `verbose_name_plural` describe its display names.

## 2. Understand relationships and constraints

Do not save this section as a separate simplified model. Complete declarations, including indexes, constraints, relationships, and display metadata, are in models.py above.

- `ExampleTeam` represents a team, with table name `example_team`.
- `ExampleProject` represents a project; `team_id` is an actual foreign key to `example_team.id`. The `team` relationship supplies the displayed team name.
- A project's `slug` is unique, `budget` cannot be negative, and `progress` must be between 0 and 100. Browser or Form validation does not replace these database constraints.
- `ExampleTask` relates to projects through `project_id` and also supports the drag-and-drop review example. It is not a task model from another tutorial containing only a title and completion status.
- `ExampleAsset` declares two file fields through `file_column()`; the database still stores logical file names. See [Data and files](data-and-files.md) for uploads.
- `ExampleServer` and `ExampleServerMetric` store the server inventory and monitoring samples respectively, for realtime tables and charts.

Ordinary SQLAlchemy columns still use `Mapped`, `mapped_column`, `ForeignKey`, and similar declarations. All models use the framework's shared metadata; do not create another Base for the same App to bypass registration.

## 3. Run existing migrations on the first run

The demo includes standard Alembic revisions, including the [initial examples migration](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/migrations/a839bf3055f2_create_example_models.py). To use them, run in the demo root:

```sh
./run.sh db migrate
./run.sh db status
./run.sh db history
```

Follow the prompts to distinguish first use from lost state, rather than deleting the database to bypass the issue. Normally, status lists no pending migrations after migrate completes; history shows migration history from source.

Run the following only when you**actually change model structure**:

```sh
./run.sh db makemigrations
```

Follow the interactive prompts to choose the App for this change and confirm differences and the description. Inspect the generated revision's upgrade/downgrade, then execute `db migrate` separately. Deploy committed migration files; do not regenerate them on the server.

`db` is a project-level command that reads database and App definitions from the project's actual services; it is not `web db`. Do not copy parameters such as `--app` and `--empty` from other migration tools. See the [Migration reference](../developers/migrations.md) for detailed interactions, table ownership, renaming, and recovery rules.

The project's `pyproject.toml` already contains a stable `tool.oldman.project_id`. Do not change it to resolve migration errors or use this demo to take over another system's production database.

## 4. Import repeatable real data

```sh
./run.sh web loaddata demo
```

This finds `apps/examples/fixtures/demo.json` by name, rather than executing a server startup hook. The file contains data for multiple installed Apps, so EPG business pages and feature examples can each read their own records.

The first record at the beginning of the file is:

```json
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
```

The complete fixture is a list of records; the object above is only one entry and cannot replace the entire file. Logo SVGs are in the App's static directory. Importing the database does not replace `web static collect`.

loaddata creates or updates records by model and primary key:

- Reimporting does not turn the same primary key into a new record.
- Fields explicitly provided in the file are updated, potentially overwriting edits to preset rows.
- Other records absent from the fixture are not deleted.
- It does not migrate table structure or package uploaded files, and it is not a database backup tool.

Export using the existing commands in the demo README:

```sh
./run.sh web dumpdata examples --output /tmp/examples.json
./run.sh web dumpdata examples.ExampleProject --output /tmp/projects.json
```

First ensure the output paths contain no files you want to keep, or choose your own explicit paths. The first command selects the entire examples App; the second selects only the project model and**does not automatically export related teams**. Prepare foreign key dependencies before importing a single-model file into another database. Do not disable foreign keys to make it pass. The creator cleans up temporary exports after use.

## 5. Static tables also read the database

“Static” in `/examples/tables/static` refers to initial HTML rendering, rather than hardcoded fake data. The original function called by the view in [apps/examples/services.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/services.py):

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

This is a function excerpt from an existing module, rather than a standalone script. The file already imports `db_manager` from `oldman.db`, `select` and `selectinload` from SQLAlchemy, and models from the current App. Run the complete demo directly; do not paste this into the App metadata module.

It does four things:

1. Creates a read-only Session using the current service's database settings.
2. Orders by project ID and limits the returned count.
3. Eagerly loads the team relationship needed by the template, avoiding implicit queries after leaving the Session.
4. Releases the Session on leaving the context, then lets the view render the page.

Dynamic HTML/JSON tables use `ExampleProjectTable.get_queryset()`; Table handles pagination, searching, and sorting. See the [next chapter](tutorial-dashboard.md) for wiring.

## 6. Writes, commits, and checks

Project creation and updates are in [apps/examples/views/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tables.py):

- `db_manager.get_session()` manages a write transaction.
- `ExampleProjectForm.from_request(..., session=session)` binds the request and uses the same Session to validate teams, duplicate slugs, and other checks.
- After validation, `form.save(commit=True, session=session)` writes and flushes the instance. The actual commit occurs when the context exits normally.
- Successful JSON actions are returned after leaving the context. Database failures must not appear as successful saves.

Do not make AsyncSession a global shared across requests or close the entire database engine after every request.

To verify, use the next chapter's Modal to create your own test project. Inspect it through static, HTML, and JSON tables, using the same query conditions to find it. The static page shows only the first 12 rows, so absence there does not imply save failure; dynamic tables support searching. Data should remain after refresh or restart. Duplicate slugs and reversed dates should fail without adding records.

## Close database connections owned by the service

On service shutdown, the framework closes the process's database connection pool after business shutdown hooks. [services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py) needs no shutdown hook for this, and an individual list view must not close it either. See the [Application reference](../developers/applications.md) for other lifecycle details, commands, and IDE initialization; see the [Fixture reference](../developers/fixtures.md) for fixture type validation and transaction failure rules.

The next chapter opens the demo's two dynamic table pages directly, following the same model to see how Form, Modal, response actions, and Page connect.

<!-- source: zh/users/tutorial-tasks.md @ 60ab2b58 -->
