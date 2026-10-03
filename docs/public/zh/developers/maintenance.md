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
| `docs/public/<语言>/` | 对外文档：`users` 用法、`developers` 准确接口、`agents` 任务接线 |

完整 Admin/Dashboard Demo 是独立仓库，有自己的依赖、配置、数据库和 Git。根 README 提供入口。不要在框架中创建业务 config、services、数据目录或将 Demo 本地配置提交回来。

在框架根目录准备环境：

```sh
uv sync --group dev
pnpm install --frozen-lockfile
```

当前元数据要求 Python 3.12 到 3.14、Node 20 及以上，packageManager 指定 pnpm 9.12.3。前端依赖版本以仓库的 `pnpm-lock.yaml` 为准；Python 依赖只受 `pyproject.toml` 的约束，`uv.lock` 是本机解析结果，不提交仓库。不通过随意升级来绕过失败。依赖变化本身应是独立、可审阅的任务。CI 的 3.13 与 3.14 矩阵钉在 3.13.11 与 3.14.2：asyncio 调试模式（`IsolatedAsyncioTestCase` 会强制开启）下，uvloop（0.22.1、0.23.0 都未修复）回收未关闭的 async generator 会崩溃（[uvloop#699](https://github.com/MagicStack/uvloop/issues/699)、[uvloop#715](https://github.com/MagicStack/uvloop/issues/715)），框架测试在 3.13.15、3.14.7 上触发，在这两个版本上不触发；上游修复后再放开。

编辑前检查 Git 状态、现有风格与全部相关调用方；一个明确任务一个提交，标题的写法见[提交标题与发行说明](#提交标题与发行说明)。发布校验不是要求提交用户的未完成修改。需要干净已提交源码时先分清归属，不用 reset 或 add . 清场。

## 日常验证：只运行相关范围

Python 例子：

```sh
.venv/bin/python -m unittest -q tests.test_oldman_web_auth_user_session
.venv/bin/ruff check oldman/web/auth/user_session.py
.venv/bin/ruff format --check oldman/web/auth/user_session.py
.venv/bin/pyright oldman/web/auth/user_session.py
```

用本次实际文件替换例子。测试应覆盖真实行为和必要失败路径，不以“实现里恰好出现某个字符串”代替行为。修改共享函数时，核对它的全部消费者。

改了公开名字（模块的 `__all__`，或导出名字的签名、文档字符串第一行）后，运行 `.venv/bin/python scripts/api_index.py --write`，把 `docs/public/en/api/` 的变化一起提交。`tests/test_api_index.py` 检查索引与源码一致，并检查公开文档里的每个 `from oldman... import` 都能在索引里找到；文档要用一个没写进 `__all__` 的名字时，先确认它确实应当公开，再把它写进所在模块的 `__all__`。

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

翻译修改的真实流程是提取 POT → 更新 PO → 翻译 → 编译 MO/前端 JSON，不是直接改某个已生成字典。应用侧参考[资源文档](assets.md#框架自带的翻译)。

框架自己的翻译只有一份 `oldman/locales`（Admin、账户页面、表格与表单、通知、角色、CLI 与迁移命令、`oldman-web` 前端文案都在里面），用 [scripts/framework_i18n.py](https://github.com/alexliyu7352/oldman/blob/main/scripts/framework_i18n.py) 维护。新增、修改或删除了框架文案（包括 `oldman-web` 的前端文案，先跑 `generate:i18n-messages`）之后，在框架根目录：

```sh
.venv/bin/python scripts/framework_i18n.py update    # 重建 messages.pot，并入 zh_Hans、zh_Hant 的 PO
# 逐条翻译新增条目，确认 fuzzy 条目后去掉 fuzzy 标记
.venv/bin/python scripts/framework_i18n.py compile   # 写出 wheel 发布的 .mo
.venv/bin/python scripts/framework_i18n.py check     # 列出仍然过时的地方，没有输出即可
```

抽取用的是 `oldman/i18n/framework-babel.cfg` 加前端文案清单，与项目 `i18n extract` 收框架文案的那一半是同一个函数，所以两边覆盖的文案不会不同。框架新加一个带文案的目录时，在这份配置里加上它。模板和 PO 不写行号，只挪动代码不会让目录过时。`tests/test_oldman_framework_translations.py` 在常规测试里跑同样的检查：模板与源码不一致、有未翻译或 fuzzy 条目、MO 与 PO 不一致都会失败。`.mo` 与 `.pot` 在 `.gitignore` 里，提交时按路径 `git add -f`。

## 版本与发布

版本权威是根 `pyproject.toml` 的 `project.version`，它必须同时是合法的 SemVer 和合法的 PEP 440 版本：正式版写 `0.1.1`，预发布写 `0.1.1-rc.1`。Python 产物的文件名与元数据使用 PEP 440 规范形式（`0.1.1rc1`），npm 使用原样字符串；维护脚本一律通过 `scripts/release_artifacts.py` 的 `python_distribution_version()` 换算，不手工拼接。

发布由 GitHub Actions 完成，本地只做三件事：

1. 修改 `project.version`，运行 `pnpm version:sync`，审阅并提交它改写的 Python/npm 版本副本（`package.json`、两个前端包、`oldman/version.py`、`OLDMAN_WEB_VERSION`）。不要逐个随手修改版本而遗漏另一个包。
2. 在 `main` 的这个提交上打注释标签 `v<版本>`（例如 `v0.1.1`、`v0.1.1-rc.1`），推送 `main` 与标签。
3. 在 Actions 中查看 Release 运行结果，并核对 PyPI、npm 与 GitHub Release。

`.github/workflows/release.yml` 依次执行：校验标签名等于 `pyproject.toml` 版本；按提交标题生成发行说明（见下一节）；`pnpm build:python` 与 `pnpm pack:web`；`verify-wheel-contents`、`verify-sdist-contents`、`verify-python-package-install`（Python 3.12、3.13 与 3.14）、`verify-oldman-web-package`；全部通过后通过 Trusted Publishing（OIDC 身份，不保存长期令牌）发布到 PyPI 与 npm，并创建 GitHub Release：正文是生成的发行说明，附带三个产物和 `SHA256SUMS`。任何一步失败都不会发布任何内容；修复后删除该标签并重新打在新的提交上即可。

### 提交标题与发行说明

仓库不维护 CHANGELOG 文件，每个版本的发行说明就是 GitHub Release 的正文，由发布工作流用 git-cliff 按根目录的 `cliff.toml` 从提交标题生成。所以提交标题就是发行说明里的一条，要写成给使用者看的一句英文：

```text
type(scope): summary
```

- `type` 决定分组：`feat` 进 Added，`fix` 进 Fixed，`perf` 进 Performance，`refactor` 进 Changed，`docs` 进 Documentation，`revert` 进 Reverted；`test`、`build`、`ci`、`chore`、`release` 不进发行说明。
- `scope` 可选，写受影响的子系统，例如 `fix(web): ...`。
- 破坏性变更在类型后加 `!`（`feat(db)!: ...`），或在正文末尾写 `BREAKING CHANGE: ...` 脚注；这类条目排在发行说明最前面。
- 正文不进发行说明，用来写原因和实现细节。
- 不符合格式的标题仍会出现在 Other 分组里，不会被丢掉，但应当避免。

正式版的说明从上一个正式版算起，包括其间预发布的提交；预发布的说明从上一个标签算起。发版前在本地预览将要生成的说明：

```sh
uvx git-cliff@2.14.2 --unreleased
```

提交推送之后标题就不能再改；写错了可以在 Release 页面直接修改正文。

预发布版本（版本号含 `-`）：PyPI 视为 pre-release，`pip install oldman` 默认不会选中它，需要 `--pre` 或精确版本；npm 发布到 `next` dist-tag，`latest` 不变；GitHub Release 标记为 prerelease。用预发布版本演练发布链路不会影响正式用户。

`.github/workflows/ci.yml` 在每次推送和 PR 上运行静态检查、Python 与前端测试；真实服务检查需要 `redis-server`（6.2 或更新，取自 apt）和 `nats-server`（工作流下载固定版本并校验 SHA-256），缺了就失败，不跳过，见[测试隔离约束](testing.md#真实服务检查)。

本地复核发布产物时使用同一套命令：

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

- static：Python lint 与格式检查（`ruff check`、`ruff format --check`，代码按 `ruff format` 统一）和两种类型检查（pyright、Pyrefly）。Pyrefly 的版本固定在 `pyproject.toml` 的 dev 依赖里，配置在 `[tool.pyrefly]`。
- python：Python 全量测试。
- frontend：两个前端包的测试与类型检查。
- web-boundaries：已有前端边界检查。
- web-package：当前版本 npm 产物及真实消费者验证。
- python-package：当前版本 wheel/sdist 内容、Python 3.12 到 3.14 安装及内置 Admin Chrome 验证（Release 工作流运行其中不依赖浏览器的部分）。
- scaffold-matrix：使用实际发行产物创建项目并验证生成服务，包含需要的浏览器环节。

包和脚手架阶段会建立隔离环境、下载依赖并构建，明显比普通单元测试消耗更多磁盘和内存。先检查可用空间、内存及已运行的服务，Chrome 一次只运行一个任务。不能给所有机器保证固定空间上限；环境和下载缓存会改变实际占用。

这些入口默认把证据保存在 `/tmp/oldman-*-evidence` 下，并不会在完成后自动删除全部结果。需要明确位置时直接调用对应 `scripts/verify-current-release-*.py --evidence-root /tmp/本次专用父目录`。每次工具会创建独立运行目录；不要把用户共享目录作为清理目标。

查看对应 result.json、日志和浏览器截图后，记录结论。需要保留的证据先归档到用户指定位置，确认本轮进程已退出，再删除**该次运行的精确目录**。不要对整个 `/tmp` 或任意通配目录执行递归删除。

高级 `--use-existing-artifacts` 路径要求提供对应 SHA-256，不能仅凭文件名绕过构建确认。其参数通过脚本 --help 查询；普通维护者直接用默认阶段入口即可。

## 发布不是测试的副作用

构建和验收不会自动上传。实际发布前还需明确目标索引、账号权限、版本、许可、发行说明与回滚安排。获得明确发布授权后，上传同一组已验收产物；不能验收一份又临时重新构建另一份上传。

没有执行的阶段、已知失败、弃用警告和未做的人工操作都应如实说明。文档重写或少数定向检查通过，不代表当次全量验收已通过，更不代表外部包索引已有这个版本。
