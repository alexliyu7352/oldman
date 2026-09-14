# 任务指南：创建服务与接入现有 App

先确定用户需要新项目、新服务，还是只在现有服务增加一个路由。不要为每项管理操作创建长期服务，也不要为运行文档另造一个任务清单项目。

## 现有 Demo 从哪里看

EPG Demo 有 services/web.py 的 WebService，services/task_worker.py、services/task_scheduler.py 两个专用任务服务，以及 services/nats_a.py、services/nats_b.py 两个 SimpleApplication 接收服务。Web 运行见[用户教程](../users/getting-started.md)，任务见[Taskiq 指南](distributed-tasks.md)，NATS 见[通信教程](../users/service-communication.md)。各入口独立启动，不改变 run.sh 的语义。

从它学习以下已有接线：

| 位置 | 应了解的内容 |
| --- | --- |
| config/schemas.py、config/settings.py | 项目唯一根 Settings 类型，业务导入当前进程的配置实例 |
| data/web_settings.example.yaml | web 服务的 Apps、数据库、Redis、模板、静态和安全配置 |
| apps/examples/apps.py | AppConfig 的 label、display_name、icon 与唯一 app 实例 |
| apps/examples/models.py | Registry 加载的真实数据库模型 |
| apps/examples/commands.py | project-stats 及本地协程/进程/缓存等 Command 的公开入口；实现位于对应普通模块 |
| apps/examples/views/__init__.py | 在共享定义就位后导入具体视图模块 |
| apps/examples/views/tables.py | get_app、路由注册、权限、查询和响应 |
| services/web.py | 框架 Web 初始化后接入 CSRF、模板、bundle；停止时关闭数据库 |

这些代码不能原封不动当成“不需要 Session/Redis/前端”的纯 API 模板。增加纯 API 服务时使用框架 API 脚手架，不把 Demo 的 UI 初始化拆成另一套全局单例。

## 新项目的命令流程

这部分是框架脚手架操作，不是声称 EPG Demo 中已经存在 api 服务。先安装 uv，再用它安装与当前文档对应的 `oldman` 命令行；`--python 3.13` 固定到框架支持的版本，因为 `uv tool install` 不检查包声明的 `requires-python`：

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install --python 3.13 oldman
```

源码开发可用 `uv tool install --python 3.13 --editable /框架源码目录` 代替发行包。项目仍需自己的依赖环境，下面的 `uv sync` 由同一个 uv 提供。

在准备存放项目的父目录执行：

```sh
oldman startproject my_site
```

交互选择 api、none 可生成不配置数据库的 API 项目。进入生成目录后安装依赖，运行：

```sh
cd my_site
uv sync
./run.sh api settings sync
./run.sh api settings check
./run.sh api start
```

这时只有服务入口；没有业务根路由时 / 返回 404，不宣称它已经能读写 EPG 数据。源码安装用户应让新项目自己的环境也使用对应源码版本，不能全局 editable、项目却从索引安装不一致版本。

### 新项目使用本地 Python 源码

本节是普通生成项目的安装参考；EPG/Admin Demo 已有 scripts/bootstrap.py，直接运行其脚本，不再重复本节。没有可用发行包时，在新项目根用下面两步替代上面的 uv sync（路径替换为实际框架源码目录）：

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r pyproject.toml --editable /实际路径/oldman_framwork
```

已有 .venv 时跳过创建；先确认它属于本项目，不能覆盖别人的环境。`-r pyproject.toml` 同时安装项目声明的数据库驱动等依赖，显式 editable 指定本次 Oldman 来源；源码版本仍须满足项目依赖约束。后续使用 ./run.sh 或 .venv/bin/python，不再运行会按发行包重新同步的 uv sync/uv run，除非已经自行配置相应 uv source。这不修改公开依赖清单，也不替项目安装前端；需要浏览器包时按[资源参考](../developers/assets.md)接线。

新 App 使用 startapp 的交互填写名字和类型，将生成的包路径加入当前服务 apps 列表。参考 EPG 的 apps/examples/apps.py 与具体视图模块连接方式，按用户业务实现路由。不要复制一个片段后漏掉包文件、App 注册或权限，也不要把文档中的名字当成必须的目录名称。

## 何时新增服务

| 需求 | 选择 |
| --- | --- |
| 现有网站增加 API | 通常在当前已安装 App 增加视图，不新开端口 |
| 独立监听地址或不同配置、进程边界 | 新建 WebApplication 服务 |
| 长期工作，不提供 HTTP | SimpleApplication |
| 异步函数持久排队、多个进程分担 | TaskiqWorkerApplication |
| 发布到期计划和延迟重试 | TaskiqSchedulerApplication；同 namespace 一个 |
| 手工导入数据、创建管理员等一次性操作 | 已安装 App 的 Command |

