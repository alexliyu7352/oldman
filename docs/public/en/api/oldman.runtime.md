# `oldman.runtime`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Lazy public exports for service discovery, bootstrap, and runtimes.

Import with `from oldman.runtime import <name>`.

## `BaseApplication`

lazy attribute · defined in `oldman.runtime`

```python
BaseApplication
```

Provided on first access by `oldman.runtime.__getattr__`.

## `bootstrap_service`

lazy attribute · defined in `oldman.runtime`

```python
bootstrap_service
```

Provided on first access by `oldman.runtime.__getattr__`.

## `discover_service_definitions`

lazy attribute · defined in `oldman.runtime`

```python
discover_service_definitions
```

Provided on first access by `oldman.runtime.__getattr__`.

## `get_service_definition`

lazy attribute · defined in `oldman.runtime`

```python
get_service_definition
```

Provided on first access by `oldman.runtime.__getattr__`.

## `load_service_class`

lazy attribute · defined in `oldman.runtime`

```python
load_service_class
```

Provided on first access by `oldman.runtime.__getattr__`.

## `ServiceBootstrapContext`

lazy attribute · defined in `oldman.runtime`

```python
ServiceBootstrapContext
```

Provided on first access by `oldman.runtime.__getattr__`.

## `ServiceDefinition`

lazy attribute · defined in `oldman.runtime`

```python
ServiceDefinition
```

Provided on first access by `oldman.runtime.__getattr__`.

## `SimpleApplication`

lazy attribute · defined in `oldman.runtime`

```python
SimpleApplication
```

Provided on first access by `oldman.runtime.__getattr__`.

## `TaskiqSchedulerApplication`

lazy attribute · defined in `oldman.runtime`

```python
TaskiqSchedulerApplication
```

Provided on first access by `oldman.runtime.__getattr__`.

## `TaskiqWorkerApplication`

lazy attribute · defined in `oldman.runtime`

```python
TaskiqWorkerApplication
```

Provided on first access by `oldman.runtime.__getattr__`.

## `WebApplication`

lazy attribute · defined in `oldman.runtime`

```python
WebApplication
```

Provided on first access by `oldman.runtime.__getattr__`.

## Module `oldman.runtime.discovery`

Discover service definitions without importing application modules.

Import with `from oldman.runtime.discovery import <name>`.

### `discover_service_definitions`

function · defined in `oldman.runtime.discovery`

```python
def discover_service_definitions(project_root: str | Path) -> dict[str, ServiceDefinition]
```

Return direct ``services/*.py`` definitions without importing them.

### `get_service_definition`

function · defined in `oldman.runtime.discovery`

```python
def get_service_definition(name: str, project_root: str | Path) -> ServiceDefinition
```

Return one named service or report the available cold definitions.

### `load_service_class`

function · defined in `oldman.runtime.discovery`

```python
def load_service_class(definition: ServiceDefinition) -> type[BaseApplication]
```

Import the selected service and validate it against the cold definition.

### `ServiceDefinition`

class · defined in `oldman.runtime.discovery`

```python
class ServiceDefinition
```

Static facts required to select one service before configuration loads.

Members:

- `module_name: str`
- `module_path: Path`
- `application_base: ApplicationBase`

## Module `oldman.runtime.web`

Sanic-backed Oldman Web application runtime.

Import with `from oldman.runtime.web import <name>`.

### `WebApplication`

class · defined in `oldman.runtime.web`

```python
class WebApplication(BaseApplication)
```

Base application for Oldman services served by Sanic.

Constructor:

```python
WebApplication(app_name: str | None=None, pid_file_path: str | None=None, log_file_path: str | None=None, config: ServiceBootstrapContext | None=None) -> None
```

Members:

- `SESSION_MODEL: ClassVar[type[SessionData]] = SessionData`
- `property runtime_app: WebApp | None` — Return the initialized Web application without requiring a Sanic import.
- `def get_ext_config() -> Mapping[str, Any] | None` — Return Sanic-Ext configuration supplied by a concrete service.
- `def get_extension() -> list[Extension | type[Extension]] | None` — Return the default Sanic-Ext extension set.
- `def get_runtime_config() -> dict[str, Any] | None` — Return low-level Sanic configuration overrides.
- `def init() -> None` — Create and configure the Sanic application owned by this service.
- `async def main_process_ready(app: WebApp) -> None` — Run after the Sanic primary process is ready.
- `async def before_server_start(app: WebApp) -> None` — Initialize request-time Web services inside each server worker.
- `async def after_server_start(app: WebApp) -> None` — Run after one Sanic server worker starts.
- `async def before_server_stop(app: WebApp) -> None` — Cancel worker-owned background tasks before resources are closed.
- `async def after_server_stop(app: WebApp) -> None` — Hook after the server stopped, while taskiq and NATS are still open.
- `def create_app() -> WebApp` — Initialize and return this service's Sanic application.
- `def prepare_server(app: WebApp) -> None` — Configure Sanic's listener from the `web` settings.
- `def run(*args: Any, **kwargs: Any) -> None` — Create the primary app and enter Sanic's server lifecycle.
