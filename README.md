# Oldman

Oldman 是后端渲染优先的 Python 应用框架，适合构建 Dashboard、管理后台、Web/API 服务和后台任务服务。

Python 负责配置、应用生命周期、权限、数据和 HTML；浏览器端负责局部更新、表单提交、表格、弹窗和实时交互。你可以只写后端，也可以为需要交互的页面增加 TypeScript。

两个包各有职责：

| 包 | 用途 |
| --- | --- |
| `oldman`（Python） | Application、App 注册、配置、数据库迁移、Web、Auth、Admin、表单、模板、存储和后台能力 |
| `oldman-web`（npm） | Page/Component 生命周期、Dashboard 布局、共享样式、表单、Table、Modal 和浏览器交互 |

内置 Admin 和业务 Dashboard 使用同一套组件、样式与响应协议，不需要分别维护两套前端。

## 从哪里开始

- [用户文档](docs/users/README.md)：安装、创建项目和实际使用。
- [开发者参考](docs/developers/README.md)：准确的接口、加载顺序和扩展方法。
- [Agent 应用开发指南](docs/agents/README.md)：按任务选择文件、完成接线与验证。
- [文档总入口](docs/README.md)：按问题查找正文。

初次使用可先[运行 EPG Dashboard Demo](docs/users/getting-started.md)，再对照其[真实数据](docs/users/tutorial-tasks.md)和[表格、Modal 表单](docs/users/tutorial-dashboard.md)。教程直接使用 Demo 代码，给出源文件、运行目录、配置和预期结果；更多页面见[示例索引](docs/users/demo-examples.md)。

## 最短的项目入口

先准备两样工具：[uv](https://docs.astral.sh/uv/) 负责 Python 环境与依赖，`oldman` 命令行由它安装。`--python 3.13` 把命令行固定在框架支持的版本上；不写的话 uv 会用它能找到的最新解释器，不检查包声明的版本范围。

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install --python 3.13 oldman
```

然后在准备存放项目的父目录执行：

```sh
oldman startproject my_site
```

命令会询问项目类型和数据库。选择 `api`、`none` 后，在新项目目录执行：

```sh
cd my_site
uv sync
./run.sh api settings sync
./run.sh api start
```

此时启动的是尚未添加业务路由的服务；`/` 返回 404 是正常结果。添加 API 的接线见[服务创建指南](docs/agents/create-service.md)；要直接查看完整业务页面则运行上面的 Demo。

`run.sh` 只把原样参数交给项目 `.venv` 中的 `oldman`，不替你选服务、迁移数据库或启动前端。`./run.sh api start` 与使用同一虚拟环境运行 `oldman api start` 的语义相同。上面是新建空项目的命令，不是 Demo 启动步骤；Demo 的独立安装与调试见[运行环境与安装](docs/users/getting-started.md#运行环境与安装)。

## 框架提供什么

- **应用组织**：一个项目可包含多个服务；每个服务读取自己的 YAML，并显式安装需要的 App。App 可提供模型、视图、自定义命令和强类型配置。
- **Web 与数据**：基于 Sanic 的异步服务、Jinja HTML、SQLAlchemy 模型、项目级 Alembic 命令、Auth 与 Admin。
- **页面交互**：后端 Form、HTML/JSON Table，前端 Form/Modal/Feedback/Select/Chart 等共享组件，以及有序的 JSON 响应动作。
- **消息**：Cookie 一次性页面提示、数据库持久通知、临时实时推送、通用 SSE 浏览器投递；进程控制消息有独立职责。
- **基础能力**：文件存储、HTTP Client、缓存、Redis/NATS provider、日志、短生命周期子进程和持久 Worker。
- **持久任务**：Taskiq + NATS JetStream + Redis，支持异步函数投递、多个执行进程、结果、广播和定时计划；与固定本地 Worker、Core NATS 事件/RPC 分开使用。

普通 API 不要求安装前端包。需要共享 Dashboard UI 时再安装 `oldman-web` 及其声明的依赖；内置 Admin 的默认浏览器资源随 Python 包提供。

当前运行目标为 Linux，Python 版本范围为 `>=3.12,<3.15`，推荐 3.13。已知限制：uvloop 0.22.1 在 asyncio 调试模式下会在 CPython 3.13.15、3.14.7 及更新的补丁版上崩溃（[uvloop#699](https://github.com/MagicStack/uvloop/issues/699)、[uvloop#715](https://github.com/MagicStack/uvloop/issues/715)，上游尚未修复），打开 `web.debug` 时请使用已验证的 3.13.11 或 3.14.2，3.12 不受影响。Dashboard 类型项目和两个 Demo 另需 Node.js 20 及以上与 pnpm（`corepack enable` 即可启用）。SQLite 驱动随 Python 包安装；MySQL、PostgreSQL 驱动按项目需要声明。配置中存在 Redis 连接项不代表启动就连接 Redis，启用或调用相应能力时才需要可用的服务。

## 完整示例

- [Admin Demo](https://github.com/alexliyu7352/oldman-admin-demo)：内置后台的独立应用。
- [EPG Dashboard Demo](https://github.com/alexliyu7352/oldman-epg-dashboard)：业务 Dashboard、UI 与功能示例。

示例是独立 Git 仓库，各有配置、虚拟环境、前端依赖和数据库。具体运行步骤以各示例的 README 为准，不在框架目录内安装它们。

## 源码布局

```text
oldman/                       Python 框架和随包资源
frontend/packages/oldman-web/  浏览器包
frontend/apps/admin/          内置 Admin 的前端源码
examples/snippets/            局部用法片段，不是完整应用
tests/                        Python 测试
scripts/                      维护和验证工具
docs/                         用户、开发者与 Agent 文档
```

Python 和 npm 包不包含独立 Demo 的业务代码与运行数据。框架仓库不是业务项目，不在根目录添加应用的 `config/`、`services/` 或数据库。

产品取舍见 [PRODUCT.md](PRODUCT.md)，参与本仓库工作前请读 [AGENTS.md](AGENTS.md)。
