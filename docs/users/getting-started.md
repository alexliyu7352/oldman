# 运行 EPG Dashboard Demo

本教程直接使用 [EPG Dashboard Demo](https://github.com/alexliyu7352/oldman-epg-dashboard)，不要求另建一套教程项目。后面的模型、表单、表格、模板和 Page 都能在这个仓库找到，浏览器操作的也是这些代码。链接是项目仓库地址；应使用与当前框架相配的Demo提交，本文不证明尚未推送的本地改动已出现在远端。

这是包含真实数据库和登录功能的 Dashboard，不是只返回固定 JSON 的最小 API。只想创建空项目时，使用 [服务创建指南](../agents/create-service.md)；不要为了运行本教程把 Demo 的 App、Redis 或前端初始化删掉。

## 运行环境与安装

使用 Linux、Python 3.12 到 3.14（推荐 3.13）、uv、Node.js 20 及以上和 pnpm。`bootstrap.py` 会直接调用 `uv` 和 `pnpm`，两者都要先在 PATH 里：

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh          # uv：Python 与依赖管理
# Node.js 20 及以上按你的发行版或 nvm 安装，然后启用随 Node 附带的 corepack：
corepack enable                                          # 提供 pnpm，版本由仓库 package.json 的 packageManager 指定
```

还需要可访问的 Redis；默认示例启用 Taskiq 和 Core 通信，因此也需要启用 JetStream 的 NATS，准备方式见[通信教程](service-communication.md#1-准备并启动-demo)。具体依赖来自 Demo 的 [pyproject.toml](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/pyproject.toml) 和 [frontend/package.json](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/package.json)，不在文档维护第二份安装版本表。

尚未取得 Demo 时，在准备存放项目的目录克隆：

```sh
git clone https://github.com/alexliyu7352/oldman-epg-dashboard.git oldman_epg_dashboard
cd oldman_epg_dashboard
python3 scripts/bootstrap.py
```

已经有这个仓库时，进入现有目录运行 bootstrap，不重复克隆。后续命令除非另有说明，都在 **Demo 根目录**执行，不在框架源码目录执行。

[bootstrap.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/scripts/bootstrap.py) 有两条实际安装路径：

- 同级存在 `oldman_framwork/` 或 `oldman/` 源码：创建 Demo 自己的 `.local/oldman` 链接和 `.venv`，Python 使用 editable 安装，Vite 使用框架前端源码。
- 没有同级源码：安装清单声明的发行包。只有对应版本已经在所用包索引发布时，这条路径才可用；不能把同名旧包当成当前源码版本。

两条路径使用同一份业务代码。不需要每次在本地调试和公开示例之间修改依赖清单，也不需要把 Demo 安装进框架的虚拟环境。

## 1. 准备当前服务的配置

Demo 的 [services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py) 定义 `WebService`，文件名决定服务叫 `web`，所以命令和默认配置文件分别是：

```text
./run.sh web ...
data/web_settings.yaml
```

首次运行，为 Demo 已定义的五个服务创建缺少的配置文件。即使暂时只启动 Web，项目级迁移也要读取这些配置：

```sh
for service in web task_worker task_scheduler nats_a nats_b; do
  test -e "data/${service}_settings.yaml" || cp "data/${service}_settings.example.yaml" "data/${service}_settings.yaml"
  ./run.sh "$service" settings sync
done
./run.sh web settings check
```

**已有配置不要再次覆盖**，只运行 sync/check 并检查所需节点。sync 补齐默认值和缺失安全密钥；check 验证配置，不创建数据表、不导入演示数据，也不证明 Redis 已连接成功。真实密钥和本地配置不应提交。

五个服务使用同一数据库和 Auth User 模型。配置文件齐全不等于同时启动全部服务；只看普通 Dashboard 时不用启动 Worker、Scheduler、nats_a/nats_b。若暂不运行 NATS，在自己的 Web YAML 中同时关闭 taskiq.enabled 和 nats_bus.enabled；不能只关闭 Taskiq 却留下已启用的 Core 连接。要查看对应功能时再按各教程开启和启动。

[配置模板](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/web_settings.example.yaml) 中的数据库与 Redis 节点如下。这是现有文件的节选，不要把它追加为第二组同名节点：

```yaml
database:
  url: sqlite+aiosqlite:///data/epg_dashboard.db
  echo: false
  enable_sql_logging: false
redis:
  SESSION:
    redis_url: redis://127.0.0.1:6379/5
  SSE:
    redis_url: redis://127.0.0.1:6379/6
```

SQLite 保存业务数据，Redis 的 SESSION 连接保存会话，SSE 连接用于实时投递。完整示例还包含CACHE（统计缓存）和TASKIQ（任务结果/计划）别名；按自己的环境逐项核对，不能只修改本节摘出的两个地址。Demo不会替使用者启动或管理外部Redis。演示命令/按钮会修改各自明确说明的缓存键，不清空整个实例。共享Redis时，还要检查 `web.session.prefix`、`user_prefix`、`web.sse.channel_prefix`、缓存前缀及Taskiq namespace；Pub/Sub不按Redis数据库编号隔离，独立验证优先使用独占实例。

## 2. 建立表，再导入数据

按 Demo README 的顺序运行：

```sh
./run.sh db migrate
./run.sh web loaddata demo
./run.sh web createsuperuser
```

- `db migrate` 执行仓库已经携带的迁移。新数据库选择“首次使用”；如果不是新数据库，不要为了绕过提示把它当成首次使用。
- `loaddata demo` 读取 `apps/examples/fixtures/demo.json`，导入示例和 EPG 业务页面的真实记录。
- `createsuperuser` 来自已安装的 Admin App，在交互中输入账号和密码。不要假设存在默认账号或默认密码。

已有数据库不应重新生成初始迁移。重复导入 fixture 会更新相同主键的指定字段，可能覆盖你对预设记录的编辑；它不是“只补缺失数据”的操作。详见[数据教程](tutorial-tasks.md)。

## 3. 构建并启动

```sh
pnpm --dir frontend build
./run.sh web static collect
./run.sh web start
```

前端 build 的前置步骤已经包含图标收集和浏览器翻译生成；static collect 收集框架及已安装 App 的静态资源。产品模式的 Web 服务读取构建 manifest，不连接 Vite。

打开 [http://127.0.0.1:17998/](http://127.0.0.1:17998/)。未登录会进入登录页，使用刚创建的账号登录。然后打开：

- [/examples/tables/static](http://127.0.0.1:17998/examples/tables/static)：数据库数据由后端直接渲染。
- [/examples/tables/html](http://127.0.0.1:17998/examples/tables/html)：服务端 HTML 动态表格。
- [/examples/tables/json](http://127.0.0.1:17998/examples/tables/json)：同一查询的 JSON 动态表格。

正常的示例数据应出现；只有“页面能打开”但列表为空，并不等于完成了初始化。下一章解释如何查数据来自哪里。

`web start` 在前台运行。在该终端按 Ctrl+C 停止；不要为释放端口终止不属于自己的服务。17998 已被使用时，先确定是否就是现有 Demo；需要独立实例时使用独立目录、数据库和配置，并相应调整地址。

## 4. 本地调试

停止自己启动的产品模式服务后，在同一 Demo 根目录运行：

```sh
python3 scripts/dev.py
```

这个 Demo 脚本管理 Vite 和 Web 服务；浏览器仍访问后端 17998，而不是把前端模板预览当成真实业务页面。使用同级框架源码时，修改 Python/TypeScript 可以直接调试，不要求先重新打 wheel。

`run.sh` 的职责不同。它只切换到项目根目录，把参数原样交给 `.venv/bin/oldman`。例如 `./run.sh web start` 与使用这个环境执行 `oldman web start` 等价；运行 `./run.sh` 不会自动迁移、导入数据或启动多个服务。

## 从页面找到代码

| 你正在看什么 | Demo 中的文件 |
| --- | --- |
| 服务、CSRF、模板和 bundle 初始化 | [services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py) |
| 根配置类型、全局配置入口 | [config/schemas.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/config/schemas.py)、[config/settings.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/config/settings.py) |
| 登录、退出、当前用户会话 | [apps/auth/views.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/auth/views.py) |
| 示例 App 的显示名称、图标和注册对象 | [apps/examples/apps.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/apps.py) |
| 示例分类与具体路由模块加载 | [apps/examples/views/__init__.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/__init__.py) |
| 浏览器唯一启动入口 | [frontend/src/main.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/main.ts) |
| 示例页的私有组件与动作 | [frontend/src/pages/examples.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/pages/examples.ts) |

模板在 `templates/pages/examples/`，不是 `templates/examples/`。前端示例页共用 `ExamplesPage`，不要求每个 URL 都有同名 TS 文件。

## 常见问题

| 现象 | 检查 |
| --- | --- |
| 提示 Oldman 未安装 | 先运行 Demo 的 bootstrap；全局安装不等于 Demo 的 .venv 已安装 |
| 提示 auth 未安装 | 是否复制了正确的 example YAML，当前服务 apps 列表是否完整 |
| 登录失败 | 是否先 migrate 再 createsuperuser；使用自己创建的账号 |
| 登录/实时请求出现 Redis 错误 | Redis 是否可达，SESSION/SSE alias 和配置是否一致 |
| 表格为空 | 是否在同一 Demo、同一数据库上执行 loaddata demo |
| 页面无样式、缺图标或提示 manifest 不存在 | 是否完成 frontend build 和 web static collect，静态路径是否正确 |
| 老页面提交出现 CSRF 403 | 刷新取得新令牌；不要关闭 CSRF 来解决 |
| 页面正常但交互无反应 | 检查浏览器脚本请求、Console 和当前 Page；不能只检查 HTML 返回了 200 |

接下来阅读[真实数据与迁移](tutorial-tasks.md)，再阅读[表格与 Modal 表单](tutorial-dashboard.md)。其他已实现功能的页面和源码见 [Demo 示例索引](demo-examples.md)。
