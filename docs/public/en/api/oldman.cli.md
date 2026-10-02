# `oldman.cli`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Lazy public entry point for the Oldman command line.

Import with `from oldman.cli import <name>`.

## `Command`

class · defined in `oldman.cli.commands`

```python
class Command(ABC)
```

Define one asynchronous App command and its CLI metadata.

Members:

- `name: ClassVar[str] = ''`
- `help: ClassVar[str | LazyTranslation] = ''`
- `check_pid: ClassVar[bool] = False`
- `raw_stdout: ClassVar[bool] = False`
- `async def handle(*args: Any, **kwargs: Any) -> Any` — Run the command inside the selected service's async lifecycle.

## `main`

function · defined in `oldman.cli`

```python
def main(argv: list[str] | None=None) -> int
```

Resolve CLI localization before importing Typer and command modules.

## Module `oldman.cli.database`

Thin Typer adapter for project-wide database migration commands.

Import with `from oldman.cli.database import <name>`.

### `register_database_commands`

function · defined in `oldman.cli.database`

```python
def register_database_commands(app: typer.Typer, *, command_class: type[TyperCommand], group_class: type[TyperGroup], exit_with_error: ExitWithError) -> None
```

Register the six project-level database commands.

## Module `oldman.cli.discovery`

Public cold service discovery used by CLI assembly.

Import with `from oldman.cli.discovery import <name>`.

### `discover_services`

function · defined in `oldman.cli._service_discovery`

```python
def discover_services() -> dict[str, ServiceDefinition]
```

Return static service definitions without importing service modules.

## Module `oldman.cli.fixtures`

Service-scoped CLI commands for deterministic JSON fixtures.

Import with `from oldman.cli.fixtures import <name>`.

### `DumpData`

class · defined in `oldman.cli.fixtures`

```python
class DumpData(Command)
```

Export one installed App or model as deterministic JSON.

Members:

- `async def handle(selector: str, output: Path | None=None) -> None` — Write raw JSON to stdout or one explicit UTF-8 file.

### `fixture_commands`

function · defined in `oldman.cli.fixtures`

```python
def fixture_commands() -> tuple[Command, Command]
```

Return the two framework-owned typed service commands.

### `LoadData`

class · defined in `oldman.cli.fixtures`

```python
class LoadData(Command)
```

Load one JSON fixture inside a single database transaction.

Members:

- `async def handle(fixture: str) -> str` — Resolve one file or installed-App fixture and import it.

## Module `oldman.cli.i18n_commands`

Thin CLI delegation to the framework catalog operations.

Import with `from oldman.cli.i18n_commands import <name>`.

### `compile_catalogs`

function · defined in `oldman.cli.i18n_commands`

```python
def compile_catalogs() -> None
```

Delegate catalog compilation to the i18n implementation.

### `extract_catalog`

function · defined in `oldman.cli.i18n_commands`

```python
def extract_catalog() -> None
```

Delegate catalog extraction to the i18n implementation.

### `initialize_catalog`

function · defined in `oldman.cli.i18n_commands`

```python
def initialize_catalog(locale_name: str) -> None
```

Delegate catalog initialization with a Babel locale identifier.

### `normalize_catalog_locale`

function · defined in `oldman.cli.i18n_commands`

```python
def normalize_catalog_locale(language: str) -> tuple[str, str]
```

Return canonical BCP 47 and Babel locale codes for one language.

### `update_catalogs`

function · defined in `oldman.cli.i18n_commands`

```python
def update_catalogs() -> None
```

Delegate catalog update to the i18n implementation.

## Module `oldman.cli.localization`

CLI language selection backed by the shared Oldman i18n core.

Import with `from oldman.cli.localization import <name>`.

### `cli_config_path`

function · defined in `oldman.cli.localization`

```python
def cli_config_path() -> Path
```

Return the XDG path used only for CLI-local preferences.

### `CLI_LANGUAGE_CODES`

value · defined in `oldman.cli.localization`

```python
CLI_LANGUAGE_CODES = ('en', 'zh-Hans', 'zh-Hant')
```

### `CLI_LANGUAGE_ENV`

value · defined in `oldman.cli.localization`

```python
CLI_LANGUAGE_ENV = 'OLDMAN_CLI_LANGUAGE'
```

### `CLI_LANGUAGE_REGISTRY`

value · defined in `oldman.cli.localization`

```python
CLI_LANGUAGE_REGISTRY = LanguageRegistry({code: {} for code in CLI_LANGUAGE_CODES})
```

### `cli_translation_context`

function · defined in `oldman.cli.localization`

```python
def cli_translation_context(args: list[str]) -> Iterator[CliLanguageState]
```

Resolve, bind, report warnings, and finally reset one CLI invocation.

### `CliLanguageState`

class · defined in `oldman.cli.localization`

```python
class CliLanguageState
```

Resolved effective and persisted language values for one invocation.

Members:

- `effective: str`
- `saved: str | None`
- `source: str`
- `warnings: tuple[CliWarning, ...] = ()`

### `read_saved_language`

function · defined in `oldman.cli.localization`

```python
def read_saved_language(path: Path | None=None) -> tuple[str | None, tuple[CliWarning, ...]]
```

Read and validate the canonical language stored in the CLI JSON file.

### `resolve_cli_language`

function · defined in `oldman.cli.localization`

