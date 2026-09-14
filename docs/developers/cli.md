# CLI 参考

`oldman` 是 Python 包提供的命令入口。命令的前两级区分**项目操作**和**选定服务的操作**，不是把所有功能都放在一个服务里。

EPG Demo 的 [run.sh](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/run.sh) 只进入项目目录并执行该项目 `.venv/bin/oldman`，原样转发参数。下文服务操作都使用其真实 `web` 服务；换成相同环境中的 `oldman` 语义不变。安装、数据和资源准备顺序见[入门教程](../users/getting-started.md)，这些命令不会因执行 `run.sh` 而自动连跑。

## 项目级命令

| 命令 | 用途 |
| --- | --- |
| `oldman startproject <directory>` | 创建新项目，通过交互选择类型及数据库 |
| `./run.sh startapp <name>` | 创建业务 App，通过交互选择模板及显示名称 |
| `./run.sh startservice <name>` | 在现有项目增加服务，通过交互选择 simple、web、taskiq_worker 或 taskiq_scheduler |
| `./run.sh language list/show/set <language>` | 分别列出、查看或设置 CLI 显示语言；只有 set 带语言参数 |
| `./run.sh i18n extract/init/update/compile` | 管理项目翻译；init 需要 locale 参数 |
| `./run.sh db makemigrations/migrate/status/history/downgrade/retire` | 项目级数据库结构管理，实际调用时选择其中一个子命令 |

查具体帮助：

```sh
./run.sh --help
./run.sh db --help
./run.sh i18n init --help
```

`startproject` 的项目类型：

| 类型 | 生成内容 |
| --- | --- |
| `cli` | 普通 Python 脚本和依赖定义，没有服务或自动配置流程 |
| `service` | `services/service.py`，基于 SimpleApplication |
| `api` | `services/api.py`，不预装前端的 WebApplication |
| `web` | `services/web.py`，启用异步模板环境的 WebApplication |
| `dashboard` | `services/dashboard.py`、共享模板与 Vite/Tailwind 前端工程 |

数据库选项是 `none`、`sqlite`、`mysql`、`postgres`。CLI 脚本不询问数据库；Dashboard 必须选择数据库。MySQL 与 PostgreSQL 脚手架会声明相应驱动，但你仍需填写实际 URL、创建数据库和完成迁移。

这些选择由交互完成，当前不提供 `startproject --type` 或 `--db` 参数。`startapp` 同样是交互选择，不传 `--type`。

`startproject` 创建已有最小 YAML；后续使用 `settings sync`。`startservice` 只生成服务代码，后续需要 `settings init`。`startapp` 不替你修改服务的 App 清单。

## 服务级命令

EPG Demo 使用 [services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py)。以下是各入口的用法，不要求先启动再逐条 stop/restart；根据当前操作选择命令：

```sh
./run.sh web settings sync
./run.sh web settings check
./run.sh web --help
./run.sh web start
./run.sh web stop
./run.sh web restart
./run.sh web shell
```

`start` 前台运行；`stop` 读取该服务 PID 并发送停止信号；`restart` 先停止再启动。不要把 `run.sh` 不带参数理解为启动所有服务。

Demo 另有 task_worker/task_scheduler，使用相同命令层级，例如 `./run.sh task_worker start`、`./run.sh task_scheduler stop`。这两类 stop 会等待并在总截止时间自动强停经核对的进程组；不会要求用户再调用 kill。Worker 的运行保活与 Scheduler 单实例规则见[分布式任务](distributed-tasks.md)。新建入口不会顺便改 App 清单或启动另一个服务。

Web 服务还提供：

```sh
./run.sh web static collect
```

静态收集默认增量复制。`--clear` 会清理收集器跟踪的输出，应先核对输出目录与帮助，不对业务上传目录执行它。启动不自动构建或收集静态资源。

