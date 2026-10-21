# `oldman.testing`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Local verification tools for real browsers, process trees, and PNG evidence.

Import with `from oldman.testing import <name>`.

## `BrowserGateError`

class · defined in `oldman.testing.gates`

```python
class BrowserGateError(RuntimeError)
```

Gate setup, execution, or cleanup failure.

## `BrowserResult`

class · defined in `oldman.testing.browser`

```python
class BrowserResult
```

Collect browser errors independently from product assertions.

Members:

- `console_errors: list[str] = field(default_factory=list)`
- `page_errors: list[str] = field(default_factory=list)`
- `bad_responses: list[dict[str, Any]] = field(default_factory=list)`
- `property ok: bool`

## `BrowserVerificationError`

class · defined in `oldman.testing.browser`

```python
class BrowserVerificationError(RuntimeError)
```

Raised when a local Chrome verification cannot continue.

## `capture_screenshot`

function · defined in `oldman.testing.browser`

```python
def capture_screenshot(client: CDPClient, *, capture_beyond_viewport: bool=True) -> bytes
```

Capture a PNG from the current page.

## `CDPClient`

class · defined in `oldman.testing.browser`

```python
class CDPClient
```

Chrome DevTools client with console, page and network error collection.

Constructor:

```python
CDPClient(websocket_url: str, result: BrowserResult) -> None
```

Members:

- `def close() -> None`
- `def command(method: str, params: dict[str, Any] | None=None, *, timeout: float=10.0) -> dict[str, Any]`
- `def evaluate(expression: str, *, timeout: float=10.0) -> Any`
- `def wait_for_load(timeout: float=15.0) -> None`
- `def pump(seconds: float) -> None`

## `child_subreaper`

function · defined in `oldman.testing.process_tree`

```python
def child_subreaper() -> Iterator[tuple[int, frozenset[tuple[int, int]]]]
```

Adopt descendants that escape their original process group/session.

## `ChromePage`

class · defined in `oldman.testing.browser`

```python
class ChromePage
```

Context manager for an isolated local headless Chrome page.

Constructor:

```python
ChromePage(result: BrowserResult, *, accept_language: str | None=None) -> None
```

## `clear_origin`

function · defined in `oldman.testing.browser`

```python
def clear_origin(client: CDPClient, origin: str) -> None
```

## `configure_viewport`

function · defined in `oldman.testing.browser`

```python
def configure_viewport(client: CDPClient, width: int, height: int, *, mobile: bool) -> None
```

## `duplicate_functions`

function · defined in `oldman.testing.duplication`

```python
def duplicate_functions(left_root: Path, right_root: Path, *, min_lines: int=6, exclude_names: Sequence[str]=(), exclude_directories: Iterable[str]=()) -> list[DuplicateFunction]
```

Find same-named, structurally identical functions across two source trees.

## `ensure_gate_admin`

function · defined in `oldman.testing.gates`

```python
def ensure_gate_admin(config_file: Path, *, environment: Mapping[str, str], project_root: Path, username: str, password: str, email: str='oldman@example.com', service: str='web') -> None
```

Create the gate administrator through public bootstrap and ensure_superuser APIs.

## `find_chrome`

function · defined in `oldman.testing.browser`

```python
def find_chrome() -> str
```

Return an installed Chrome/Chromium executable.

## `find_free_port`

function · defined in `oldman.testing.browser`

```python
def find_free_port() -> int
```

## `forbidden_attributes`

function · defined in `oldman.testing.duplication`

```python
def forbidden_attributes(root: Path, *, attributes: Sequence[str], exclude_directories: Iterable[str]=()) -> list[SourceReference]
```

Find attribute chains such as a.b.c to prevent bypassing public entry points.

## `forbidden_imports`

function · defined in `oldman.testing.duplication`

```python
def forbidden_imports(root: Path, *, modules: Sequence[str], allowed_names: Sequence[str]=(), exclude_directories: Iterable[str]=()) -> list[SourceReference]
```

Find imports from prefix-matched modules, permitting names in allowed_names.

## `gate_settings`

function · defined in `oldman.testing.gates`

