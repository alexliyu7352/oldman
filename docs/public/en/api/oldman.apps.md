# `oldman.apps`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

@author:alex

Import with `from oldman.apps import <name>`.

## `AppConfig`

class · defined in `oldman.apps.config`

```python
class AppConfig
```

Describe one reusable App while preserving its settings type.

Constructor:

```python
AppConfig() -> None
```

Members:

- `display_name: str | LazyTranslation = ''`
- `settings_model: type[T_AppSettings] | None = None`
- `property settings: T_AppSettings` — Return the current service's validated settings instance.

## `AppNotInstalledError`

class · defined in `oldman.apps.config`

```python
class AppNotInstalledError(RuntimeError)
```

Raised when code accesses an App absent from the current Registry.

## `AppRegistry`

class · defined in `oldman.apps.registry`

```python
class AppRegistry
```

Register App metadata once while preserving the configured package order.

Constructor:

```python
AppRegistry() -> None
```

Members:

- `property packages: tuple[str, ...]` — Return package paths in their original registration order.
- `property labels: tuple[str, ...]` — Return App labels in the corresponding registration order.
- `property configs: tuple[AppConfig[Any], ...]` — Return registered AppConfig objects without exposing mutable storage.
- `property models: tuple[ModelMetadata, ...]` — Return resolved mapped model metadata after the model stage.
- `property commands: tuple[Command, ...]` — Return discovered App commands in configured App and module order.
- `def get_command(name: str) -> Command` — Return one discovered App command by its service-level CLI name.
- `def get_app_commands(label: str) -> tuple[Command, ...]` — Return commands owned by one installed App in declaration order.
- `def get_model_metadata(model: type[Any]) -> ModelMetadata` — Return Registry metadata for one mapped model class.
- `def register_packages(packages: Iterable[str]) -> None` — Import and register each package's sole public AppConfig object.
- `def get_by_package(package: str) -> AppConfig[Any]` — Return a registered AppConfig by its import package.
- `def get_by_label(label: str) -> AppConfig[Any]` — Return a registered AppConfig by its stable label.
- `def bind_settings(label: str, settings: object) -> None` — Bind one settings instance after SettingsManager validation.
- `def load_models(*, user_model_path: str | None=None) -> None` — Import each configured model module and resolve table ownership once.
- `def load_commands() -> None` — Import installed Apps' command modules after the model stage.
- `def load_views() -> None` — Import each Web module after models without allowing schema changes.
- `def load_permissions() -> None` — Import each installed App's permission declarations once, after models.
- `def load_tasks() -> None` — Import only installed Apps' tasks once, without loading Web modules.
- `def load_events() -> None` — Declare installed App handlers once; the caller owns network startup.

## `AppSettingsNotDefinedError`

class · defined in `oldman.apps.config`

```python
class AppSettingsNotDefinedError(RuntimeError)
```

Raised when an App without a settings model accesses ``app.settings``.

## `AppSettingsNotReadyError`

class · defined in `oldman.apps.config`

```python
class AppSettingsNotReadyError(RuntimeError)
```

Raised when installed App settings have not completed validation.
