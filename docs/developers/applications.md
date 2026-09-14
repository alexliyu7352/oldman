# 应用与生命周期

Oldman 区分两种对象：**Application 是启动一个服务的运行时；App 是被该服务安装的可复用功能包。** App 的 `apps.py` 导出的 `app` 是 AppConfig 实例，不是 Sanic 应用；视图中的 `get_app()` 取得 Sanic，不是 AppConfig。

以下实际接线取自 EPG Demo 的 [services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py) 和 [apps/examples](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/apps/examples)。公开签名表用于查接口；类内方法节选用于对照现有服务，不是完整的新服务文件。

## 公开入口

```python
from oldman import ServiceBootstrapContext, bootstrap_service
from oldman.apps import AppConfig, AppRegistry
from oldman.runtime import SimpleApplication, WebApplication
from oldman.runtime import TaskiqWorkerApplication, TaskiqSchedulerApplication
from oldman.web import Request, Response, WebApp, get_app
```

`WebApp` 是公开的 Sanic 类型名称，视图仍按 Sanic 的路由和请求语义执行。Oldman 没有要求业务另写一套 runtime adapter。

## 服务发现

框架读取项目 `services/` 直接下一层的 `.py` 文件，忽略 `__init__.py` 和下划线开头的文件。有效服务名匹配 `[a-z][a-z0-9_]*`。

发现阶段使用 Python AST 读取类的直接基类，不执行服务模块。因此还没有配置文件时，也能知道有哪些服务，并提供它们的 `settings init` 命令。

每个文件必须有且只有一个直接继承 `WebApplication`、`SimpleApplication`、`TaskiqWorkerApplication` 或 `TaskiqSchedulerApplication` 的类。使用正常基类名称，不要给基类改一个别名后让静态发现猜测它的含义，也不要用动态工厂生成服务类。加载选中服务时，还会核对真实类与静态发现结果，并拒绝抽象类。

`SERVICE_NAME` 可以改日志等场景的可读名称；命令名和默认 YAML 名称不受它影响。后者始终来自文件名。

服务模块可以导入业务已经加载的模型，但不能通过导入额外未注册模块来创建新的表。模型声明归 App 的模型阶段。

## 实际加载顺序

不同命令只加载需要的阶段，不为配置检查启动 Web：

| 入口 | 读取配置和 App 元数据 | 加载模型 | 加载 App 命令 | 创建 Sanic / 加载 views |
| --- | --- | --- | --- | --- |
| `settings init/sync/check` | 是 | 否 | 否 | 否 |
| `bootstrap_service()` / `shell` | 是 | 是 | 否 | 否 |
| `<service> --help`、一次性 App 命令 | 是 | 是 | 是 | 否 |
| `<service> start` | 是 | 是 | 是，CLI 装配时 | 仅 WebApplication |
| 项目级 `db` 命令 | 只收集迁移所需配置 | 按命令需要加载 | 否 | 否 |

`oldman --help` 是根帮助，只发现服务，不加载各服务的业务模型。`oldman web --help` 则要显示 Demo 的 web 服务安装的 App 命令，因此会加载该服务的配置和模型。配置有误时后者报错，并不与前者行为矛盾。

普通服务启动的具体顺序是：

```text
发现 services/<name>.py
→ 选择 data/<name>_settings.yaml
→ 导入 config.schemas.Settings
→ 导入 settings.apps 中每个包的 apps.py
→ 分别校验全局配置和 App 配置
→ 发布 conf.settings，绑定各 App 的 app.settings
→ 加载配置选定的 User 和所有 App 模型
→ CLI 加载 App commands，导入选中的服务类
→ 构造并启动 Application
→ WebApplication 创建 Sanic、安装启用的基础扩展
→ 导入各 App 的 views
→ 进入 Sanic 运行生命周期
```

先模型、后 views 是为了让所有模型已有统一归属，让无 Web 的命令也能使用数据库；不是重新扫描项目目录。Registry 保存显式 App 清单，并记录各阶段是否已经完成。