```python
def gate_settings(example_file: Path, state_root: Path, *, service_port: int, redis_url: str, namespace: str, database_name: str='gate.sqlite3', static_dir: Path | None=None, host: str=DEFAULT_HOST, customize: Callable[[dict], None] | None=None) -> Path
```

Rewrite project web_settings.example.yaml as complete configuration pointing only to temporary directories.

## `identical_files`

function · defined in `oldman.testing.duplication`

```python
def identical_files(left_root: Path, right_root: Path, *, suffixes: Sequence[str]=('.py', '.ts', '.html'), exclude_directories: Iterable[str]=(), min_bytes: int=200) -> list[IdenticalFile]
```

Find byte-identical same-named files across two source trees.

## `launch_chrome`

function · defined in `oldman.testing.browser`

```python
def launch_chrome(port: int, profile: str, *, stderr: int | BinaryIO=subprocess.DEVNULL, accept_language: str | None=None) -> subprocess.Popen[bytes]
```

Start one isolated headless Chrome.

## `linux_process_table`

function · defined in `oldman.testing.process_tree`

```python
def linux_process_table() -> dict[int, tuple[int, int, int, str]]
```

Return PID -&gt; (PPID, process group, start time, state) from procfs.

## `minimal_environment`

function · defined in `oldman.testing.gates`

```python
def minimal_environment(source: Mapping[str, str] | None=None) -> dict[str, str]
```

Keep only environment variables needed by local tools and fix the hash seed, timezone, and language.

## `navigate`

function · defined in `oldman.testing.browser`

```python
def navigate(client: CDPClient, url: str) -> None
```

## `owned_redis_server`

function · defined in `oldman.testing.gates`

```python
def owned_redis_server(state_root: Path, *, environment: Mapping[str, str], host: str=DEFAULT_HOST) -> Iterator[str]
```

Start nonpersistent Redis and verify process-group and port release on exit.

## `owned_service`

function · defined in `oldman.testing.gates`

```python
def owned_service(config_file: Path, *, environment: Mapping[str, str], project_root: Path, service: str='web', name: str='service') -> Iterator[subprocess.Popen[bytes]]
```

Start a gate-owned foreground service group and confirm its complete cleanup on exit.

## `PngEvidence`

class · defined in `oldman.testing.png_evidence`

```python
class PngEvidence
```

Content identity and decoded dimensions of one retained PNG.

Members:

- `bytes: int`
- `height: int`
- `sha256: str`
- `width: int`

## `PngEvidenceError`

class · defined in `oldman.testing.png_evidence`

```python
class PngEvidenceError(RuntimeError)
```

Raised when browser evidence is not one complete, safe PNG.

## `ProcessTreeError`

class · defined in `oldman.testing.process_tree`

```python
class ProcessTreeError(RuntimeError)
```

Raised when a gate cannot prove complete process-tree cleanup.

## `ProcessTreeTracker`

class · defined in `oldman.testing.process_tree`

```python
class ProcessTreeTracker
```

Track one leader plus descendants, including adopted new-session children.

Members:

- `leader_pid: int`
- `adopted_parent: int`
- `ignored_adoptees: frozenset[tuple[int, int]]`
- `owned: dict[int, tuple[int, int]] = field(default_factory=dict)`
- `def remember() -> dict[int, tuple[int, int, int, str]]`
- `def live(table: Mapping[int, tuple[int, int, int, str]] | None=None) -> dict[int, tuple[int, int, int, str]]`
- `def reap() -> None`
- `def wait_for_exit(process: subprocess.Popen[Any], timeout: float) -> list[int]`
- `def signal_leader(signum: int, *, require_live_leader: bool=False) -> bool` — Signal only the live leader and prove delivery to its recorded identity.
- `def wait_for_leader_state(expected: frozenset[str], timeout: float) -> bool` — Wait until the recorded leader identity enters one of the requested procfs states.
- `def signal(signum: int, *, require_live_leader: bool=False) -> bool` — Signal all live identities and report whether the leader accepted the signal.
- `def terminate(process: subprocess.Popen[Any], *, require_live_leader: bool=True, term_timeout: float=10.0, kill_timeout: float=5.0) -> None` — Terminate, reap, and prove removal of the complete owned process tree.

## `require_png`