```python
def resolve_cli_language(args: list[str]) -> CliLanguageState
```

Resolve environment, saved, prompt, and system language precedence.

### `save_cli_language`

function · defined in `oldman.cli.localization`

```python
def save_cli_language(language: str, path: Path | None=None) -> str
```

Atomically persist one canonical CLI language and return its code.

### `use_cli_language`

function · defined in `oldman.cli.localization`

```python
def use_cli_language(language: str, *, app_packages: Iterable[str]=()) -> Iterator[None]
```

Bind the project, installed-App and framework ``messages`` catalogs.

## Module `oldman.cli.mail`

Send a test message through the configured mail backend of one service.

Import with `from oldman.cli.mail import <name>`.

### `send_test_mail`

function · defined in `oldman.cli.mail`

```python
def send_test_mail(service_module: str, recipients: Sequence[str], *, config_file: Path | None=None) -> TestMailResult
```

Bootstrap the service, then send one plain message to `recipients` like Django's sendtestemail.

### `TestMailResult`

class · defined in `oldman.cli.mail`

```python
class TestMailResult
```

What the test send did: how many messages the backend accepted and which backend that was.

Members:

- `count: int`
- `backend: str`

## Module `oldman.cli.remote`

Remote files for command-line tools: one file, one task, fetched from a base address.

Import with `from oldman.cli.remote import <name>`.

### `Refreshed`

class · defined in `oldman.cli.remote`

```python
class Refreshed
```

What `refresh()` did: the files it downloaded again, and the ones it could not with the reason.

Members:

- `updated: tuple[str, ...]`
- `failed: dict[str, str]`

### `RemoteFileError`

class · defined in `oldman.cli.remote`

```python
class RemoteFileError(Exception)
```

A remote file could not be downloaded.

### `RemoteFiles`

class · defined in `oldman.cli.remote`

```python
class RemoteFiles
```

Files under one base address, for `tui.Item(load=...)` and `tui.Item(action=...)`.

Constructor:

```python
RemoteFiles(base: str | os.PathLike[str], *, cache_dir: str | os.PathLike[str], proxy_url: str | None=None) -> None
```

Members:

- `async def fetch(path: str) -> Path` — The local file for `path`: the file itself under a local base, otherwise the cached copy,
- `async def refresh() -> Refreshed` — Download every cached file of this base again.
- `def menu(path: str) -> Callable[[], Awaitable[Menu]]` — For `tui.Item(load=...)`: the file's `menu()`, loaded when the item is chosen.
- `def action(path: str) -> Callable[[], Awaitable[None]]` — For `tui.Item(action=...)`: the file's `run()`.
- `def script(path: str, *args: str, interpreter: str, check: bool=True) -> Callable[[], Awaitable[None]]` — For `tui.Item(action=...)`: run `interpreter <file> *args` as a child process.

## Module `oldman.cli.service`

Runtime command adapters for one selected service.

Import with `from oldman.cli.service import <name>`.

### `load_selected_service`

function · defined in `oldman.cli.service`

```python
def load_selected_service(definition: ServiceDefinition, *, config_file: Path | None=None) -> tuple[type[Any], AppRegistry]
```

Bootstrap and import exactly one service for runtime commands.

### `register_application_commands`

function · defined in `oldman.cli.service`

```python
def register_application_commands(service_app: typer.Typer, service_class: type[Any], app_registry: AppRegistry, *, service_name: str, command_class: type[TyperCommand], reserved_names: AbstractSet[str]) -> None
```

Attach service commands and installed Apps' typed commands.

## Module `oldman.cli.settings`

Cold-path project settings helpers for CLI commands.

Import with `from oldman.cli.settings import <name>`.

### `ensure_cwd_on_syspath`

function · defined in `oldman.cli.settings`

```python
def ensure_cwd_on_syspath() -> None
```

Make the current project importable for explicit module discovery.

### `get_settings_manager`

function · defined in `oldman.cli.settings`

```python
def get_settings_manager(service_definition: ServiceDefinition, config_file: Path | None=None) -> SettingsManager
```

Create a manager for one cold-discovered service definition.

### `load_project_settings_schema`

function · defined in `oldman.cli.settings`

```python
def load_project_settings_schema() -> type[DefaultSettings]
```

Load the required project schema without publishing runtime settings.

### `SettingsCliError`

class · defined in `oldman.cli.settings`

```python
class SettingsCliError(RuntimeError)
```

An expected project-schema prerequisite error safe for CLI display.

Constructor:

```python
SettingsCliError(message: str, **variables: Any) -> None
```

## Module `oldman.cli.shell`

Interactive shell backed by the public service bootstrap.

Import with `from oldman.cli.shell import <name>`.

### `open_service_shell`

function · defined in `oldman.cli.shell`

```python
def open_service_shell(service_module: str, *, config_file: Path | None=None) -> ServiceBootstrapContext
```

Bootstrap one headless service context and open Python's interactive shell.

## Module `oldman.cli.staticfiles`

Lazy CLI adapter for the public staticfiles collector.

Import with `from oldman.cli.staticfiles import <name>`.

### `collect_static_files`

function · defined in `oldman.cli.staticfiles`

```python
def collect_static_files(service_definition: ServiceDefinition, config_file: Path | None=None, *, clear: bool=False) -> Any
```

Collect Web and installed-App assets for one cold service definition.
