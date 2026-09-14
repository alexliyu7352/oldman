# 配置参考

Oldman 使用项目唯一的 Settings 类型校验各服务 YAML。全局配置和 App 配置保存在同一文件，但发布为不同的强类型对象。

## 根 Settings

EPG Demo 的 [config/schemas.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/config/schemas.py) 定义项目唯一根类。下面是完整类定义节选，不是独立文件；`Field` 来自 Pydantic，配置类型来自 `oldman.conf.schemas`，默认函数在同文件上方：

```python
class Settings(DefaultSettings):
    """Project settings schema."""

    database: DatabaseConfig = Field(default_factory=default_database_config, description="Database settings")
    i18n: I18nConfig = Field(default_factory=I18nConfig, description="Internationalization settings")
    web: WebConfig = Field(default_factory=default_web_config, description="Web service settings")
    storages: StoragesConfig = Field(default_factory=default_storages_config, description="Named file storage settings")
```

四项配置的默认函数分别负责项目数据库路径、模板/静态目录与 Session、默认文件存储；i18n 直接使用 `I18nConfig`。例如下面这两个连续函数说明 Web 组如何组合，而不是在业务代码里逐处拼配置：

```python
def default_session_config() -> SessionConfig:
    """Return the Redis Session contract used by the Dashboard service."""
    return SessionConfig(
        enabled=True,
        expiry=86400,
        prefix="oldman_session:",
        user_prefix="oldman_user_session:",
        cookie_name="oldman_session_id",
    )


def default_web_config() -> WebConfig:
    """Assemble the Dashboard's browser-facing service settings."""
    return WebConfig(
        session=default_session_config(),
        template=default_template_config(),
        static=default_static_config(),
        frontend=FrontendConfig(),
    )
```

