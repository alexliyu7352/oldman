# Demo 的真实数据、迁移与查询

先按[运行教程](getting-started.md)准备 EPG Dashboard。本文始终使用这个 Demo 的 `ExampleTeam`、`ExampleProject` 等模型，不另外创建一个同名近似模型。

数据源是 [apps/examples/models.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/models.py)，初始数据是 [apps/examples/fixtures/demo.json](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/fixtures/demo.json)。浏览器操作与下面的源码属于同一套实现。

## 1. App、模型和表分别叫什么

Demo 的 [apps/examples/apps.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/apps.py) 完整内容如下：

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

服务 YAML 的 `apps` 列表包含 `apps.examples`。框架由这个包路径取得上述 `app`，再加载模型和 Web 视图；元数据模块不自行导入模型或启动服务。

这些名字不要混用：

| 名字 | 含义 |
| --- | --- |
| apps.examples | 服务安装的 Python App 包 |
| examples | App 的稳定 label，用于 fixture 等命令 |
| ExampleProject | 模型类名 |
| example_project | 模型的数据库表名 |
| examples.ExampleProject | fixture 中的模型标识，不是 Python 导入路径 |

`display_name` 和 `icon` 用于界面展示，不改变表名和模型标识。模型自身的 `Meta.verbose_name`、`verbose_name_plural` 则描述模型的展示名称。

## 2. 看懂关系和约束

不要把本段另存为一份简化模型；完整声明位于上面的 models.py，包含索引、约束、relationship 和展示元数据。

- `ExampleTeam` 是团队，表名 `example_team`。
- `ExampleProject` 是项目，`team_id` 是指向 `example_team.id` 的真实外键。显示团队名称时使用 `team` relationship。
- 项目的 `slug` 唯一，`budget` 不能小于零，`progress` 限定为 0 到 100。浏览器或 Form 校验不能代替这些数据库约束。
- `ExampleTask` 通过 `project_id` 关联项目，同时用于拖拽审核示例。它不是另一个教程里只有标题和完成状态的任务模型。
- `ExampleAsset` 通过 `file_column()` 声明两个文件字段；数据库仍保存逻辑文件名，上传见[数据与文件](data-and-files.md)。
- `ExampleServer` 和 `ExampleServerMetric` 分别保存服务器清单和监控样本，用于实时表格与图表。

普通 SQLAlchemy 列仍使用 `Mapped`、`mapped_column`、`ForeignKey` 等声明。所有模型使用框架共享 metadata，不能为同一 App 另外创建 Base 来绕过注册。

## 3. 第一次运行执行已有迁移

Demo 已携带标准 Alembic revision，包括 [examples 初始迁移](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/migrations/a839bf3055f2_create_example_models.py)。使用它时，在 Demo 根目录运行：

```sh
./run.sh db migrate
./run.sh db status
./run.sh db history
```

根据提示区分首次使用与状态丢失，不用删除数据库来绕过问题。正常情况下，migrate 完成后 status 不再列出待执行迁移；history 展示源码中的迁移历史。

只有你**实际修改了模型结构**，才运行：

```sh
./run.sh db makemigrations
```

按交互提示选择本次变更的 App、确认差异和说明，检查生成 revision 的 upgrade/downgrade，再单独执行 `db migrate`。部署使用提交的迁移文件，不在服务器上重新生成。

`db` 是项目级命令，读取项目真实服务的数据库与 App 定义；不是 `web db`。不要从其他迁移工具的示例照搬 `--app`、`--empty` 等参数。详细交互、表归属、改名和恢复规则见[迁移参考](../developers/migrations.md)。

项目 `pyproject.toml` 中已有稳定的 `tool.oldman.project_id`。不要靠更换它解决迁移错误，也不要用这份 Demo 去接管其他系统的生产数据库。

## 4. 导入可重复的真实数据

```sh
./run.sh web loaddata demo
```