function · defined in `oldman.testing.png_evidence`

```python
def require_png(path: Path, *, min_width: int=300, min_height: int=200) -> PngEvidence
```

Parse chunks, CRCs and scanlines; reject headers or corrupt image lookalikes.

## `run_browser_child`

function · defined in `oldman.testing.gates`

```python
def run_browser_child(command: Sequence[str], *, environment: Mapping[str, str], project_root: Path, browser: str, timeout: float=180, label: str='gate') -> dict
```

Run a real-browser child process and require a clean success payload.

## `save_screenshot`

function · defined in `oldman.testing.browser`

```python
def save_screenshot(client: CDPClient, path: str, *, capture_beyond_viewport: bool=True) -> bytes
```

Capture a PNG, write the artifact, and return the encoded bytes.

## `tracked_popen`

function · defined in `oldman.testing.process_tree`

```python
def tracked_popen(*args: Any, **kwargs: Any) -> Iterator[tuple[subprocess.Popen[Any], ProcessTreeTracker]]
```

Launch one process after enabling subreaping and yield it with its tracker.

## `tracked_process_tree`

function · defined in `oldman.testing.process_tree`

```python
def tracked_process_tree(process: subprocess.Popen[Any]) -> Iterator[ProcessTreeTracker]
```

Create a subreaper-backed tracker for an already launched leader.

## `use_owned_redis`

function · defined in `oldman.testing.gates`

```python
def use_owned_redis(payload: dict, redis_url: str) -> None
```

Point every Redis alias of one settings payload at the gate's own Redis, one database each.

## `wait_for_service`

function · defined in `oldman.testing.gates`

```python
def wait_for_service(process: subprocess.Popen[bytes], service_port: int, *, host: str=DEFAULT_HOST, timeout: float=30, name: str='service') -> None
```

Wait for service listening, failing immediately on early process exit rather than waiting until timeout.

## `WebSocket`

class · defined in `oldman.testing.browser`

```python
class WebSocket
```

Minimal RFC 6455 client for local Chrome DevTools traffic.

Constructor:

```python
WebSocket(url: str, timeout: float=10.0) -> None
```

Members:

- `def close() -> None`
- `def send_json(payload: dict[str, Any]) -> None`
- `def recv_json(timeout: float | None=None) -> dict[str, Any] | None`

## Module `oldman.testing.duplication`

Detect existing duplicate implementations through tests rather than relying on memory.

Import with `from oldman.testing.duplication import <name>`.

### `DEFAULT_EXCLUDED_DIRECTORIES`

value · defined in `oldman.testing.duplication`

```python
DEFAULT_EXCLUDED_DIRECTORIES = frozenset({'.git', '.mypy_cache', '.pytest_cache', '.ruff_cache', '.venv', '.worktrees', '__pycache…
```

### `DuplicateFunction`

class · defined in `oldman.testing.duplication`

```python
class DuplicateFunction
```

A same-named function with structurally identical implementations in two source trees.

Members:

- `name: str`
- `left: Path`
- `right: Path`
- `lines: int`
- `def describe(*, left_root: Path | None=None, right_root: Path | None=None) -> str` — Return a readable one-line description for assertion failures.

### `function_digests`

function · defined in `oldman.testing.duplication`

```python
def function_digests(root: Path, *, min_lines: int=6, exclude_names: Sequence[str]=(), exclude_directories: Iterable[str]=()) -> dict[tuple[str, str], list[tuple[Path, int]]]
```

Map names and fingerprints of sufficiently long functions to their source-tree locations.

### `IdenticalFile`

class · defined in `oldman.testing.duplication`

```python
class IdenticalFile
```

Files with identical contents in two source trees.

Members:

- `left: Path`
- `right: Path`
- `def describe(*, left_root: Path | None=None, right_root: Path | None=None) -> str`

### `iter_python_files`

function · defined in `oldman.testing.duplication`

```python
def iter_python_files(root: Path, *, exclude_directories: Iterable[str]=()) -> Iterator[Path]
```

Iterate Python files in a source tree, excluding caches, virtual environments, and migrations.

### `SourceReference`

class · defined in `oldman.testing.duplication`

```python
class SourceReference
```

