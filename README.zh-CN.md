# Oldman

[English](https://github.com/alexliyu7352/oldman/blob/main/README.md) | 简体中文

**用一个 Python 框架做完整的业务后台。** Dashboard、管理后台、API、后台任务、服务间通信、终端运维工具，以及给 AI agent 用的 MCP 接口，共用同一套配置、权限和界面。框架基于 Sanic，同一台机器上实测，每秒处理的请求约为 FastAPI 的 1.8 倍。

![EPG Dashboard 示例的频道列表：带搜索、列与导出菜单、分页的表格，位于带侧栏的 Dashboard 外壳中](https://raw.githubusercontent.com/alexliyu7352/oldman/main/website/static/img/epg-channels-light.webp)

**给编码 agent**：先读 [Agent 应用开发指南](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/agents/README.md)，文档以已安装版本的 tag 为准，每个 `oldman` import 先查 [API 索引](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/api/README.md)。不是用 `oldman startproject` 建的项目没有 `AGENTS.md`，可以把[这一段](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/agents/README.md#已有项目在自己的指令文件里加一段)贴进项目自己的 `AGENTS.md` 或 `CLAUDE.md`。

## 为什么选 Oldman

### 一个框架，做完整个后台

一个项目可以有多个服务。每个服务读自己的 YAML、安装自己需要的 App，但共用同一套强类型配置、模型、权限和生命周期：

- **Web**：业务 Dashboard 和内置 Admin，Sanic + Jinja 后端渲染。
- **API**：同一条认证流水线，支持 Session、JWT、API key、HTTP Basic 和 IP 白名单。
- **后台工作**：同进程协程、子进程和常驻 Worker；Taskiq + NATS JetStream 的持久任务，带结果、广播和定时计划。
- **服务间通信**：NATS 事件与 RPC。
- **终端运维工具**：编号菜单、表单、可预置答案的无人值守模式，以及远程脚本和 systemd 操作。
- **MCP 服务端**：把 App 的数据交给 AI agent，见下文。

[EPG 示例](https://github.com/alexliyu7352/oldman-epg-dashboard)就是这样一个项目：`./run.sh web start`、`./run.sh task_worker start`、`./run.sh task_scheduler start`、`./run.sh nats_a start` 分别启动网页、任务执行、定时投递和 NATS 接收服务，它们读同一份配置类型、用同一批模型。

### 开箱就是完整的后台

- **`oldman startproject` 选 dashboard**：生成登录与登出、个人页（改密码、切换语言）、通知中心、用户管理、角色与权限管理，前端构建和共享界面都已接好。找回密码、令牌接口各加一个现成的流程就能用。
- **内置 Admin**：和 Django admin 一样，注册模型就有列表、搜索、排序、新增、编辑、删除和 CSV 导出；不需要编译前端，默认的浏览器资源随 Python 包提供。

```python
class DemoProjectAdmin(ModelAdmin):
    list_display = ("id", "name", "owner", "status", "is_active", "created_at")
    search_fields = ("name", "owner", "status")
    ordering = ("name",)
```

### 少写前端，也能做交互页面

表格、表单、Modal、图表和实时推送都在 Python 端声明；浏览器端组件由 `oldman-web` 提供，页面切换时自动挂载和清理，只有真正需要的地方才写 TypeScript。上面截图里的频道表格（搜索、排序、分页、勾选行、选择显示的列、CSV 导出）来自这一个类（节选）：

```python
class ChannelsEpgTable(SQLAlchemyTableView):
    route_path = "/channels-epg/table"
    model = ChannelsEpg
    page_size = 10
    selectable = True
    export_formats = ("csv",)
    search_fields = ["name", "src_url", "country"]
    columns = [
        (_("ID"), "id"),
        (_("Name"), "name"),
        (_("Source URL"), "src_url", "get_column_src_url_data"),
        (_("Country"), "country"),
        (_("Hits"), "hits"),
        (_("Last Date"), "last_date"),
        (_("Action"), None, "get_column_action_data"),
    ]
```

内置 Admin 和业务 Dashboard 用同一套组件、样式与响应协议，只需要维护一套前端。

### 为 AI 时代设计

- **内置 MCP 服务端**：App 用装饰器声明工具、resource 和 prompt，Web 服务在同一套认证、权限和限流之后，把它们提供给 Claude Code、Cursor 等 AI agent。它是 Web 服务里的一个路由，不另起服务器，也不依赖官方 SDK。
- **写给编码 agent 的资料**：`oldman startproject` 生成的项目自带 `AGENTS.md`，已有项目把一段现成的说明贴进自己的 `AGENTS.md` 或 `CLAUDE.md`；框架有英文的 agent 开发指南和从源码生成的 API 索引，agent 照着就能把新功能接对。

```python
@mcp.tool(permission=ReportPermissions.view)
async def count_reports(request: Request, status: str) -> int:
    """Count reports in one status."""
    async with db_manager.get_read_session() as session:
        ...
```

### 快

Oldman 基于 Sanic，认证与中间层几乎不增加开销：

| 单个 worker，返回同一份 JSON | 每秒请求 | p99 延迟 |
| --- | ---: | ---: |
| **Oldman 0.8.0**（每个请求都经过认证流水线） | **约 20,300** | **6.1 ms** |
| Sanic 25.12（直接使用） | 约 17,900 | 6.8 ms |
| FastAPI 0.159 + uvicorn（返回值用 orjson 编码） | 约 13,000 | 9.2 ms |
| FastAPI 0.159 + uvicorn（默认写法） | 约 11,100 | 10.7 ms |

测试条件：同一台 AMD Ryzen 7 3800X，Python 3.13.11；每个服务 1 个 worker，绑在同一颗 CPU 上；oha 用 64 个连接跑 3 轮、每轮 15 秒，取中位数；uvicorn 使用 uvloop 和 httptools。Oldman 用的是 `startproject` 生成的 API 项目原样。这是只测框架开销的微基准，真实应用的瓶颈通常在数据库和外部调用。

### 生产环境需要的细节已经做好

- 强类型配置：项目只有一个根 Settings 类型，每个 App 自带强类型设置，`settings sync` 按类型补齐 YAML 里缺的字段，保留已有的值和注释。
- 安全：CSRF、登录与 MCP 限流、密码重置令牌、改密或停用后撤销全部会话和令牌。
- 进程：Web、Worker、Scheduler 都有 PID 锁和整组停止，超时后强制结束并确认退出。
- 内置简体、繁体中文翻译，项目自己的文案走同一条提取、翻译、编译流程。
- 站在成熟实现上：Sanic、SQLAlchemy、Alembic、Jinja、Taskiq、NATS，表单核心改写自 WTForms，不另造一套底层。

## 和常见组合比较

| 需要 | 常见做法 | Oldman |
| --- | --- | --- |
| 管理后台 | Django 自带 admin；FastAPI 要另选 SQLAdmin 等第三方库 | 内置 Admin，和业务页面共用一套界面 |
| 带账户和权限的业务后台 | 自己搭页面，或套用前端模板 | `startproject` 生成登录、用户、角色与权限管理 |
| 交互页面 | 另写 React、Vue 前端，或自己接 htmx | Python 端声明表格、表单与 Modal，用共享组件 |
| 持久任务 | 另接 Celery 等任务队列 | 内置 Taskiq + NATS JetStream |
| 服务间事件与 RPC | 另选消息库，自己接线 | 内置 NATS 事件与 RPC |
| 终端运维工具 | 另写 Click、Typer 脚本 | 同一套 App 命令、终端菜单与表单 |
| 给 AI agent 的接口 | 另装 MCP SDK，自己接认证 | 内置 MCP 服务端，沿用认证与权限 |

## 快速开始

先准备 [uv](https://docs.astral.sh/uv/)，它负责 Python 环境和依赖，`oldman` 命令行也由它安装：

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install --python 3.13 oldman
oldman startproject my_site
```

`startproject` 第一次运行时先问命令行的显示语言，然后问项目类型和数据库。选 `api`、`none` 得到一个最小的 API 项目：

```sh
cd my_site
uv sync
./run.sh api settings sync
./run.sh api start
```

服务自带三个接口：`/` 是不需要认证的健康检查，`/api/caller`、`/api/ops` 分别演示 API key 和 HTTP Basic 认证，凭据位置和试用命令见生成项目的 README。要看完整的业务页面，先[运行 EPG Dashboard 示例](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/users/getting-started.md)，再对照[真实数据](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/users/tutorial-tasks.md)和[表格、Modal 表单](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/users/tutorial-dashboard.md)两篇教程。

## 完整示例

- [EPG Dashboard](https://github.com/alexliyu7352/oldman-epg-dashboard)：建立在 dashboard 骨架上的完整业务后台，有账户、通知、用户与角色管理，以及 UI 和功能示例。
- [内置 Admin](https://github.com/alexliyu7352/oldman-admin-demo)：内置后台作为独立应用运行。
- [运维工具](https://github.com/alexliyu7352/oldman-ops-demo)：终端里的服务器维护工具，改 sshd、sysctl、nginx 站点，重启服务。

示例是独立的 Git 仓库，各有配置、虚拟环境、前端依赖和数据库，运行步骤以各自的 README 为准。

## 文档

- [文档站](https://alexliyu7352.github.io/oldman/)：英文、简体中文、繁体中文，可本地搜索。
- [用户文档](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/users/README.md)：安装、创建项目和实际使用。
- [开发者参考](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/README.md)：准确的接口、加载顺序和扩展方法。
- [Agent 应用开发指南](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/agents/README.md)：给编码 agent，按任务选择文件、完成接线与验证。

## 要求与限制

- Linux；Python `>=3.12,<3.15`，推荐 3.13。
- 两个包：`oldman`（PyPI）是框架本身，普通 API 只需要它；`oldman-web`（npm）是 Dashboard 的浏览器端，dashboard 项目和示例另需 Node.js 20 及以上与 pnpm（`corepack enable` 即可）。内置 Admin 的浏览器资源随 Python 包提供。
- SQLite 驱动随包安装；MySQL、PostgreSQL 驱动按项目需要声明。配置里有 Redis 连接项不代表启动就连 Redis，启用或调用相应能力时才需要。
- 已知问题：打开 `core.debug`（asyncio 调试模式）时，uvloop 回收没有关闭的 async generator 可能报错或段错误（[uvloop#699](https://github.com/MagicStack/uvloop/issues/699)、[uvloop#715](https://github.com/MagicStack/uvloop/issues/715)）。默认关闭调试的生产运行不受影响，详见[配置参考](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/configuration.md#web-默认值与开关)。

## 源码布局

```text
oldman/                       Python 框架和随包资源
frontend/packages/oldman-web/  浏览器包
frontend/apps/admin/          内置 Admin 的前端源码
examples/snippets/            局部用法片段，不是完整应用
tests/                        Python 测试
scripts/                      维护和验证工具
docs/                         用户、开发者与 Agent 文档
website/                      文档站
```

产品取舍见 [PRODUCT.md](https://github.com/alexliyu7352/oldman/blob/main/PRODUCT.md)。
