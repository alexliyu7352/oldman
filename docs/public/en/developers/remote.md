# Remote files

`oldman.cli.remote` lets operations-tool menus use files hosted elsewhere. Each remote file handles one task/problem and can be added or changed after tool release without redeploying the tool. Files live under a **base location**: a GitHub raw URL, your file server, or a local development directory.

There are two kinds:

- **Python files** load/run inside the tool's own command. Database, Redis, and settings already follow tool initialization, so data cleanup/configuration changes can use them directly. Files export `run()` for one task or `menu()` for a submenu.
- **Scripts** (shell, Python, etc.) run as child processes and communicate only through arguments/environment variables.

Both appear alongside local actions in [Terminal interaction](tui.md#menus).

## Tool-side setup

The tool's menu is its own App command. Put the base location in App settings: tagged GitHub raw URLs in production, local directories during development.

```python
# apps/ops/remote.py
from apps.ops.apps import app
from oldman.cli.remote import RemoteFiles
from oldman.conf import settings

remote = RemoteFiles(app.settings.remote_base, cache_dir=settings.core.data_dir / "remote")
```

This module reads settings at import time, so only commands, menus, and remote files may import it. apps.py, models.py, and their imports must not. db commands load Apps/models without settings and would raise `Oldman settings are not configured`, while ordinary service commands still work, making the mistake easy to miss.

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

`remote_base` is this tool App's own setting (see [Configuration reference](configuration.md#app-settings)); the framework does not prescribe its name. `AccessLog` in `apps/ops/models.py` likewise belongs to the tool.

| Member | Behavior |
| --- | --- |
| `RemoteFiles(base, *, cache_dir, proxy_url=None)` | base is an http:// or https:// URL or local directory. URLs may contain user:pass@ but no query or fragment. cache_dir is explicit |
| `menu(path)` | For Item(load=...): selecting fetches/loads the file and calls menu() |
| `action(path)` | For Item(action=...): selecting fetches/loads the file and awaits run() |
| `script(path, *args, interpreter, check=True)` | For Item(action=...): selecting fetches the file and runs interpreter file *args |
| `await fetch(path)` | Returns the local file path; also fetches data files needed by remote files, such as configuration templates |
| `await refresh()` | Redownloads cached files under this base, returning Refreshed: updated contains refreshed paths; failed contains paths/reasons that failed |

`path` is a file path relative to the base, such as `nginx.py` or `checks/ssh.py`. Leading /, any .., or a lone . raises ValueError when constructing menu items.

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

- Define either asynchronous run() or menu() inside the file, without arguments. menu() returns tui.Menu and may build it from current state, such as existing sites. Defining both/neither, non-async functions, arguments, invalid menu returns, or action() on menu-only files fails upon selection and identifies the file URL. Only functions defined in this file count; `from subprocess import run` does not.
- Imports resolve in the tool's environment: its packages, framework, and installed third-party dependencies are available without sys.path changes. Install required third-party packages as tool dependencies; remote files install nothing themselves.
- Existing tool models are usable, but **model declarations are forbidden**: tables/migrations belong to local Apps. Remote files do not import each other. Put shared code in the tool or framework.
- Each file loads once per process under a unique sys.modules name derived from base/path. Same-named files under different bases stay separate, and features requiring module registration such as @dataclass work normally. The framework compiles source directly without adjacent __pycache__ output.
- That module name exists only in this process. Commands/ssh invoked by remote files still work because they run other programs. However, do not pass Python functions/classes defined remotely to another Python process: spawn pools (macOS default; likewise Linux's forkserver default from Python 3.14), pickled data read elsewhere, or taskiq tasks. Those processes reimport by module name and cannot find it. Put such code in the tool package and call it from remote files.
- Question keys are global [Terminal interaction](tui.md#preset-answers-for-unattended-use) variable names, conventionally prefixed with the filename. Here `cleanup.days` is answered by `OLDMAN_ANSWER_CLEANUP_DAYS`.

## Remote scripts

- Selecting `script("hotfix.sh", "--dry-run", interpreter="bash")` runs `bash <local-file> --dry-run`. The interpreter is required and is not inferred from extensions.
- Scripts run in the foreground with the tool's terminal/environment: live output, sudo password prompts, read input, and preset-answer environment variables all work. They use [Processes and background tasks](background.md#foreground-commands), rather than run_subprocess_exec, which detaches children from the terminal.
- Nonzero exit raises subprocess.CalledProcessError, displaying the relative command path rather than the cache path. The menu shows the error and returns to the same menu. check=False disables checking.
- Ctrl-C during a script ends the entire tool, as in other menu actions.

## Caching and updates

- Local directories are not cached. Every access reads directly; restart the tool after editing. Relative directories resolve from the tool's working directory (oldman runs at the project root).
- URL files download on first use to `<cache_dir>/<base-location-hash>/<path>`, then reuse that cache, including offline. Bases have separate caches: changing v1.2.0 to v1.3.0 selects another cache without old-version files.
- Call refresh() for current files, such as the menu's "Update remote files" above. It redownloads files individually with whole-file replacement. Remote files are independent and need no batch-wide consistency. A failed download, such as upstream deletion/404, is skipped and recorded in failed; its old cache remains usable offline, and other files still refresh. Delete unneeded cached files directly. Refreshed Python files reload on next selection.
- Cache directories are deployment state, not source. Add them to tool .gitignore, `/data/remote/` above.

## Credentials and security

- URL user:pass@ is used only for HTTP Basic requests. Encode password punctuation such as :, @, and / as percent escapes like %3A. Errors/logs strip credentials. Downloads retry at most once, excluding 401/403/404.
- Remote files run as the tool's user with the same permissions as its own code. Pin versions through tags/commit IDs in base URLs. A branch URL fetches its latest contents on the next refresh().
- proxy_url selects an HTTP proxy for downloads.

<!-- source: zh/developers/remote.md @ 8c13fdcf -->