An import or attribute access that must not appear.

Members:

- `path: Path`
- `line: int`
- `text: str`
- `def describe(*, root: Path | None=None) -> str`

## Module `oldman.testing.gates`

Run browser gates in fully owned temporary environments with free ports, Redis, configuration, and foreground services.

Import with `from oldman.testing.gates import <name>`.

### `DEFAULT_HOST`

value · defined in `oldman.testing.gates`

```python
DEFAULT_HOST = '127.0.0.1'
```

### `ENVIRONMENT_ALLOWLIST`

value · defined in `oldman.testing.gates`

```python
ENVIRONMENT_ALLOWLIST = frozenset({'CHROME_BIN', 'DISPLAY', 'FIREFOX_BIN', 'HOME', 'LD_LIBRARY_PATH', 'OLDMAN_CHROME_HEADLE…
```

### `find_free_port`

function · defined in `oldman.testing.gates`

```python
def find_free_port(host: str=DEFAULT_HOST) -> int
```

Return a currently unused loopback port.

### `FirstUseInteraction`

class · defined in `oldman.testing.gates`

```python
class FirstUseInteraction
```

Allow only first-use confirmation during migration, treating other questions as gate wiring errors.

Members:

- `def choose(prompt: str, choices: tuple[str, ...]) -> str`
- `def confirm(prompt: str, *, default: bool=False) -> bool`
- `def text(prompt: str, *, default: str) -> str`

### `migrate_gate_database`

function · defined in `oldman.testing.gates`

```python
def migrate_gate_database(config_file: Path, state_root: Path, *, project_root: Path, service: str='web') -> None
```

Build a minimal temporary project and apply reviewed migrations to the gate-owned database.

### `port_is_open`

function · defined in `oldman.testing.gates`

```python
def port_is_open(port: int, host: str=DEFAULT_HOST) -> bool
```

Check whether a port already has a listener.

### `process_group_exists`

function · defined in `oldman.testing.gates`

```python
def process_group_exists(process_group: int) -> bool
```

Check whether a process group still exists, which must be False after cleanup.

### `redis_database_url`

function · defined in `oldman.testing.gates`

```python
def redis_database_url(redis_url: str, database: int) -> str
```

Select a logical database on gate-owned Redis.

### `service_command`

function · defined in `oldman.testing.gates`

```python
def service_command(config_file: Path, *, service: str='web') -> list[str]
```

Build a foreground service command using normal bootstrap and service discovery.

## Module `oldman.testing.notifications`

Verify the full persistent-notification flow in a real browser for reuse by host-project gates.

Import with `from oldman.testing.notifications import <name>`.

### `ExtraFirefoxSteps`

value · defined in `oldman.testing.notifications`

```python
ExtraFirefoxSteps = Callable[['FirefoxBiDi', str, str, dict[str, Any]], None]
```

### `FirefoxBiDi`

class · defined in `oldman.testing.notifications`

```python
class FirefoxBiDi
```

Minimal WebDriver BiDi client used only for the compatibility smoke.

Constructor:

```python
FirefoxBiDi(port: int) -> None
```

Members:

- `def close() -> None`
- `def command(method: str, params: dict[str, Any] | None=None, *, timeout: float=15) -> dict[str, Any]`
- `def evaluate(context: str, expression: str) -> Any`

### `HostContract`

class · defined in `oldman.testing.notifications`

```python
class HostContract
```

URLs owned by one notification host.

Members:

- `name: str`
- `home_path: str`
- `login_path: str`
- `center_path: str`

### `notification_gate_main`

function · defined in `oldman.testing.notifications`

```python
def notification_gate_main(*, host: HostContract, project_root: Path, argv: list[str] | None=None, extra_firefox_steps: ExtraFirefoxSteps | None=None) -> int
```

Parse gate arguments, run the selected browser, and print one machine-readable result.

### `run_verification`

function · defined in `oldman.testing.notifications`

```python
def run_verification(*, browser: str, base_url: str, config_file: Path, project_root: Path, host: HostContract, username: str, password: str, extra_firefox_steps: ExtraFirefoxSteps | None=None) -> tuple[int, dict[str, Any]]
```

Run one selected real browser and return a strict JSON record.
