# 测试隔离约束

本章约束测试和验证环境，不增加生产 API。服务运行仍是一进程、一份根配置、一组 App 和模型。测试方便不能成为修改此模型的理由。

## 按被测边界选择隔离

| 测什么 | 合适环境 |
| --- | --- |
| 纯函数、序列化、无配置对象 | 普通单元测试，显式传输入 |
| 函数读取当前配置 | 测试内临时绑定全局配置并在结束后恢复，检查真正行为 |
| Settings、App Registry、模型加载、服务发现 | 临时完整项目 + 独立 Python 进程 |
| 数据库事务、外键、文件清理 | 独立数据库和 Storage 目录，真实 flush/commit/rollback |
| Redis/NATS 跨进程语义 | 任务独占实例或明确隔离资源，实际发布/读取 |
| 页面交互、构建或安装 | 隔离应用，实际产物、浏览器及数据结果 |

框架现有 `tests/test_oldman_service_bootstrap.py` 展示临时项目和子进程方式。复用这种边界，不把它作为应用运行时的新配置协议。

## 配置与模块导入

- bootstrap 前不能读取 conf.settings 或未绑定 App 的 app.settings；服务启动测试应验证真实入口完成初始化。
- 同一进程不能切换 api/web 两套服务配置。需要对比两个服务时分别启动进程，不写生产 reset 或配置代理。
- 直接绑定配置的窄单元测试必须自动恢复原值，即使断言失败也要恢复；不能把假配置挂到 app.ctx.settings。
- 真实 App/模型加载会影响 sys.modules 和 SQLAlchemy metadata。不要只清 registry 字典，就声称完整 bootstrap 状态已重置。
- 需要模拟独立项目包名、服务文件或模型归属时，子进程的 cwd 必须是临时项目根；别把临时 config 包写入框架根目录。

可以在测试中 patch 外部 I/O 以精确触发某条异常，但不能拿被 patch 掉的数据库/Redis 行为宣称跨进程或事务机制正确。对应真实集成验证应明确区分。

## 资源和失败路径

测试创建的进程要保留句柄，在 finally 中停止并等待；浏览器要关闭 profile；数据库、连接池及后台任务应正常退出。不要按进程名批量杀死用户服务。

临时目录用标准 TemporaryDirectory 或 mktemp -d，记录所有权，只清本任务自己的目录。发布工具持久证据需要显式清理，详见[维护入口](maintenance.md#集中验收分阶段串行)。

失败测试至少验证“没有发生什么”：校验错误未写库、数据库回滚保留原文件、未授权请求未读取别人的数据、动作失败未执行后续动作等。不要只断言返回一句错误消息。

修改真实 UI 必须手工操作。DOM/源码断言可辅助检查协议，但不能证明布局、弹窗尺寸、点击响应或加载失败提示确实可见。Dashboard 与 Admin 必须使用同一公共组件协议。

## 控制验证范围

一个小模块完成后只运行当前无法安全继续所需的检查。剩余全量发布检查集中、串行执行；不要为了绿灯建立重复状态、永久截图缓存或复杂测试专用生产分支。

测试预期过时先核对当前契约和真实行为，再决定修正或删除测试。不能为满足旧断言恢复已不存在的接口，也不能把内部历史文档的字句作为生产正确性门槛。

## 浏览器与进程门禁工具

真实浏览器验证、进程树清理和 PNG 证据检查是 `oldman.testing`（只用标准库，导入它不会读配置也不会起服务）：

| 入口 | 用途 |
| --- | --- |
| `ChromePage` / `CDPClient` / `navigate` / `configure_viewport` / `save_screenshot` | 用本机 Chrome 的 DevTools 协议打开页面、截图、`client.evaluate(...)` 断言 |
| `BrowserResult` | 收集 console 错误、page 错误和坏响应，和业务断言分开 |
| `find_free_port` | 给临时服务找一个空闲端口 |
| `tracked_popen` / `ProcessTreeTracker` | 起子进程并在结束时确认整棵进程树都已退出 |
| `require_png` | 确认截图确实是一张够大的 PNG，而不是 0 字节文件 |

需要一套完全自有的临时环境（不碰开发机上正在跑的服务和数据）时用 `oldman.testing.gates`：

| 入口 | 用途 |
| --- | --- |
| `minimal_environment()` | 只保留启动本机工具需要的环境变量，固定 `TZ=UTC` 与 `PYTHONHASHSEED=0` |
| `owned_redis_server(state_root, environment=...)` | 起一个不落盘的 Redis，退出时确认进程组和端口都释放了 |
| `gate_settings(example, state_root, service_port=, redis_url=, namespace=, customize=)` | 把项目的 example 配置改写成只指向临时目录的一份；`namespace` 隔离 session 前缀和 Cookie |
| `migrate_gate_database(...)` / `ensure_gate_admin(...)` | 按“首次使用”应用迁移，并用公开 API 建出门禁要的管理员 |
| `owned_service(config_file, ...)` + `wait_for_service(...)` | 前台起服务、等它监听，结束时确认整个进程组回收 |
| `run_browser_child(command, ...)` | 跑真实浏览器子进程，要求 console/page/响应错误都是空的 |

项目不要把这些脚本复制进自己的 `scripts/`：升级框架时复制品不会跟着变。演示项目的 `scripts/verify-*.py` 只保留页面自己的断言和自己的配置差异，其余从 `oldman.testing` 导入。

## 防止复制粘贴变成第二份实现

`oldman.testing.duplication` 把“这段代码别处已经有了”变成一条测试，不靠人记：

| 入口 | 找什么 |
| --- | --- |
| `duplicate_functions(left, right, min_lines=6)` | 两棵源码树里同名且函数体结构相同的函数（复制粘贴通常保留函数名，所以误报很少） |
| `identical_files(left, right, suffixes=...)` | 内容逐字节相同的文件：抄过去的脚本、模板、类型声明 |
| `forbidden_imports(root, modules=..., allowed_names=...)` | 绕过公开 API 的 import，例如从 `oldman.apps.admin` 里取与 Admin 业务无关的东西 |
| `forbidden_attributes(root, attributes=("app.ext.environment",))` | 绕过公开入口的属性访问 |

框架自己跑 Admin↔`oldman.web`/`oldman.auth`，项目跑自己的代码↔框架包。检查只读源码，不导入被检查的模块。

发现重复时的顺序是：**先判断这段能力属于谁**。属于框架就上提到框架（并写文档和测试），项目只留调用；确属项目自己的业务才留下。为了让测试变绿而把两份实现改得“看起来不一样”，是这条守卫要防的反面。
