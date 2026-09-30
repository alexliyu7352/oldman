# 远程文件（remote）

`oldman.cli.remote` 让运维工具的菜单直接使用放在别处的文件：一个远程文件解决一个任务或一个问题，工具发布之后也能增加、修改，不用重新部署工具本身。文件放在一个**基础地址**下：GitHub 仓库的 raw 地址、自己的文件服务器，开发时是本地目录。

远程文件有两种：

- **Python 文件**，在工具自己的命令里加载运行：数据库、Redis、settings 都已按工具的配置初始化，所以清理数据、改配置这类事直接写。它导出 `run()`（一个任务）或 `menu()`（自带的子菜单）。
- **脚本**（shell、Python 等），作为子进程运行，与工具只通过参数和环境变量交流。

它们都挂在 [tui 菜单](tui.md#菜单)上，和本地动作混排。

## 工具这边

工具的菜单是它自己的 App 命令。基础地址放在 App 设置里：上线用带标签的 GitHub raw 地址，开发机改成本地目录。

```python
# apps/ops/remote.py
from apps.ops.apps import app
from oldman.cli.remote import RemoteFiles
from oldman.conf import settings

remote = RemoteFiles(app.settings.remote_base, cache_dir=settings.core.data_dir / "remote")
```

这个模块在导入时就读设置，只能被命令、菜单和远程文件导入；`apps.py`、`models.py` 以及它们导入的模块都不能导入它。`db` 命令只加载 App 和模型、不加载设置，被牵连到就会报 `Oldman settings are not configured`，而服务命令照常能跑，平时不容易发现。

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
    # 开发时：remote_base: ../ops-files/remote
```

`remote_base` 是这个工具 App 自己的设置字段（见 [App Settings](configuration.md#app-settings)），框架不规定它叫什么。`apps/ops/models.py` 里的 `AccessLog` 同样是工具自己的模型。

| 成员 | 行为 |
| --- | --- |
| `RemoteFiles(base, *, cache_dir, proxy_url=None)` | `base` 是 `http://` / `https://` 地址或本地目录；地址可以带 `user:pass@`，不能带查询串和 `#`。`cache_dir` 必须显式给 |
| `menu(path)` | 给 `Item(load=...)`：选中时取文件、加载，调用它的 `menu()` |
| `action(path)` | 给 `Item(action=...)`：选中时取文件、加载，`await` 它的 `run()` |
| `script(path, *args, interpreter, check=True)` | 给 `Item(action=...)`：选中时取文件，运行 `interpreter 文件 *args` |
| `await fetch(path)` | 返回文件在本地的路径；远程文件要读的数据文件（配置模板等）也用它取 |
| `await refresh()` | 把这个基础地址已缓存的文件全部重新下载，返回 `Refreshed`：`updated` 是重新下载了的路径，`failed` 是没能下载的路径与原因 |

`path` 是基础地址下某个文件的相对路径，例如 `nginx.py`、`checks/ssh.py`；以 `/` 开头、含 `..`，或者只是 `.` 的，在构造菜单项时就抛 `ValueError`。

## 远程 Python 文件

```python
# cleanup.py：一个文件一个任务
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
# nginx.py：自带子菜单
from oldman import ops
from oldman.cli import tui


async def reload() -> None:
    await ops.systemd.reload("nginx", command=("sudo", "systemctl"))
    tui.success("nginx reloaded")


async def menu() -> tui.Menu:
    return tui.Menu("Nginx", [tui.Item("Reload", action=reload)])
```

- 文件在自己里面定义 `async def run()` 或 `async def menu()` 之一，都不带参数；`menu()` 返回 `tui.Menu`，可以按当时的情况生成（例如列出现有站点）。两个都定义、都没有、不是 `async def`、带参数、`menu()` 返回别的东西，或者 `action()` 用在只定义了 `menu()` 的文件上，选中时都报错并写出文件地址。只算这个文件里写的函数：`from subprocess import run` 不算。
- 导入按工具的环境解析：工具自己的包、框架、工具环境里装了的第三方包都能导入，不需要改 `sys.path`。远程文件用得到的第三方包要装进工具的依赖里，远程文件本身不安装任何东西。
- 可以用工具已有的模型，**不能声明模型**：建表和迁移属于本地 App。远程文件之间也不互相导入；几个文件共用的代码放进工具本身或框架。
- 每个文件在一个进程里加载一次，以基础地址和路径算出的唯一名字登记在 `sys.modules`，所以两个基础地址下的同名文件互不影响，`@dataclass` 等依赖模块登记的写法照常可用。框架直接编译源文件，不在旁边写 `__pycache__`。
- 这个名字只在当前进程里有效。远程文件里执行命令、调用 ssh 不受影响（子进程运行的是别的程序）；但不能把远程文件里定义的 Python 函数或类交给另一个 Python 进程——spawn 方式的进程池（macOS 默认，Linux 从 Python 3.14 起默认的 forkserver 同理）、pickle 后在别处读取、taskiq 任务——对方要按模块名重新导入，找不到它。需要这样做的代码放进工具自己的包，远程文件只调用它。
- 问题的 key 是全局的[预置答案](tui.md#预置答案无人值守)变量名，约定以文件名开头：上例的 `cleanup.days` 由 `OLDMAN_ANSWER_CLEANUP_DAYS` 回答。

## 远程脚本

- `script("hotfix.sh", "--dry-run", interpreter="bash")` 选中时运行 `bash <本地文件> --dry-run`。解释器必须给出，框架不按扩展名猜。
- 脚本在前台运行，直接用工具的终端和环境变量：输出实时显示，`sudo` 可以问密码，`read` 可以读输入，预置答案的环境变量也传得到。脚本经 [`run_foreground`](background.md#前台命令) 运行；不用 `run_subprocess_exec`，因为它会让子进程脱离终端。
- 退出码非零时抛 `subprocess.CalledProcessError`（命令里是相对路径，不是缓存路径），菜单显示错误后回到原菜单；`check=False` 时不检查。
- 在脚本运行时按 Ctrl-C，和在其他菜单动作里一样，会结束整个工具。

## 缓存与更新

- 本地目录不缓存，每次直接读，改完文件重新运行工具就能看到。相对路径按运行工具时的当前目录解析（`oldman` 命令在项目根运行）。
- 地址上的文件第一次用到时下载到 `<cache_dir>/<基础地址的哈希>/<path>`，之后都用这份缓存，离线也能用。缓存按基础地址区分：把地址里的 `v1.2.0` 换成 `v1.3.0` 就是另一份缓存，不会用到旧版本的文件。
- 要取最新的文件，调用 `refresh()`（例如上面菜单里的「Update remote files」）。它逐个文件重新下载，每个文件整体替换；远程文件之间互不依赖，所以不需要整批一致。某个文件下载失败（例如上游删掉了它，得到 404）时跳过它、记进 `failed`，缓存里的旧文件保留，工具离线照样能用，其余文件照常刷新；不再需要的文件可以直接从缓存目录里删掉。刷新过的 Python 文件在下次被选中时重新加载。
- 缓存目录是部署状态，不要提交：把它加进工具的 `.gitignore`（上例是 `/data/remote/`）。

## 凭据与安全

- 地址里的 `user:pass@` 只用于请求（HTTP Basic）；密码里的 `:`、`@`、`/` 等要写成 `%3A` 这样的编码。报错信息和日志里的地址都去掉了凭据。下载失败最多重试一次，401、403、404 不重试。
- 远程文件以运行工具的用户执行，和工具自己的代码权限相同。锁定版本的办法是把标签或提交号写进基础地址；写分支名时，下一次 `refresh()` 取到的就是分支的最新内容。
- `proxy_url` 是下载时使用的 HTTP 代理。
