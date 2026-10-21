# Remote files

`oldman.cli.remote` lets an operations tool's menu use files hosted elsewhere. Each remote file handles one task or problem. Files can be added or changed after the tool is released without redeploying the tool itself. They live under a **base location**: a GitHub repository's raw URL, your own file server, or a local directory during development.

There are two kinds of remote files:

- **Python files** load and run within the tool's own command. The database, Redis, and settings are already initialized with the tool's configuration, so these files can directly perform operations such as cleaning data or changing configuration. Each file exports `run()` for a task or `menu()` for its own submenu.
- **Scripts**, such as shell or Python scripts, run as child processes and communicate with the tool only through arguments and environment variables.

Both kinds appear in the [Terminal interaction](tui.md#menus), alongside local actions.

## Tool-side setup

The tool's menu is an App command of its own. Store the base location in App settings. Use a tagged GitHub raw URL in production and a local directory on development machines.

```python
# apps/ops/remote.py
from apps.ops.apps import app
from oldman.cli.remote import RemoteFiles
from oldman.conf import settings

remote = RemoteFiles(app.settings.remote_base, cache_dir=settings.core.data_dir / "remote")
```

This module reads settings when imported, so only commands, menus, and remote files may import it. Neither `apps.py` nor `models.py`, nor modules imported by them, may import it. The `db` command loads Apps and models without loading settings. Pulling this module into that chain raises `Oldman settings are not configured`, even though service commands still run normally, making the problem easy to overlook.

```python
# apps/ops/commands.py
from apps.ops.remote import remote
from oldman.cli import Command, tui


async def update_remote_files() -> None:
    refreshed = await remote.refresh()
    tui.success("Updated %d remote files" % len(refreshed.updated))
    for reason in refreshed.failed.values():
        tui.warning(reason)


MAIN_MENU = tui.Menu(
    "Maintenance",
    [
        tui.Item("Nginx", load=remote.menu("nginx.py")),
        tui.Item("Clean old access logs", action=remote.action("cleanup.py")),
        tui.Item("Hotfix", action=remote.script("hotfix.sh", interpreter="bash")),
        tui.Item("Update remote files", action=update_remote_files),
    ],
)


class Maintain(Command):
    """Open the maintenance menu."""

    name = "maintain"
    help = "Open the maintenance menu."

    async def handle(self) -> None:
        await tui.run_menu(MAIN_MENU)
```

```yaml
# data/ops_settings.yaml
app_settings:
  ops:
    remote_base: https://raw.githubusercontent.com/example/ops-files/v1.2.0/remote
    # Development: remote_base: ../ops-files/remote
```

`remote_base` is a setting owned by this tool's App; see [Configuration reference](configuration.md#app-settings). The framework does not prescribe its name. `AccessLog` in `apps/ops/models.py` likewise belongs to the tool.

| Member | Behavior |
| --- | --- |
| `RemoteFiles(base, *, cache_dir, proxy_url=None)` | `base` is an `http://` or `https://` URL, or a local directory. URLs may include `user:pass@`, but must not have a query string or `#` fragment. You must supply `cache_dir` explicitly. |
| `menu(path)` | Pass it to `Item(load=...)`. Selection fetches and loads the file, then calls its `menu()`. |
| `action(path)` | Pass it to `Item(action=...)`. Selection fetches and loads the file, then uses `await` to call its `run()`. |
| `script(path, *args, interpreter, check=True)` | Pass it to `Item(action=...)`. Selection fetches the file, then runs `interpreter <file> *args`. |
| `await fetch(path)` | This returns the file's local path. Remote files also use it to fetch data files they need, such as configuration templates. |
| `await refresh()` | This redownloads every cached file under the base location and returns `Refreshed`. `updated` contains downloaded paths; `failed` contains paths that failed and their reasons. |

`path` is a file path relative to the base location, such as `nginx.py` or `checks/ssh.py`. A path beginning with `/`, containing `..`, or consisting only of `.` raises `ValueError` when the menu item is constructed.

## Remote Python files

```python
# cleanup.py: one task per file
from datetime import timedelta

from sqlalchemy import delete

from apps.ops.models import AccessLog
from oldman.cli import tui
from oldman.db import db_manager
from oldman.utils.date import naive_utcnow


async def run() -> None:
    days = tui.ask("Keep how many days", type=int, default=30, key="cleanup.days")
    async with db_manager.get_session() as session:
        result = await session.execute(delete(AccessLog).where(AccessLog.created_at < naive_utcnow() - timedelta(days=days)))
    tui.success("Removed %d rows" % result.rowcount)
```

```python
# nginx.py: supplies its own submenu
from oldman import ops
from oldman.cli import tui


async def reload() -> None:
    await ops.systemd.reload("nginx", command=("sudo", "systemctl"))
    tui.success("nginx reloaded")


async def menu() -> tui.Menu:
    return tui.Menu("Nginx", [tui.Item("Reload", action=reload)])
```

- Define exactly one of `async def run()` and `async def menu()` within the file, without parameters. `menu()` returns a `tui.Menu` and can generate it from current conditions, such as the list of existing sites. Selection fails and identifies the file's address if both or neither is defined, a function is not `async def`, parameters are present, `menu()` returns another type, or `action()` is used for a file defining only `menu()`. Only functions defined within the file count: `from subprocess import run` does not qualify.
- Imports resolve within the tool's environment. The tool's own packages, the framework, and installed third-party packages are available without changing `sys.path`. Add dependencies required by remote files to the tool's dependencies. Remote files do not install packages themselves.
- Remote files may use the tool's existing models but **must not declare models**. Tables and migrations belong to local Apps. Remote files also must not import one another. Put code shared by several files in the tool itself or in the framework.
- Each file loads once per process under a unique name derived from its base location and path in `sys.modules`. Therefore files with the same name under different bases do not conflict, and features such as `@dataclass` that depend on module registration work normally. The framework compiles source directly without creating adjacent `__pycache__` files.
- That module name exists only in the current process. Commands or ssh calls made by remote files are unaffected because their children run other programs. However, do not pass Python functions or classes defined in a remote file to another Python process. This includes spawn-based process pools (the macOS default, with the same issue for Linux's forkserver default from Python 3.14), pickled objects loaded elsewhere, and taskiq tasks. The receiving process must reimport the module by name and cannot find it. Put such code in the tool's own package and call it from the remote file.
- Question keys are global variable names for [Terminal interaction](tui.md#preset-answers-for-unattended-use). By convention, prefix them with the filename: `cleanup.days` above is answered by `OLDMAN_ANSWER_CLEANUP_DAYS`.

## Remote scripts

- Selecting `script("hotfix.sh", "--dry-run", interpreter="bash")` runs `bash <local-file> --dry-run`. The interpreter must be explicit; the framework does not infer it from the extension.
- Scripts run in the foreground using the tool's terminal and environment. Output appears immediately, `sudo` can ask for a password, `read` can accept input, and preset-answer environment variables reach the script. They run through `run_foreground`; see [Processes and background tasks](background.md#foreground-commands), not `run_subprocess_exec`, which detaches children from the terminal.
- A nonzero exit raises `subprocess.CalledProcessError`, with the relative command path rather than the cache path. The menu displays the error and returns to the original menu. `check=False` disables this check.
- Pressing Ctrl-C during a script ends the entire tool, as it does in other menu actions.

## Caching and updates

- Local directories are not cached. Each access reads directly, so rerunning the tool after edits picks them up. Relative paths resolve against the working directory from which the tool runs; the `oldman` command runs at the project root.
- Files at URLs download on first use to `<cache_dir>/<base-location-hash>/<path>`. Later uses read that cache, which also works offline. Caches are separated by base location: changing `v1.2.0` to `v1.3.0` selects a different cache and does not use old-version files.
- Call `refresh()` to get current files, for example through "Update remote files" in the menu above. It redownloads files individually and replaces each whole file. Remote files are independent, so no batch-wide consistency is required. If a download fails, such as when an upstream deletion returns 404, it skips that file and records it in `failed`. The previous cached copy remains usable offline, and other files still refresh. Unneeded files can be deleted directly from the cache directory. Refreshed Python files reload when next selected.
- Cache directories are deployment state and must not be committed. Add them to the tool's `.gitignore`, using `/data/remote/` in this example.

## Credentials and security

- URL credentials in `user:pass@` are used only for HTTP Basic requests. Encode password characters such as `:`, `@`, and `/` with escapes such as `%3A`. Errors and logs remove credentials from addresses. Downloads retry at most once; 401, 403, and 404 are not retried.
- Remote files run as the tool's user with the same permissions as its own code. Pin a version by placing a tag or commit ID in the base URL. A branch name means the next `refresh()` retrieves the branch's latest contents.
- `proxy_url` specifies the HTTP proxy used for downloading.

<!-- source: zh/developers/remote.md @ 8c13fdcf -->