服务名取自 services/<name>.py，配置默认 data/<name>_settings.yaml，不定义第二个 SERVICE_ID。多个服务运行于不同进程，共用项目唯一根 Settings 类型，分别选择 YAML。数据库迁移仍是项目级命令。

已有项目需要新服务时用 startservice，根据实际用途选模板，再对不存在的配置执行 settings init。已有配置使用 sync/check，不靠启动时改写配置。App 清单由各服务明确管理；把模型文件放进目录不等于安装。

## 后台示例的当前边界

EPG Demo 的 Taskiq 场景已实际运行，见 tasks.py、views/tasks.py 和两个任务服务；SimpleApplication 的实际例子是两个 NATS 接收服务。进程内周期采样则由 `background-stats` Command 展示：sample_project_counts 读取两次真实 SQL 结果，随后取消并清理。不是每个浏览器或每个 Sanic worker 启动一个采集器。

有限运行的 `python-process`、`subprocess-demo`、`worker-demo` 各展示实际成功、失败和退出；命令、源码与可观察结果见[后台教程](../users/background-work.md)。选择本地接口时从这些已完成的实例取例，不需要重新建立 collector/reporter 服务。只有用户的业务确实需要常驻采集时，再按实际采样来源、频率、资源和退出要求扩展 SimpleApplication；其生命周期与进程 API 见[应用参考](../developers/applications.md#simpleapplication)、[后台参考](../developers/background.md)。

## 自定义一次性命令

直接从 Demo 的 `apps/examples/commands.py` 中的 `ProjectStats` 取例，运行 `./run.sh web project-stats` 或加 `--team-id 1`。具体前置和人工对照步骤见[命令示例](../users/demo-examples.md#自定义-app-命令)，完整实现和接口见[CLI 参考](../developers/cli.md#自定义-app-命令)。不要为它新建服务、全局注册器或数据库表。

- 注册来源只有服务 `apps` 中的 `apps.examples`。AppConfig 默认读取 commands.py，其 `__all__` 导出 ProjectStats；帮助使用 App 显示名，调用不增加 `examples` 一级。
- 入口是 `async handle()`，用 `Annotated[int | None, typer.Option(min=1)]` 验证可选团队参数；不用自己解析 argv。未注册 App 的服务不能运行这个命令。
- 读取已有 ExampleTeam/ExampleProject；空结果成功，不存在团队和数据库错误失败。默认统计与按团队筛选都只读，不使用 cache_example 的 Redis 快照。不要捕获 SQL 异常后返回“统计成功”。
- CLI 选择 web 配置，但不启动 HTTP、Web 监听器或后台接收服务。启用的 Core NATS/Taskiq 仍由现有异步命令生命周期初始化；需要它们可连接，或按 Demo 既有规则明确关闭两项功能，不加命令私有绕过。
- Session 在上下文退出时关闭，命令自己的 finally 释放 db_manager；不能依靠 Web 停止钩子。不要把这个会关闭连接池的命令 handle 当作网页请求内的通用查询函数调用。
- 修改命令文案后沿用 messages 的 extract/update/compile，保留简繁翻译。专项检查使用 tests/test_examples_commands.py 的独立项目/进程和 SQLite，不修改用户运行配置、数据或服务。

内置 `web loaddata demo`、`web dumpdata examples`、`web createsuperuser` 仍是实际消费入口，不复制进业务 commands.py。

## IDE 与检查

使用 Demo 的 IDE Shell 时，工作目录和解释器分别指向 Demo 根和其 .venv。先调用公共 bootstrap_service("web") 再导入应用模型，或直接运行 `./run.sh web shell`。细节见[Shell 参考](../developers/applications.md#python-shell-与-ide)。同一进程不能接着选择另一套服务配置。

交付检查必须针对实际任务：

1. 明确注册、配置、启动入口，不把创建一个子类当成接线完成。
2. API 验证真实成功请求和一条失败路径；写入失败不新增记录。
3. 模型结构通过 db makemigrations/migrate 管理，不在启动中 create_all。
4. 一次性命令不启动 HTTP；后台服务不加载 Web 视图或偷偷新增服务。
5. 退出时释放本任务资源，不停止其他用户的服务。
6. 示例和文档使用实际文件、符号与命令；尚缺的 Demo 场景先记录，再单独补齐。

碰到 AppNotInstalledError 或配置未就绪，按[加载顺序](../developers/applications.md#实际加载顺序)修正，不增加默认配置回退、兼容 alias 或生产 reset。