这是按名字查找 `apps/examples/fixtures/demo.json`，不是执行服务器启动钩子。该文件同时包含多个已安装 App 的数据，因此 EPG 业务页面和功能示例都能读取自己的记录。

文件开头的第一条记录原文为：

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

完整 fixture 是记录列表，上面只是其中一个对象，不是可直接代替整个文件的内容。Logo SVG 位于 App 静态目录，导入数据库不会代替 `web static collect`。

loaddata 按模型和主键新增或更新：

- 重复导入不会把相同主键变成另一条记录。
- 文件里明确填写的字段会更新，可能覆盖你对预设行的修改。
- 不在 fixture 中的其他记录不会因此删除。
- 它不迁移表结构，不打包上传文件，也不是数据库备份工具。

导出使用 Demo README 已有命令：

```sh
./run.sh web dumpdata examples --output /tmp/examples.json
./run.sh web dumpdata examples.ExampleProject --output /tmp/projects.json
```

先确认输出路径未保存你要保留的文件，也可以换成自己的明确路径。第一条选择整个示例 App；第二条只选择项目模型，**不会自动把关联团队也导出**。把单模型文件导入另一数据库前，必须先准备其外键依赖；不能关闭外键来让它通过。临时导出用完后由创建者清理。

## 5. 静态表格也读取数据库

`/examples/tables/static` 的“静态”指首次 HTML 渲染，不代表写死假数据。[apps/examples/services.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/services.py) 中被视图调用的函数原文：

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

这是已有模块中的函数节选，不是独立脚本。该文件已从 `oldman.db` 导入 `db_manager`，从 SQLAlchemy 导入 `select`、`selectinload`，并从当前 App 导入模型。直接运行完整 Demo，不要把这段粘到 App 元数据模块。

它完成四件事：

1. 使用当前服务的数据库配置创建只读 Session。
2. 按项目 ID 排序，并限制返回数量。
3. 提前加载模板需要的团队关系，避免离开 Session 后再隐式查询。
4. 离开上下文释放 Session，再由视图渲染页面。

动态 HTML/JSON 表格使用 `ExampleProjectTable.get_queryset()`，分页、搜索和排序由 Table 处理。具体接线见[下一章](tutorial-dashboard.md)。

## 6. 写入、提交与检查

项目创建和修改在 [apps/examples/views/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tables.py)：

- `db_manager.get_session()` 管理一次写事务。
- `ExampleProjectForm.from_request(..., session=session)` 绑定请求并用同一个 Session 校验团队、重复 slug 等。
- 校验通过后 `form.save(commit=True, session=session)` 写入实例并 flush；真正提交发生在上下文正常退出时。
- 成功的 JSON 动作在退出上下文后返回。数据库失败不能冒充“保存成功”。

不要将 AsyncSession 放成供多个请求共用的全局变量，也不要在每次请求结束时关闭整个数据库引擎。

验证时，使用下一章的 Modal 新建一条自己的测试项目，分别从静态、HTML、JSON 表格查看，并通过相同查询条件找到它。静态页只显示前 12 条，未出现在静态页不等于保存失败；动态表格可以搜索。刷新或重启后数据应仍在。重复 slug 或倒置日期应失败，不应新增记录。

## 关闭服务持有的数据库连接

[services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py) 的实际关闭钩子如下，保留在 `WebService` 类内：

```python
    async def before_server_stop(self, app: WebApp) -> None:
        """服务停止前关闭数据库连接池。"""
        await super().before_server_stop(app)
        await db_manager.close()
```

Demo 退出时关闭自己进程中的连接池；不是由单个列表视图关闭。其他生命周期、命令和 IDE 初始化见[Application 参考](../developers/applications.md)，fixture 的类型校验与事务失败规则见[Fixture 参考](../developers/fixtures.md)。

下一章直接打开 Demo 的两个动态表格页面，沿着同一模型查看 Form、Modal、响应动作和 Page 如何连接。
