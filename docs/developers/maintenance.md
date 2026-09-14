# 源码开发、验证与发布

本章面向维护框架的人。应用开发者不需要为了使用 Admin 或 Form 跑本仓库的发布验证；应用部署见[部署指南](../users/deployment.md)。

## 仓库布局与工作环境

| 路径 | 职责 |
| --- | --- |
| `oldman/` | Python 包；App、运行时、Web、数据与其他公共能力 |
| `frontend/packages/oldman-web/` | 发布的浏览器组件包 |
| `frontend/apps/admin/` | 内置 Admin 的前端消费者；产物进入 Python 包静态目录 |
| `oldman/scaffolds/` | 项目、App、服务的生成模板 |
| `tests/` | Python 行为及安装/维护脚本检查 |
| `scripts/` | 构建、安装、浏览器及发布验证工具，不是业务 API |
| `docs/users`、`docs/developers`、`docs/agents` | 用法、准确接口与任务接线 |

完整 Admin/Dashboard Demo 是独立仓库，有自己的依赖、配置、数据库和 Git。根 README 提供入口。不要在框架中创建业务 config、services、数据目录或将 Demo 本地配置提交回来。

在框架根目录准备环境：

```sh
uv sync --group dev
pnpm install --frozen-lockfile
```

当前元数据要求 Python 3.12/3.13、Node 20 及以上，packageManager 指定 pnpm 9.12.3。前端依赖版本以仓库的 `pnpm-lock.yaml` 为准；Python 依赖只受 `pyproject.toml` 的约束，`uv.lock` 是本机解析结果，不提交仓库。不通过随意升级来绕过失败。依赖变化本身应是独立、可审阅的任务。

编辑前检查 Git 状态、现有风格与全部相关调用方；一个明确任务一个提交。发布校验不是要求提交用户的未完成修改。需要干净已提交源码时先分清归属，不用 reset 或 add . 清场。

## 日常验证：只运行相关范围

Python 例子：

```sh
.venv/bin/python -m unittest -q tests.test_oldman_web_auth_user_session
.venv/bin/ruff check oldman/web/auth/user_session.py
.venv/bin/pyright oldman/web/auth/user_session.py
```

用本次实际文件替换例子。测试应覆盖真实行为和必要失败路径，不以“实现里恰好出现某个字符串”代替行为。修改共享函数时，核对它的全部消费者。

前端改动在对应包执行 test/typecheck，并在真实 Chrome 操作相关页面。检查初始化、重复进入、远程内容替换、离开页面及失败反馈；截图只是证据，不能代替点击和结果核对。兼容目标不只 Chrome。

启动服务、浏览器和 Redis 时只管理本任务的进程。临时数据放自己创建的 `/tmp` 子目录，不使用 `/dev/shm`，不复用真实 Demo 的数据库做破坏性检查。结束后停止子进程，确认端口释放，再删除自己的临时目录。

Settings/App Registry/模型的隔离见[测试隔离约束](testing.md)，不为测试给生产层增加 reset、第二套 Settings 或假 provider。

## 浏览器包和 Admin 构建

```sh
pnpm --filter oldman-web build
pnpm --filter oldman-admin build
```

按顺序执行。oldman-web 的 prebuild 生成图标、前端词条清单与 i18n CLI，编译 TS 并复制样式；Admin 从这个包导入公共实现，Vite 输出到 `oldman/apps/admin/static/oldman/admin`。

这些命令会更新生成文件，并清理相应构建目标。运行前保存用户修改，之后核对 diff，不手工修改压缩 JS/CSS。自定义应用样式和图标应在应用自身构建，不把业务依赖塞进框架。

翻译修改的真实流程是提取 POT → 更新 PO → 翻译 → 编译 MO/前端 JSON，不是直接改某个已生成字典。应用侧参考[资源文档](assets.md)，框架 CLI 维护入口见 [locales README](../../oldman/cli/locales/README.md)。

## 版本与构建产物

版本权威是根 `pyproject.toml` 的 `project.version`。需要发布新版本时，先修改它，再使用现有同步命令：

```sh
pnpm version:sync
pnpm verify:version
```

同步会更新 Python/npm 中的版本副本，必须审阅产生的差异。不要逐个随手修改版本而遗漏另一个包。

构建发布候选：

```sh
pnpm build:python
pnpm pack:web
```

第一条构建 Admin 后生成 wheel/sdist；第二条构建并打包 oldman-web。当前普通版本的产物位置为：

- `dist/oldman-<Python规范化版本>-py3-none-any.whl`
- `dist/oldman-<Python规范化版本>.tar.gz`
- `frontend/packages/oldman-web/oldman-web-<版本>.tgz`

预发布版本的 Python 文件名可能被规范化；维护工具使用 `scripts/release_artifacts.py` 计算路径，不按最近修改时间或 glob 猜本次产物。安装校验必须针对实际准备发布的文件和 hash，不用 editable 安装冒充 wheel 验证。

Python 包包括运行代码、模板、Admin 构建、迁移、脚手架和需要的 MO；许可资料随包提供。sdist 有自己明确的内容规则，不能因为源码目录存在某个文件就认为发行包一定包含。

## 集中验收：分阶段串行

仅在准备发布或用户明确要求完整验收时，按以下阶段执行。前一阶段失败先定位，不把所有命令同时放到后台：

```sh
pnpm verify:static
pnpm verify:python
pnpm verify:frontend
pnpm verify:web-boundaries
pnpm verify:web-package
pnpm verify:python-package
pnpm verify:scaffold-matrix
```

- static：Python lint 和类型检查。
- python：Python 全量测试。
- frontend：两个前端包的测试与类型检查。
- web-boundaries：已有前端边界检查。
- web-package：当前版本 npm 产物及真实消费者验证。
- python-package：当前版本 wheel/sdist 内容、Python 3.12/3.13 安装及内置 Admin Chrome 验证。
- scaffold-matrix：使用实际发行产物创建项目并验证生成服务，包含需要的浏览器环节。

包和脚手架阶段会建立隔离环境、下载依赖并构建，明显比普通单元测试消耗更多磁盘和内存。先检查可用空间、内存及已运行的服务，Chrome 一次只运行一个任务。不能给所有机器保证固定空间上限；环境和下载缓存会改变实际占用。

这些入口默认把证据保存在 `/tmp/oldman-*-evidence` 下，并不会在完成后自动删除全部结果。需要明确位置时直接调用对应 `scripts/verify-current-release-*.py --evidence-root /tmp/本次专用父目录`。每次工具会创建独立运行目录；不要把用户共享目录作为清理目标。

查看对应 result.json、日志和浏览器截图后，记录结论。需要保留的证据先归档到用户指定位置，确认本轮进程已退出，再删除**该次运行的精确目录**。不要对整个 `/tmp` 或任意通配目录执行递归删除。

高级 `--use-existing-artifacts` 路径要求提供对应 SHA-256，不能仅凭文件名绕过构建确认。其参数通过脚本 --help 查询；普通维护者直接用默认阶段入口即可。

## 发布不是测试的副作用

构建和验收不会自动上传。实际发布前还需明确目标索引、账号权限、版本、许可、发行说明与回滚安排。获得明确发布授权后，上传同一组已验收产物；不能验收一份又临时重新构建另一份上传。

没有执行的阶段、已知失败、弃用警告和未做的人工操作都应如实说明。文档重写或少数定向检查通过，不代表当次全量验收已通过，更不代表外部包索引已有这个版本。