文件中的 `BASE_DIR = Path(__file__).resolve().parents[1]` 用于生成项目路径。上面引用的 `default_template_config()`、`default_static_config()` 也在同文件；复制默认函数时应保留这些依赖。示例 YAML 还显式配置 messages、SSE 等值，见[Demo 的配置和开关](../users/settings-and-apps.md#web-相关开关)，不能只看这个默认函数就推断最终配置。

Demo 的 [config/settings.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/config/settings.py) 只给已初始化对象补上项目类型，以下是其导入和绑定部分：

```python
from typing import cast

import oldman.conf as conf
from config.schemas import Settings

settings = cast(Settings, conf.settings)
```

业务通过 `from config.settings import settings` 读取。`cast()` 不新建实例、不加载文件、不改变运行时值。

框架级通用代码可以从 `oldman.conf` 读取 `settings`，但看到的静态类型是 `DefaultSettings`。项目新增字段使用项目自己的导入入口。

Web 服务也使用这同一个实例，不需要将配置再挂到 `app.ctx.settings`。Admin 静态资源、语言菜单、登录有效期、语言偏好 Cookie 和 CSRF 都读取全局配置；`app.ctx` 只保存这些功能实际安装的运行时对象，不提供另一套配置来源。

初始化前读取 `conf.settings` 会抛 `RuntimeError`；它不是一个任意阶段都可用的默认对象或 lazy proxy。正常 CLI 会先 bootstrap 后导入业务，IDE 使用[公开 bootstrap](applications.md#python-shell-与-ide)。

根模型的值来源是 YAML 和模型默认值，不叠加 `.env`、环境变量或 secrets 目录作为业务配置来源。这里不限制 CLI 语言、运行工具等独立用途的环境参数。

## 配置文件选择

在 EPG Demo 根目录运行 `./run.sh web start` 读取 `data/web_settings.yaml`，服务来自 `services/web.py`。其他服务同样按文件名得到 `data/<name>_settings.yaml`，文件名允许下划线；数据目录配置 `core.data_dir` 不会反过来改变这个启动文件名。

以下是 CLI 工具的路径选项用法，不是 Demo 已附带另一份 debug 配置。`data/web_debug.yaml` 是用户自行选择的替代文件；对它先 `init`，之后才能 `check/sync` 或打开 Shell。当前 CLI 的 `--config PATH` 仅出现在以下工具入口：

```sh
./run.sh web settings init --config data/web_debug.yaml
./run.sh web settings sync --config data/web_debug.yaml
./run.sh web settings check --config data/web_debug.yaml
./run.sh web shell --config data/web_debug.yaml
./run.sh web static collect --config data/web_debug.yaml
```

它不是全局选项，`web start` 不读取上一次 `settings --config` 的结果，也不能写成 `oldman --config ... web start`。Python 的 `bootstrap_service(..., config_file=...)` 则可显式选择文件。

相对路径按当前工作目录解析；项目 `run.sh` 先切回项目根，所以本文都使用 `data/...`。当前实现接受显式路径，不自动复制到 `data`，也不把它登记成服务默认配置。正式服务配置应统一放 `data`；项目级 `db` 命令只读取真实服务对应的默认 YAML，不收集这些临时替代文件。

项目根目录优先使用有效的 `PROJECT_ROOT`，否则按工作目录等已知起点向上查找 `pyproject.toml`、`setup.cfg`、`setup.py` 或 `.git`。普通项目通过根目录或 `run.sh` 执行即可，不需要设置这个环境变量。

## YAML 的两个配置空间

下面取自 Demo 的 [web_settings.example.yaml](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/web_settings.example.yaml)，保留完整 App 清单和对应设置；其他根配置未在此重复：

```yaml
apps:
  - oldman.auth
  - oldman.apps.admin
  - oldman.web.messages.notifications
  - apps.auth
  - apps.dashboard
  - apps.epg_admin
  - apps.examples
  - apps.web
app_settings:
  auth:
    user_model: apps.auth.models.OldmanUser
  admin:
    require_superuser: false
  examples:
    http_base_url: https://httpbin.org
```

- `apps`、`database`、`web` 等进入根 Settings。
- `app_settings.auth` 使用 AuthSettings 校验，`app_settings.admin` 使用 AdminSettings 校验，`app_settings.examples` 使用Demo的ExamplesSettings校验，各自绑定到对应 App。
- `apps.auth` 是 Demo 的 Python 包，label 为 `epg_auth`；`app_settings.auth` 属于框架包 `oldman.auth`。前者提供具体 User，后者选择它。
- 根 Settings 没有 `app_settings` 字段，也不提供按 App 查询的代理方法。

根未知字段报错。内置子配置的未知字段处理遵循各自模型定义；不要把一次 `check` 当成所有业务关系和拼写的万能检查器。

## App Settings

配置模型必须继承 `pydantic.BaseModel`。推荐写上 `ConfigDict(extra="forbid")`，并为可配置范围使用 `Field` 的类型和约束。没有专用的 `AppSettings` 基类要求。

Demo 已安装的 Admin App 提供下面这个配置类。以下取自框架 [oldman/apps/admin/settings.py](../../oldman/apps/admin/settings.py)，包含导入和完整类，不是要在 Demo 创建同名文件：

```python
"""Strongly typed settings owned by the Admin application."""

from pydantic import BaseModel, ConfigDict, Field


class AdminSettings(BaseModel):
    """Configure access policy specific to the built-in Admin UI."""

    model_config = ConfigDict(extra="forbid")

    require_superuser: bool = Field(
        default=False,
        description="Require superuser access to Admin",
    )
```

注册使用框架 [oldman/apps/admin/apps.py](../../oldman/apps/admin/apps.py)，下面同样保留导入、类和实例：

```python
"""Installable Admin application metadata."""

from oldman.apps import AppConfig
from oldman.apps.admin.settings import AdminSettings
from oldman.i18n import gettext_lazy as _


class AdminAppConfig(AppConfig[AdminSettings]):
    """Describe the built-in Admin application and its settings owner."""

    label = "admin"
    display_name = _("Administration")
    icon = "ri-admin-line"
    settings_model = AdminSettings


app = AdminAppConfig()
```

`AppConfig[AdminSettings]` 决定 `app.settings` 的静态类型，`settings_model = AdminSettings` 决定运行时创建的类型。自定义 App 沿用这个接口，用自己的类和 label；不需要改根 Settings。

Demo 的登录服务实际读取 `admin_app.settings.require_superuser`，完整消费者和初始化要求见[用户指南](../users/settings-and-apps.md#app-自己的配置)。Demo 的 Examples App 另有实际使用的 ExamplesSettings，通过同样的泛型和 settings_model 绑定 http_base_url，由 run_http_example 在运行时读取。它对应可配置的 HTTP 上游需求，不是为了统一形式新增的空模型；无配置需求的 App 仍可不声明设置模型。

绑定规则：

1. 只加载 `settings.apps` 显式安装的 App。
2. 用各 App 的 `settings_model` 校验 `app_settings.<label>`。
3. 未提供部分字段则用默认；缺少必填字段则报错。
4. 未安装 App 的配置、没有配置模型却配置了该 App、未知的 App 配置字段均报错。
5. 正常 bootstrap 完成校验后绑定实例；`settings check/sync` 不发布可供业务运行的 App Settings。

不要在模块级缓存 `app.settings` 中的业务值后，又假定该模块可以在配置尚未初始化时导入。Demo 将策略读取放在 `authenticate_user()` 内；调用前通过服务入口完成初始化。

## SettingsManager

普通项目使用 CLI 或 `bootstrap_service()`。需要编写配置工具时，可以从 `oldman.conf` 导入 `SettingsManager`：

```python
SettingsManager(
    settings_class,
    service_definition,
    config_file,
    deprecated_keys=None,
)
```

上面是构造接口说明，不是 Demo 的调用代码；`deprecated_keys` 为仅关键字参数。它需要真实的 `ServiceDefinition`，不是单独一个 Settings 类即可替代全部启动逻辑。不要手工造 manager 并与已运行的服务共享或切换 Registry。

| 方法 | 行为 |
| --- | --- |
| `read_config()` | 读取当前 YAML mapping，不写入 |
| `load()` | 验证配置并绑定 App Settings，返回根实例；全局发布仍由统一 bootstrap 负责 |
| `check_config()` | 验证并返回根实例，不写文件、不发布运行时 App Settings |
| `init_config()` | 仅在文件缺失时创建，以同名 `.example.yaml` 为可选初值 |
| `sync_config()` | 保留已有值和注释，补齐当前模型中的缺失字段 |
| `write_config(data)` | 验证传入数据后显式写入，必要时生成 Web 密钥 |
| `diagnostics` | 最近一次成功验证中的非致命建议 tuple |

EPG 第一次初始化时使用同目录的 `web_settings.example.yaml`，所以初始 App 清单有明确来源；没有同名示例时不会扫描 App 目录补装。已有 YAML 则使用 `sync`，不执行 `init` 覆盖它。

同一个 manager 不支持更换 App 清单或给已经绑定的 App 重新绑定另一套实例。配置工具应在独立进程运行。

`init/sync/write` 写入时附带字段描述，新增文件的权限为 0600；已经存在的文件不会因为写入自动收紧原权限。部署时检查文件权限，不要将真实密钥提交版本库。

## 根配置分组

这些分组的 Pydantic 类型定义在 `oldman.conf.schemas`。具体服务的完整字段可通过 `settings sync` 在 YAML 中生成带注释的版本。

| 节点 | 类型 | 主要用途 |
| --- | --- | --- |
| `apps` | `tuple[str, ...]`，YAML 写列表 | 当前服务安装的 App 包路径 |
| `core` | `CoreConfig` | 名称、数据目录、时区 |
| `logging` | `LoggingConfig` | 等级、日志目录、控制台颜色策略 |
| `process` | `ProcessConfig` | PID 目录 |
| `web` | `WebConfig` | Web 监听、会话、SSE、模板、静态和安全 |
| `i18n` | `I18nConfig` | Web 翻译、语言列表与默认语言 |
| `database` | `DatabaseConfig` | 异步 SQLAlchemy URL 和查询日志 |
| `redis` | `RedisConfig` | 大小写敏感的连接别名 mapping |
| `nats` | `NATSConfig` | 命名 NATS URL、认证及 TLS 参数 |
| `nats_bus` | `NATSBusConfig` | Core 事件/RPC 开关、接收、namespace、peer、codec 和启停等待 |
| `taskiq` | `TaskiqConfig` | 分布式任务开关、namespace、连接别名、并发及调度/关闭预算 |
| `cache` | `RedisCacheConfig` | 缓存使用的 Redis 别名、namespace 和序列化器 |
| `http_client` | `HttpClientConfig` | 出站连接池和 User-Agent 默认值 |
| `storages` | `StoragesConfig` | 命名文件存储后端及 options |
| `proxy` | `ProxyConfig` | 代理连接和读取超时等设置 |

Auth 的 `user_model` 从 `oldman.auth.apps.app.settings` 读取；Admin 的 `require_superuser` 从 `oldman.apps.admin.apps.app.settings` 读取。它们保存为 `app_settings.auth`、`app_settings.admin`，不属于根设置。

### 常用非 Web 默认值

| 字段 | 默认 |
| --- | --- |
| `core.app_name` | `oldman` |
| `core.data_dir` | 项目根下 `data` |
| `core.time_zone` | `Asia/Singapore` |
| `logging.level` | `logging.INFO`，也接受等级名如 `INFO` |
| `logging.dir` | 项目根下 `logs` |
| `logging.color` | `auto`，可选 `always`、`never` |
| `process.pid_dir` | 项目根下 `pids` |
| `database.url` | `None`，用数据库前必须配置 |
| `database.echo` | `None`，数据库管理器可使用 Web debug 作为回退 |
| `database.enable_sql_logging` | `False` |
| `i18n.use_i18n`、`use_i18n_path` | `False` |
| `i18n.default_language` | `en` |
| `cache.client` / `namespace` / `serializer` | `CACHE` / `main` / `pickle` |
| `http_client.max_connections` | `300` |

Redis 内置 `DEFAULT`、`CACHE`、`SESSION` 别名；可添加其他别名，如 `SSE`。自定义别名必须提供真实 `redis_url`，不要假定它自动存在。开启依赖该别名的能力前，核对生成配置中的 URL、数据库编号和 `decode_responses`。

NATS 默认 DEFAULT 指向 nats://localhost:4222；Taskiq 默认关闭，启用时必须配置 namespace 和实际存在的 NATS/Redis alias。非 Web 服务不自动生成 web，但仍生成这些根配置。全部 Taskiq 默认值、安全参数转换和生命周期见[分布式任务配置](distributed-tasks.md#配置与默认值)。

Core 事件/RPC 另由根 nats_bus 控制：enabled/consume 默认 false，nats_alias 默认 DEFAULT，启用时必须提供 namespace。它与 Taskiq 可以引用同一命名地址，但不共用连接/协议；全部默认值、peer_id、codec 和启动/停止预算见 [NATS 配置](providers.md#配置与默认值)。配置 init/sync/check 不连接 NATS，也不读取证书文件。

显式配置 `storages` 时必须包含 `default`，每个后端使用真实的类导入路径及其 options。不在模型导入阶段创建后端连接。

## Web 默认值与开关

| 字段 | 默认 |
| --- | --- |
| `web.listen_host` / `listen_port` | `::` / `17998` |
| `web.debug` / `auto_reload` | `False` / `False` |
| `web.workers` / `access_log` | `1` / `False` |
| `web.response_timeout` / `request_timeout` / `keep_alive_timeout` | 都是 120 秒 |
| `web.real_ip_header` | `X-Real-IP`；Sanic 直接采用该头的值作为 `request.client_ip` |
| `web.proxies_count` / `forwarded_secret` | 都未设置；设置后 Sanic 才解析 `X-Forwarded-For` 或 RFC 7239 `Forwarded`，见[客户端地址与代理](web.md#客户端地址与代理) |
| `web.fallback_error_format` | `auto`，也可设 `html`、`json`、`text` |
| `web.websocket_max_size` | `1048576` 字节 |
| `web.websocket_ping_interval` / `websocket_ping_timeout` | 5 / 20 秒 |
| `web.domain` | `http://localhost:17998` |
| `web.template.dir` | 项目根下 `templates` |
| `web.static.dir` / `root` | 项目根下 `static` |
| `web.static.url` | `/static/` |
| `web.media.storage` / `url` | `default` / `/media/` |
| `web.frontend.vite_dev_server_url` | `http://localhost:5173` |

这些字段由 Web 运行时或具体服务消费。`prepare_server()` 仍决定传给 Sanic 的 worker 参数组合；模板设置也仍需要服务启用模板环境。配置不是绕过运行时接线的全自动安装清单。

设置真实 IP header 不表示所有请求都可信。生产反向代理应覆盖该 header，并限制直接绕过代理访问服务的路径。

### Web 安全配置

`web.security.secret_key` 默认空，在 Web 服务 `init/sync/write` 时生成并持久化。`fingerprint.aes_secret_key` 同样生成并持久化，采用 Base64 编码的 32 字节密钥。已有非空密钥不自动轮换。

`settings check` 或服务加载发现必需密钥仍为空，会要求先同步配置。不要在 worker 启动时各生成一份临时秘密，否则签名和验证不能稳定协作。

其他安全字段包括：

- `web.security.token_expire_time`：通用 Web token 有效期，默认 86400 秒。
- `web.security.csrf.ttl`：默认 3600 秒；`check_referer` 默认 true，`check_url` 默认 false。
- `web.security.fingerprint`：浏览器指纹时间差、频率限制与异常策略。

安全 token 和 Session 的有效期是不同设置，不能用其中一个代替另一个。

### Session、messages 与 SSE

| 配置 | 默认与含义 |
| --- | --- |
| `web.session.enabled` | false；启用才安装会话中间件 |
| `web.session.redis_alias` | `SESSION` |
| `web.session.expiry` | 2592000 秒，30 天 |
| `web.session.cookie_name` | `session_id` |
| `web.session.cookie_httponly` / `cookie_secure` / `cookie_samesite` | true / false / `Lax`；HTTPS 部署应调整 Secure |
| `web.messages.enabled` | false；控制 Cookie 一次性页面提示 |
| `web.sse.enabled` | false；控制 Redis 支持的分布式 SSE |
| `web.sse.redis_alias` | `SSE`，需显式配置此别名或改用合适的已有别名 |
| `web.sse.channel_prefix` | 默认空；启用分布式 SSE 时必须显式填写非空前缀，隔离项目和环境 |
| `web.sse.heartbeat_interval` | 15 秒 |
| `web.sse.session_check_interval` | 30 秒 |
| `web.sse.queue_size` | 100 |
| `web.sse.max_message_size` | 65536 字节 |

Web 配置校验会检查开启 Session 或分布式 SSE 时引用的 Redis 别名是否存在，但不会在 `settings check` 中连接 Redis。Cookie messages 不需要 Redis。

Web 服务安装 Admin，且原始配置没有 `web.messages.enabled` 时，`init/sync` 将它补为 true；用户显式 false 不被覆盖。运行时单纯读取缺省 YAML 不会执行这一写入默认的操作，也不会连带打开其他模块。

SimpleApplication 不自动补全或生成 `web` 节点，不执行上述 Web 专用密钥和 Redis 别名关系检查。显式提供的 Web 配置仍按字段类型解析；这不等于安装浏览器中间件。其他根配置和已安装 App 配置仍正常生成。

## 配置变更的操作边界

修改配置模型或安装 App 后，先执行目标服务的 `settings sync/check`，检查 YAML，再重启服务。

不要在请求里修改全局 Settings 来切换租户、语言或服务；请求级状态有自己的对象。不要在生产提供任意 reset；不同配置需要独立进程。

配置验证只说明数据符合当前模型及明确校验关系。数据库能否连接、表是否已迁移、Redis 是否可用、静态资源是否已构建，需要在对应操作阶段验证，不能把 `Settings OK` 当成完整部署验收。