Demo 的 `WebService.get_default_commands()` 保留父类命令并增加 `dev`；`dev()` 选择 Vite 资源入口后调用 `start()`。它不负责启动 Vite，Demo 的 [scripts/dev.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/scripts/dev.py) 才是同时管理前后端开发进程的便捷脚本，接线见[资源开发流程](assets.md)。带前端的 Dashboard 脚手架也提供 dev；普通 API/Web 或 Simple 服务并不因此自动拥有它。

`--config` 的适用命令和路径语义见[配置文件选择](configuration.md#配置文件选择)，不要假定它是所有命令共享的全局选项。

### 数据 fixtures 与用户管理

运行时服务提供两个 JSON 数据工具。Demo 的 [README](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/README.md) 使用真实 Examples App 和 ExampleProject；下面将导出位置选在本机 `data/`，文件名可以自选，不是框架固定目录：

```sh
./run.sh web dumpdata examples --output data/examples-export.json
./run.sh web dumpdata examples.ExampleProject --output data/projects-export.json
./run.sh web loaddata data/examples-export.json
```

这些是导出/导入用法，不要求为阅读文档立即回灌数据库。文件已存在时先检查，避免覆盖需要保留的导出。第一次准备 Demo 数据使用 `./run.sh web loaddata demo`，来源是 [apps/examples/fixtures/demo.json](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/fixtures/demo.json)；具体主键、关联和重复导入规则见[数据教程](../users/tutorial-tasks.md#4-导入可重复的真实数据)。

`dumpdata` 的 selector 选择当前服务注册的 App 或模型；没有 `--output` 时向 stdout 输出 JSON。`loaddata` 会写数据库，并非数据库备份恢复或 schema 迁移工具。执行前核对目标数据库和数据冲突规则，不把用户的生产表当作教程试验场。

Demo 的 YAML 已安装 `oldman.auth` 与 `oldman.apps.admin`，因此在 web 服务下可以使用 Admin App 提供的命令：

```sh
./run.sh web createsuperuser
./run.sh web changepassword admin
```

先迁移数据库，再创建账户。`changepassword admin` 中的 admin 应换成已经创建的真实用户名；不存在的用户会报错，不会顺便创建。`createsuperuser` 遇到重名同样报错，不会修改旧账户。密码使用隐藏输入并再次确认，不通过命令行明文参数传入；仅生成数据库不自动创建默认管理员。这些命令只依赖 App 注册和数据库，不要求挂载或启动 `/admin` 页面。

## 自定义 App 命令

App 命令继承 `oldman.cli.Command`，在 App 的 `commands.py` 公共导出。只要 App 在本服务 `settings.apps` 中，Registry 就会发现它；不用再给服务注册一遍 decorator。

EPG Demo 的 [apps/examples/commands.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/commands.py) 提供真实的 `project-stats`：直接读取 ExampleProject，按状态统计，可按团队 ID 筛选。下面保留该类及它需要的全部导入；省略同文件另外8个示例命令的导入和末尾导出列表，不把节选当成当前完整文件：

```python
"""Read real Demo data through the installed App command lifecycle."""

from __future__ import annotations

from typing import Annotated

import typer
from sqlalchemy import func, select

from oldman.cli import Command
from oldman.db import db_manager
from oldman.i18n import gettext
from oldman.i18n import gettext_lazy as _

from .models import ExampleProject, ExampleTeam


class ProjectStats(Command):
    """Count projects without changing fixtures, records or cache snapshots."""

    name = "project-stats"
    help = _("Count example projects, optionally filtered by team.")

    async def handle(
        self,
        team_id: Annotated[int | None, typer.Option(min=1)] = None,
    ) -> None:
        """Read a fresh grouped count; CLI validation restricts the optional ID."""
        try:
            async with db_manager.get_read_session() as session:
                statement = (
                    select(ExampleProject.status, func.count())
                    .group_by(ExampleProject.status)
                    .order_by(ExampleProject.status)
                )
                if team_id is not None:
                    if await session.get(ExampleTeam, team_id) is None:
                        raise ValueError(gettext("Team %(team_id)s does not exist.", team_id=team_id))
                    statement = statement.where(ExampleProject.team_id == team_id)
                counts = {status: count for status, count in await session.execute(statement)}
            # Plain output keeps database values from being interpreted as Rich markup.
            typer.echo(gettext("Total projects: %(count)s", count=sum(counts.values())))
            for status, count in counts.items():
                typer.echo(f"{status}: {count}")
        finally:
            # One-shot commands do not run the Web service's shutdown listeners.
            await db_manager.close()
```

`apps.examples` 已在服务 YAML 的 `apps` 中，`ExamplesAppConfig` 继承的 `commands_module = "commands"` 让 Registry 发现这个导出类，不需要修改 AppConfig 或 WebService。帮助按 App 的显示名称分组；调用方式如下：

```sh
./run.sh web --help
./run.sh web project-stats --help
./run.sh web project-stats
./run.sh web project-stats --team-id 1
```

先准备配置及数据库，步骤和结果对照见[命令示例](../users/demo-examples.md#自定义-app-命令)。这里的 `web` 用来选择服务配置，并不启动 Web 端口。正常 Demo 配置启用 NATS/Taskiq，因此现有命令生命周期会连接配置中的基础设施；不需要启动接收服务、Worker 或 Scheduler。不试用通信/任务时可关闭 `nats_bus.enabled` 与 `taskiq.enabled`，命令本身不使用它们或 Redis 缓存。

`--team-id` 的类型及最小值由 Typer 检查，错误退出码为 2。不存在的团队抛出 ValueError，CLI 输出说明并退出 1；存在但没有项目的团队正常输出 0，退出 0。缺表、数据库不可访问等异常也退出 1，不自动建表或导入 fixture。状态按数据库原值排序/显示，输出只列实际存在的分组；每次重新查询，不读取缓存页的快照。

读 Session 的上下文管理器负责关闭 Session；`finally` 另外释放本次命令使用的数据库连接池，包括查询失败时。一次性命令不执行 Web 停止监听器，不能指望 `WebService.before_server_stop()` 代为清理。这是命令的资源收尾，不是供请求内并发调用的统计助手。这里用 `typer.echo()` 打印普通文本后返回 None，避免数据库字符串被终端 Rich 标记解释；需要交互输入时仍复用 Typer prompt/confirm，实际例子可看内置 [Admin 命令](../../oldman/apps/admin/commands.py)。

`name` 匹配 `[a-z][a-z0-9-]*`；命令名用连字符，Python 参数名用下划线。`help` 必须是非空字符串或 `LazyTranslation`。类必须可无参数构造，`handle()` 必须是 `async def`，可以返回供 CLI 打印的结果，也可以自行输出并返回 None。

参数沿用 Typer：无默认值通常是位置参数，有默认值通常是选项；可以用 `Annotated[..., typer.Option(...)]` 或 `typer.Argument(...)` 明确约束。交互复用 `typer.prompt()`、`typer.confirm()`，不另写输入解析系统。

同一服务的 App 命令名必须唯一，不能与服务已有命令、配置/静态/Shell 入口或 fixtures 命令冲突。App 显示名用于帮助里的分组，不成为额外一级命令。例如执行的是 `web changepassword`，不是 `web admin changepassword`。

Registry枚举命令模块中不以下划线开头的公共变量，选择非抽象的Command子类，包括从其他模块导入的类；它不读取`__all__`作为注册清单。Demo的BackgroundStats等命令正是通过commands.py中的普通import接入。只改`__all__`不会注册一个尚未导入的类，也不会隐藏已经以公共名称导入的类。

如果将 `commands_module` 设为一个包，在包的 `__init__.py` 显式导入需要的 Command 类。Registry 不递归扫描所有 Python 文件；同一类也不能用多个公共变量名重复导出。仅供内部复用的具体Command应使用私有导入名，抽象公共基类则不会被实例化。

### 命令生命周期

App 命令的模型已加载，流程为：

```text
构造选定服务的 Application
→ 配置命令日志
→ 在同一个事件循环初始化 Storage
→ 打开启用的 Core NATS 发送连接
→ 打开启用的 Taskiq 发布连接
→ await application.before_command(name, ...)
→ await command.handle(...)
→ await application.after_command(name, ...)
→ Taskiq shutdown（原生钩子仍可调用 Core）
→ 关闭 Core NATS
→ 关闭该次命令的日志资源
```

它不运行服务的 `init()`、`prepare()`、`main()`、`prepare_server()` 或 Web 启停监听器，因此不会仅仅为了执行命令就绑定 HTTP 端口。需要服务级命令初始化时，覆盖 `before_command()`；对应资源在 `after_command()` 关闭。普通业务也可以在 `handle()` 内用上下文管理器或 `finally` 关闭自己使用的资源。

Core 只发送/RPC，不因 consume=true 加载 App events 或启动 subscriber；普通命令也不自动加载所有 tasks。功能关闭不建对应连接。初始化、handle 或 after_command 抛错仍进入通信 finally，保留原始错误、另外记录清理错误；自己的 DB/HTTP 等资源仍按原归属关闭。命令中直接导入 bus 使用，不再手工 async with。Settings/帮助、数据库命令和 bootstrap/Shell 不执行这条异步命令运行链路；Shell 显式通信见 [provider 参考](providers.md#shellide-与独立连接)。

不要在 Command 构造函数中连接数据库、读取请求对象或启动任务。命令错误由 CLI 输出并以失败状态退出；不要吞掉异常后返回成功文本。

两个可选类属性：

- `check_pid = True`：限制同一服务的同名命令并发。默认 false；不是分布式锁，也不保护不同机器。
- `raw_stdout = True`：给机器消费原始 stdout 时，把命令日志送往 stderr。默认 false；命令自己也应避免在数据流中混入说明文字。

## 数据库命令的范围

迁移命令根据项目的真实服务文件收集默认 YAML，合并 App 列表，要求所有配置了数据库的服务具有**字符串完全相同**的 URL。安装 Auth 的服务也必须选定一致的具体 User 模型。

迁移过程不会发布某个服务的 App Settings，不启动服务，也不加载 views 或 App 命令。因此模型声明不能依赖某个服务的 `app.settings`，让同一张表在不同进程变成不同结构。

每个 App 保存标准 Alembic revision，框架统一提供 Alembic 环境和目录接线。生成时选择目标 App；执行时使用迁移依赖顺序，而不是按菜单或配置顺序改表。

涉及首次使用、状态恢复、改名或删除等决定时需要交互终端；不能指望 `echo yes | ...` 绕过判断。`makemigrations` 和 `migrate` 分开运行，生成后可先检查文件。

`downgrade` 会执行逆向迁移，可能删除数据；`retire` 用于退出某个 App 的结构管理而保留物理表，不等同于卸载 Python 包。调用这两项前必须明确目标，不作为普通上手步骤。

## CLI 语言

```sh
./run.sh language list
./run.sh language show
./run.sh language set zh-Hans
```

内置 CLI 支持 `en`、`zh-Hans`、`zh-Hant`。语言偏好存于用户 XDG 配置目录中的 `oldman/cli.json`，不修改服务 YAML。`OLDMAN_CLI_LANGUAGE` 可以仅覆盖当前命令语言，这与业务 Settings 的 YAML-only 规则不同。

App 命令的说明使用 `gettext_lazy()`，实际运行时再翻译。Python、Jinja、CLI 共用 `messages` 翻译目录；不需要为 CLI 增设独立 domain。

没有有效译文的词条会回退原文。新增或修改命令文案时，应同步提取、补齐简繁译文并编译，步骤见 [CLI 翻译维护](../../oldman/cli/locales/README.md)。