配置和模型加载时不应主动执行数据库、Redis 或 NATS I/O。`bootstrap_service()` 不启动服务器、后台任务、进程 Worker，也不主动连接数据库。Core 接收声明由启用 nats_bus 且 consume=true 的普通 Web/Simple 加载；真正连接/接收在后面的异步运行阶段。命令、Shell、Taskiq Worker/Scheduler 不自动加载 events。

## AppConfig

Demo 的 Examples App 将视图拆成包。下面是其与接线相关的真实目录节选，非完整文件清单：

```text
apps/examples/
├── __init__.py
├── apps.py
├── settings.py
├── commands.py
├── models.py
├── tasks.py
├── forms.py
├── tables.py
├── services.py
├── providers.py
├── views/
│   ├── __init__.py
│   ├── forms.py
│   └── tables.py
├── fixtures/
│   └── demo.json
└── migrations/
    ├── __init__.py
    └── a839bf3055f2_create_example_models.py
```

它有HTTP示例使用的settings.py、Taskiq使用的tasks.py，以及导出project-stats、协程/进程/Worker/缓存示例命令的commands.py。后者可以从同包其他模块导入具体Command类，不必把所有实现塞在一个文件中，规则见[自定义命令](cli.md#自定义-app-命令)。默认 `views` 可以是模块，也可以像这里一样是包；包通过自己的 `__init__.py` 导入具体视图，Registry 不为每个功能再扫描一次目录。没有某类功能的其他App才省略其模块，不创建空实现。

`apps.py` 必须导出唯一的公共 `AppConfig` 实例，变量名为 `app`。定义类不等于导出实例。ExamplesAppConfig 的完整定义见[用户指南](../users/settings-and-apps.md#安装-app)：label 为 `examples`，展示名为 `Dashboard Examples`，图标为 `ri-flask-line`。

| 属性 | 默认 / 约束 | 用途 |
| --- | --- | --- |
| `label` | 必填，`[a-z][a-z0-9_]*` | 稳定标识，当前 Registry 内唯一 |
| `display_name` | 必填，非空 `str` 或 `LazyTranslation` | 菜单、命令分组等展示名 |
| `icon` | `ri-database-2-line` | 单个图标 class，可用 `ri-`、`mdi-`、`bx-`、`bxs-`、`bxl-` 前缀 |
| `settings_model` | `None` | 可选的 Pydantic `BaseModel` 子类 |
| `models_module` | `"models"` | 相对 App 包的模型模块 |
| `migrations_module` | `"migrations"` | 相对 App 包的迁移模块 |
| `web_module` | `"views"` | 相对 App 包的 Web 模块 |
| `commands_module` | `"commands"` | 相对 App 包的命令模块 |
| `tasks_module` | `"tasks"` | Worker/Scheduler 加载的任务模块；模型阶段之后 |
| `events_module` | `"events"` | 启用 Core 接收的 Web/Simple 加载的 handler 声明；模型阶段之后 |

模块路径必须是非空的相对 Python 模块路径，不能设置为 `None`。默认目录没有对应模块时，模型、视图或命令加载可正常跳过；模块存在但内部 import 失败时保留真正的异常，不伪装成“没有这个模块”。如果覆盖为嵌套模块，其父包需要实际存在。

有专用设置时，可参考 Demo 的 `ExamplesAppConfig(AppConfig[ExamplesSettings])`，其 settings_model 指向 ExamplesSettings，配置 HTTP 示例的上游地址；也可参考它使用的内置 AdminAppConfig。泛型参数决定 app.settings 的静态类型，settings_model 决定运行时如何创建配置，两处应该指向同一类。完整声明与读取路径见 [App Settings](configuration.md#app-settings)和[HTTP 示例](http-client.md#demo-中的实际使用)。

包路径已经由 `settings.apps` 提供，不另填一个 `name`。AppConfig 不提供 `ready()` 钩子或自动补装依赖的声明系统。需要其他 App 时，在服务配置中明确安装，并按它的接口接线。

App 包根、`apps.py` 和配置模型模块应保持轻量：不读取尚未绑定的 `app.settings`，不导入 views，不声明或提前导入数据表，不连接外部服务。

### 配置访问异常

以下异常可从 `oldman.apps` 导入：

| 异常 | 原因 | 处理 |
| --- | --- | --- |
| `AppNotInstalledError` | 当前服务没有安装这个 App | 检查当前 YAML 的包路径列表 |
| `AppSettingsNotDefinedError` | App 没有声明配置模型，却读取 `app.settings` | 定义必要配置，或不要读取不存在的设置 |
| `AppSettingsNotReadyError` | 配置绑定尚未完成就读取 | 移出元数据导入阶段，或先完成 bootstrap |

不要捕获这些异常后悄悄返回默认配置；这样会把漏安装和初始化顺序错误变成更难发现的业务错误。

## AppRegistry

通常不用手工创建 Registry。服务 bootstrap 创建它，调试时从 `context.apps` 取得。

| 属性 / 方法 | 返回或行为 |
| --- | --- |
| `packages`、`labels` | 保留配置顺序的 tuple |
| `configs` / 遍历 Registry | 已安装的 AppConfig |
| `get_by_package(package)`、`get_by_label(label)` | 指定 App；未安装抛 `AppNotInstalledError` |
| `models` | 模型阶段完成后的 `ModelMetadata` tuple |
| `get_model_metadata(model)` | 模型对应的 Table、App label、展示名与 managed 状态 |
| `commands`、`get_command(name)`、`get_app_commands(label)` | 命令阶段完成后查询已发现命令 |

调用 `models` 或 `commands` 前对应阶段必须完成。`register_packages()`、`bind_settings()`、`load_models()`、`load_commands()`、`load_views()`、`load_tasks()`、`load_events()` 是配置与运行时使用的阶段接口；应用不应建立第二个 Registry 与框架并行注册。每个加载阶段完成后重复调用不会重复导入，模型阶段开始后不能再追加 App。events 与 tasks 一样不能在加载时声明新的数据库表，也不应执行网络 I/O。

所有模型共用 `Base.metadata`。Registry 根据已注册 App 的定义模块记录归属，关联表也需要处于相应模型模块中。`oldman_user` 的选定模型由 Auth 配置决定，不在每个 App 中创建一个具体 User。

## WebApplication

Demo 的服务类是 `WebService(WebApplication)`；文件名为 `web.py`，所以命令为 `./run.sh web start`。它实现的 `prepare_server()` 完整方法如下：

```python
def prepare_server(self, app: WebApp) -> None:
    """按照项目配置准备 Sanic 监听参数。"""
    ensure_vite_build_available()
    app.prepare(
        host=settings.web.listen_host,
        port=settings.web.listen_port,
        debug=settings.web.debug,
        motd=False,
        auto_reload=settings.web.auto_reload,
        single_process=True,
        workers=settings.web.workers,
        access_log=settings.web.access_log,
    )
```

方法属于类内部，不能只复制为模块函数。原文件已从 `config.settings` 导入全局 `settings`，从 `oldman.web.routing` 导入 `WebApp`。同文件 `ensure_vite_build_available()` 根据产品/开发模式检查资源：产品模式需要已构建、收集的 manifest；开发模式使用 Vite 地址。资源准备流程见[Assets](assets.md)，不是让 `prepare_server()` 隐式运行构建。

这里调用原生 `app.prepare(...)`，Demo 明确传 `single_process=True`。需要多个 worker 时，必须同时按 Sanic 的参数约束调整这里，不能只把 YAML 的 `workers` 改大就假定切换完成。

### 模板和基础能力接线

Demo 的 `get_ext_config()` 为 Sanic-Ext 提供配置，完整方法如下；原文件还从 `typing` 导入了 `Any`：

```python
def get_ext_config(self) -> dict[str, Any]:
    """返回 Sanic-Ext 配置。"""
    return {
        "oas": False,
        "oas_autodoc": False,
        "templating_path_to_templates": settings.web.template.dir,
        "templating_enable_async": True,
        "logging": False,
        "cors": True,
    }
```

模板目录来自同一个全局 Settings，异步模板显式启用，日志仍交给 Oldman，不让 Sanic-Ext 再安装一套日志系统。

接着，Demo 的 `init()` 在基类初始化之后补充自己的 CSRF、通知路由和模板助手：

```python
def init(self) -> None:
    """初始化 Sanic、Session、CSRF 与模板辅助函数。"""
    super().init()
    app = self.runtime_app
    if app is None:
        raise RuntimeError("Sanic app was not initialized")

    StatelessCSRFManager(app)
    notification_routes = install_notifications(app)
    install_template_helpers(
        app,
        notification_routes=notification_routes,
        user_events_url="/user-events" if settings.web.sse.enabled else None,
    )
```

这里的名称来自同一服务文件：

- `StatelessCSRFManager` 从 `oldman.web.security.csrf` 导入。
- `install_notifications` 是 `oldman.web.messages.notifications.init_app` 的导入名称，不是另一个 subscriber。
- `install_template_helpers()` 是 Demo 自己的函数：安装共享/项目模板 loader、静态 bundle、语言菜单、CSRF 和通知链接等模板 globals。完整实现仍在服务文件中，不能把它当成框架自动存在的方法。
- `/user-events` 是 Demo 已声明的 SSE 视图地址；这里只将地址交给模板，不创建这条路由。SSE 关闭时传 None。

父类 `init()` 创建 Sanic 和扩展环境，按开关安装 messages、Session，初始化 Storage 与 SSE 输出扩展，再让 Registry 加载 models/views。模型阶段在 bootstrap 已完成，再调用不会重复加载。Demo 的上述覆盖随后才安装自己的附加能力；最终开始处理请求时，这些接线都已完成。不能在 `apps.py`、models 或 views 的导入阶段就假定项目的模板 globals/CSRF 助手已经可用。

项目自己的请求/响应中间件也在这个 `init()` 覆盖里注册，签名、短路规则和与基类中间件的先后顺序见[自定义中间件](web.md#自定义中间件)。

下面的扩展点表是框架接口参考；Demo 并没有覆盖表中每一个方法。

可按需覆盖：

| 方法 | 时机 / 要求 |
| --- | --- |
| `get_ext_config()` | 返回 Sanic-Ext 配置 mapping，默认 `None`；需要模板时启用异步模板环境，`logging` 保持 false |
| `get_extension()` | 提供 Sanic-Ext 扩展集合；默认包含 injection、OpenAPI、HTTP、health 和 templating 扩展 |
| `get_runtime_config()` | 可选的低层 Sanic 配置覆盖；常规设置优先用 `settings.web` |
| `init()` | 创建 Sanic、配置基础扩展并加载 views；覆盖时先调用 `super().init()` |
| `async main_process_ready(app)` | Sanic 主进程 ready 后 |
| `async before_server_start(app)` | worker 启动前；基类在这里初始化 Web i18n |
| `async after_server_start(app)` | worker 已启动后 |
| `async before_server_stop(app)` | 停止前；基类取消已登记后台任务 |
| `async after_server_stop(app)` | 停止后、循环仍可执行异步清理时；基类关闭其缓存及 Redis 资源 |

监听方法只接收 `app`，不增加 `loop` 参数。覆盖已有生命周期时保留需要的 `super()` 调用。需要事件循环的资源放在异步生命周期里，不放到 import 或构造函数中。

启用 nats_bus 后，框架在**实际 Sanic worker** 中先打开 Core，再打开启用的 Taskiq 发布连接，随后执行用户 before_server_start；用户 after_server_start 完成后才开始 Core 接收。停止先结束接收、等待 handler 的 finally，再调用用户 before_server_stop/after_server_stop，最后关闭 Taskiq 与 Core。业务钩子失败也会清理通信连接。主进程只加载声明，不提前创建跨进程共享 Client；不要在子类钩子里重复 start/stop bus。完整预算、异常与独立资源责任见 [NATS 生命周期](providers.md#app-与运行生命周期)。

`runtime_app` 在初始化前是 `None`，初始化后是 Sanic 实例。仅有 AppConfig 注册不意味着某个内置应用已经完成全部路由安装；例如 `install_admin(...)` 是额外的 Admin 接线步骤，不要把包列表当作其替代。

自建连接池或 Client 由服务负责关闭。不要假定基类会自动发现并关闭任意业务资源。关闭数据库的实际例子见教程；请求内 Session 则使用上下文管理器关闭，不逐请求销毁共享连接池。

## SimpleApplication

以下是普通 SimpleApplication 的接口参考，来源于 [oldman/runtime/simple.py](../../oldman/runtime/simple.py)。真实例子是 Demo 的 services/nats_a.py、nats_b.py：两个独立 Core 接收服务，见[通信教程](../users/service-communication.md)。它们使用同一个接收 App，不复制 broker 或采集调度循环。

它不创建 Sanic，也不加载 App 的 views。必须实现：

```python
def prepare(self) -> None:
    ...

async def main(self, *args, **kwargs) -> None:
    ...
```

正常运行顺序为 init/模型、按开关加载 events 声明、同步 prepare；事件循环中先打开启用的 Core/Taskiq 发送连接，再执行 before_start，开始 Core 接收，然后 main。main 返回或收到停止信号后，先结束 Core handler，再执行 before_stop/after_stop，最后关闭 Taskiq 与 Core。main 返回服务即结束；Demo 的 main 使用 await asyncio.Event().wait() 等正常停止，不是空 main 自动成为 Worker。

`before_start()`、`before_stop()`、`after_stop()` 是异步扩展点。基类停止流程会取消通过其接口登记的后台任务，关闭已有缓存和 Redis；业务创建的其他资源仍需要自身的清理。

例如 nats_a 的 after_stop 先 await db_manager.close()，再在 finally 调用 super；此时接收 handler 已退出。业务停止钩子中仍可用 Core 发送给其他在线服务，不能再期待本地已停止的订阅回复。信号取消的是受管主协程，不先 loop.stop 抢断异步清理；等待仍是协作式取消，不保证无界阻塞业务的硬退出期限。

App 命令不执行 `main()` 或启动后台服务，而是走[命令生命周期](cli.md#命令生命周期)。不要把命令依赖的初始化全部放进 `prepare()` 后，又假定一次性命令也会调用它。

## Taskiq 专用服务

Demo 已有 task_worker 和 task_scheduler。前者继承 TaskiqWorkerApplication，以原生 ProcessManager 管执行子进程；后者继承 SimpleApplication 的 TaskiqSchedulerApplication，只运行原生调度器。它们不加载 Web views，模型之后才自动加载已安装 App 的 tasks。普通 Web/Simple/命令只管理启用后的发布连接，不自动加载所有 tasks。精确顺序、Shell 显式连接和资源归属见[Taskiq 运行时](distributed-tasks.md#app-与服务加载)。

## Python Shell 与 IDE

以 EPG Demo 为例，在其项目根目录运行：

```sh
./run.sh web shell
```

Shell 已提供 `context`、`settings` 和 `apps`，可以直接导入本服务模型。它不会创建 Sanic、加载 views 或启动业务后台任务。

IDE 的 Python Shell 使用同一公开入口。下面是交互操作说明，引用 Demo 已有的配置与模型，不是 Demo 中另一个脚本文件；先将工作目录及导入路径设为应用项目根目录：

```python
from oldman import bootstrap_service

context = bootstrap_service("web")

from config.settings import settings
from apps.examples.models import ExampleProject

assert context.service_module == "web"
```

公开签名：

```python
def bootstrap_service(
    service_module: str,
    *,
    config_file: str | Path | None = None,
) -> ServiceBootstrapContext:
    ...
```

返回的冻结 dataclass 包含 `service_module`、解析后的 `config_file: Path`、`settings`、`apps`。冻结的是上下文容器，并不意味着里面的 Pydantic 配置被深度冻结。

同一服务和同一解析后路径重复调用返回已有上下文；不能通过重复调用让磁盘配置热加载。换服务或换配置文件会报错，需新开进程。测试也应使用隔离进程或测试专用 fixture，而不是增加生产 reset。

不依赖配置的纯函数仍可在普通 Python Shell 直接导入。需要执行数据库异步操作时，在本次调试的事件循环中完成操作并关闭使用过的连接；bootstrap 本身不是数据库连接入口。
