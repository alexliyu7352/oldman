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

`settings init/sync/write` 整体替换文件：先在旁边写临时文件再改名，中途失败只会留下旧文件或新文件，不会是写了一半的文件。配置文件是符号链接时（几个服务链接到同一份配置），写入顺着链接落到真实文件，链接保留；被替换的文件属主变成执行命令的用户。

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

根未知字段报错。内置子配置不认识的字段不报错、也不生效，`settings check` 和服务启动时逐层把它们列为提示（`unknown settings key 'web.sesion'`），拼错的键就是这样发现的。`redis` 下的连接别名由使用者命名，不在检查之列；App Settings 的未知字段按上文直接报错。`check` 只看键名和取值，不检查业务关系。

## App Settings

配置模型必须继承 `pydantic.BaseModel`。推荐写上 `ConfigDict(extra="forbid")`，并为可配置范围使用 `Field` 的类型和约束。没有专用的 `AppSettings` 基类要求。

Demo 已安装的 Admin App 提供下面这个配置类。以下是框架 [oldman/apps/admin/settings.py](https://github.com/alexliyu7352/oldman/blob/main/oldman/apps/admin/settings.py) 里这个类的字段部分，不是要在 Demo 创建同名文件：

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
    prefix: str = Field(
        default="/admin",
        description="URL path the Admin is mounted under; its own pages (login, sign-out, session) sit beneath it",
    )
```

完整文件另有 `prefix` 的校验器：去掉末尾的斜杠；根路径 `/` 和不是站内路径的值（带域名、查询串、`#` 片段，或以 `//` 开头）在加载配置时报错。

注册使用框架 [oldman/apps/admin/apps.py](https://github.com/alexliyu7352/oldman/blob/main/oldman/apps/admin/apps.py)，下面同样保留导入、类和实例：

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
)
```

上面是构造接口说明，不是 Demo 的调用代码。它需要真实的 `ServiceDefinition`，不是单独一个 Settings 类即可替代全部启动逻辑。不要手工造 manager 并与已运行的服务共享或切换 Registry。

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
| `cache` | `RedisCacheConfig` | 缓存使用的 Redis 别名和序列化器；键前缀固定是 `<core.namespace>:cache` |
| `http_client` | `HttpClientConfig` | 出站连接池和 User-Agent 默认值 |
| `storages` | `StoragesConfig` | 命名文件存储后端及 options |
| `mail` | `MailConfig` | 外发邮件后端、默认发件人、管理员收件人和 SMTP 参数 |
| `proxy` | `ProxyConfig` | 代理连接和读取超时等设置 |

Auth 的 `user_model` 和找回密码的 `password_reset`（`expiry` 24 小时、`ip_limit`/`ip_window` 5 次每 15 分钟、`email_limit`/`email_window` 3 封每小时）从 `oldman.auth.apps.app.settings` 读取；Admin 的 `require_superuser` 与挂载路径 `prefix`（默认 `/admin`）从 `oldman.apps.admin.apps.app.settings` 读取。它们保存为 `app_settings.auth`、`app_settings.admin`，不属于根设置。

### 常用非 Web 默认值

| 字段 | 默认 |
| --- | --- |
| `core.app_name` | `oldman` |
| `core.namespace` | 未设置时等于 `core.app_name`。本服务所有 Redis 键和频道的第一段（session、令牌撤销、缓存、限流、SSE 频道、锁……）。共用 session、令牌或缓存的相关服务（例如前台网站和后台 dashboard）设成相同的值；需要独立的服务设成自己的值，互不干扰。都没设这一项的几个服务，只有 `app_name` 相同才共用：`app_name` 不同时，在一个服务上改密码结束不了另一个服务的 session 和令牌，另一个服务的缓存也不会失效。不能含冒号或空白；未设置时这条规则同样适用于 `core.app_name`，不符合时启动报错，提示设置 `core.namespace` |
| `core.data_dir` | 项目根下 `data` |
| `core.time_zone` | `Asia/Singapore` |
| `core.debug` | `False`。所有服务共用的调试开关：Web 服务把它交给 Sanic（调试模式、错误页显示详情）；`logging.level` 未设置时打开它就是 DEBUG 日志；`database.echo` 未设置时 SQL 日志跟随它；流代理出错时打完整堆栈 |
| `core.id_alphabet` | 未设置。公开 id（`oldman.utils.hash_ids` 的 `encode_id` / `decode_id`）用的字母表，每个部署一张：**只有 Web 服务**在 `init/sync/write` 时自动生成，同一项目里其他要编码或解码 id 的服务（如 Worker）复制同一个值——各自生成会让它们编出的 id 在 Web 里解错。未设置时 `encode_id` / `decode_id` 报错并说明如何补上。已有值不自动轮换，换字母表会让已经发出去的 id 全部失效 |
| `logging.level` | 未设置：`core.debug` 打开时为 DEBUG，否则 INFO。写了就以写的为准，也接受等级名如 `INFO` |
| `logging.dir` | 项目根下 `logs` |
| `logging.color` | `auto`，可选 `always`、`never` |
| `logging.rotate_when` | `D`(按天);可选 `S`/`M`/`H`/`W0`–`W6`/`midnight`;设为 `null` 关闭时间轮转 |
| `logging.rotate_interval` | `1`,表示每隔几个 `rotate_when` 单位滚动一次 |
| `logging.max_bytes` | `0`(关闭)。按大小轮转,**要求 `rotate_when` 为 `null`**——两种轮转不能同时开 |
| `logging.backup_count` | `3`,保留几份历史日志 |
| `process.pid_dir` | 项目根下 `pids` |
| `process.stop_timeout` | `60`（秒）。Web 与后台服务的 `stop` 等整个进程组退出的期限，到期对整组 SIGKILL；Taskiq 服务用 `taskiq.stop_timeout` |
| `database.url` | `None`，用数据库前必须配置 |
| `database.echo` | `None`，此时跟随 `core.debug` |
| `database.enable_sql_logging` | `False` |
| `database.cache_pool_size` / `cache_pool_timeout` | `5` / `1.0` 秒；模型缓存未命中时查库用的独立连接池，见[模型缓存](cache.md#缓存连接池) |
| `i18n.use_i18n`、`use_i18n_path` | `False` |
| `i18n.default_language` | `en` |
| `cache.client` / `serializer` | `CACHE` / `pickle`；键前缀是 `<core.namespace>:cache` |
| `http_client.max_connections` | `300` |
| `mail.backend` | `oldman.mail.backends.console.ConsoleEmailBackend`，打印到标准输出；生产改成 smtp |
| `mail.default_from_email` / `subject_prefix` | `webmaster@localhost` / `[Oldman] ` |
| `mail.smtp.host` / `port` / `timeout` | `localhost` / `25` / `10` 秒；`use_tls` 与 `use_ssl` 互斥 |

Redis 内置 `DEFAULT`、`CACHE`、`SESSION` 别名，默认都指向 `localhost:6379` 的 TCP 端口（库 3、2、5）；`redis_url` 也接受 `rediss://`（TLS）和 `unix:///path/to/redis.sock?db=N`（已开启的 unix socket）。可添加其他别名，如 `SSE`。自定义别名必须提供真实 `redis_url`，不要假定它自动存在。开启依赖该别名的能力前，核对生成配置中的 URL、数据库编号和 `decode_responses`。

NATS 默认 DEFAULT 指向 nats://localhost:4222；Taskiq 默认关闭，启用时必须配置 namespace 和实际存在的 NATS/Redis alias。非 Web 服务不自动生成 web，但仍生成这些根配置。全部 Taskiq 默认值、安全参数转换和生命周期见[分布式任务配置](distributed-tasks.md#配置与默认值)。

Core 事件/RPC 另由根 nats_bus 控制：enabled/consume 默认 false，nats_alias 默认 DEFAULT，启用时必须提供 namespace。它与 Taskiq 可以引用同一命名地址，但不共用连接/协议；全部默认值、peer_id、codec 和启动/停止预算见 [NATS 配置](providers.md#配置与默认值)。配置 init/sync/check 不连接 NATS，也不读取证书文件。

邮件字段的含义和内置后端见[邮件](mail.md)。显式配置 `storages` 时必须包含 `default`，每个后端使用真实的类导入路径及其 options。不在模型导入阶段创建后端连接。

## Web 默认值与开关

| 字段 | 默认 |
| --- | --- |
| `web.listen_host` / `listen_port` | `::` / `17998` |
| `web.auto_reload` | `False` |
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

`core.debug` 为 true 时，Web 服务的 Sanic 会对事件循环调用 `set_debug(True)`。在这个模式下，uvloop 回收没有关闭的 async generator 时可能报 `AttributeError`，也可能直接段错误（[uvloop#699](https://github.com/MagicStack/uvloop/issues/699)、[uvloop#715](https://github.com/MagicStack/uvloop/issues/715)；到 2026-10-01 为止，0.22.1 与 0.23.0 都没有修复）。两个条件同时满足才会出现：打开了调试模式，并且代码里有 async generator 没有关闭（`break` 跳出 `async for` 之类）、留给垃圾回收。换 Python 版本避不开：用上游 #715 的复现脚本实测，3.12 的各补丁版和 3.13.11、3.13.15、3.14.2 在调试模式下都会出现（段错误，或者只打印一条 `AttributeError` 的 "Exception ignored"），3.14.7 上这个脚本不出错、框架自己的测试却会崩；关掉调试就都正常。框架自己的测试在 3.13.11、3.14.2 上不触发，CI 因此固定这两个版本。默认关闭调试的生产运行不受影响。调试时遇到回收 async generator 的报错或段错误就是这个问题；把自己代码里的 async generator 显式关闭（`contextlib.aclosing`），不留给垃圾回收，就不会触发。

### Web 安全配置

`web.security.secret_key` 默认空，在 Web 服务 `init/sync/write` 时生成并持久化。`fingerprint.aes_secret_key` 同样生成并持久化，采用 Base64 编码的 32 字节密钥。已有非空密钥不自动轮换。

`settings check` 或服务加载发现必需密钥仍为空，会要求先同步配置。不要在 worker 启动时各生成一份临时秘密，否则签名和验证不能稳定协作。

其他安全字段包括：

- `web.security.csrf.ttl`：默认 3600 秒；`check_referer` 默认 true，`check_url` 默认 false。
- `web.security.csrf.cookie_name`：默认 `csrf_id`，匿名访客的 CSRF 令牌绑定的随机 id 放在这个 cookie 里（见 [Web](web.md#csrf)）；不要改成 `csrftoken`，前端找不到隐藏字段时会把那个名字的 cookie 当作令牌读。
- `web.security.csrf.enforce`：默认 **false**。打开后框架注册一个全局中间件，对每个状态改变请求(非 GET/HEAD/OPTIONS/TRACE)校验 CSRF token，被 `@csrf_exempt` 标注的 handler 跳过。
  默认关是因为打开会波及**现在没有被保护的路由**——webhook、回调这类不经认证流水线识别调用方的接口。
  打开之前先把这些路由标上 `@csrf_exempt`，否则它们会开始返回 403。凭 Bearer 访问令牌认证的请求自动免检，不需要标注。关闭时保护仍按逐路由的 `@csrf_protect` 声明生效。
- `check_referer` 的语义已扩展:开启时按 **Origin 优先、Referer 回退**做同源校验,两者都缺失即拒绝。
  仅看 Referer 是不够的——`referrer-policy: no-referrer` 能把 Referer 完全去掉。浏览器仍会发 Origin 头,但在 `no-referrer` 下它的值是 `null`,本站表单也一样,框架按跨站拒绝;所以有表单要提交的页面不要用 `no-referrer`,需要不把地址泄露给别的站时用 `same-origin`。
- `web.security.fingerprint`：浏览器指纹时间差、频率限制与异常策略。

安全 token 和 Session 的有效期是不同设置，不能用其中一个代替另一个。

### Session、messages 与 SSE

| 配置 | 默认与含义 |
| --- | --- |
| `web.session.enabled` | false；启用才安装会话中间件 |
| `web.session.redis_alias` | `SESSION` |
| `web.session.expiry` | 43200 秒，12 小时；普通登录的会话时长（服务端 Redis TTL，Cookie 有效期与之一致，活动不续期） |
| `web.session.remember_expiry` | 2592000 秒，30 天；登录时勾选"记住我"后的会话时长 |
| `web.session.cookie_name` | `session_id` |
| `web.session.cookie_httponly` / `cookie_secure` / `cookie_samesite` | true / false / `Lax`；HTTPS 部署应调整 Secure |
| `web.auth.authenticators` | 未设置：开启 Session 时为 `[session]`，否则为空。请求认证方式按顺序尝试，第一个认出凭据的说了算；内置 `session`、`jwt`、`api_key`、`http_basic`、`ip_allowlist`（必须排最后），项目类写导入路径，见 [请求认证](web.md#请求认证requestctxuser) |
| `web.auth.jwt.secret` | 未设置。访问令牌的签名密钥，与 `web.security.secret_key` 分开，至少 32 个字符；要互认令牌的几个服务共用它。`web.auth.authenticators` 列了 `jwt` 而没设它，启动时报错；设置同步不会自动生成它 |
| `web.auth.jwt.access_token_ttl` | 900 秒。访问令牌寿命；校验时拒绝签得比它长的令牌 |
| `web.auth.jwt.refresh_token_ttl` | 604800 秒（7 天）。刷新令牌寿命，每刷新一次从头计算：客户端只要在这段时间内刷新过，就一直保持登录 |
| `web.auth.jwt.issuer` / `audience` | 未设置。设置后写进令牌的 `iss` / `aud`，校验时要求一致；未设置受众时，带 `aud` 的令牌一律拒绝 |
| `web.auth.api_keys` | 空。`api_key` 认证方式接受的 key，按名字配置，名字即 `request.ctx.auth.caller`。每个 key：`secret` 必填；`query_param` 未设置（设置后也从该查询参数读）；`authorization` 为 false（为 true 时也接受 `Authorization: Bearer <key>`）。两个名字不能共用一个 key；列了 `api_key` 却没有 key 时启动报错 |
| `web.auth.http_basic.realm` / `accounts` | `oldman` / 空。`http_basic` 认证方式的领域名（浏览器登录框上显示，不能含引号、反斜杠或控制字符）与固定账号（用户名 → 密码，原样存放；用户名不能含冒号）。列了 `http_basic` 却没有账号时启动报错 |
| `web.auth.ip_allowlist` | 空。`ip_allowlist` 认证方式接受的网段，按名字配置（名字 → 地址或 CIDR 网段列表），名字即 `request.ctx.auth.caller`。TCP 对端地址和按代理配置解析出的客户端地址必须落在同一个条目里，服务在代理后面时条目要列上代理自己的地址。网段不能带主机位，条目不能为空；列了 `ip_allowlist` 却没有条目时启动报错，见 [IP 白名单](web.md#ip-白名单) |
| `web.auth.login_backends` | `[users]`。登录与取令牌时核对凭据的登录后端，按顺序尝试，第一个认出的说了算；内置 `users` 查用户表，项目类写导入路径 |
| `web.messages.enabled` | false；控制 Cookie 一次性页面提示 |
| `web.sse.enabled` | false；控制 Redis 支持的分布式 SSE |
| `web.sse.redis_alias` | `SSE`，需显式配置此别名或改用合适的已有别名 |
| `web.sse.heartbeat_interval` | 15 秒 |
| `web.sse.session_check_interval` | 30 秒 |
| `web.sse.queue_size` | 100 |
| `web.sse.max_message_size` | 65536 字节 |

Web 配置校验会检查开启 Session 或分布式 SSE 时引用的 Redis 别名是否存在，但不会在 `settings check` 中连接 Redis。Cookie messages 不需要 Redis。

Web 服务安装 Admin，且原始配置没有 `web.messages.enabled` 时，`init/sync` 将它补为 true；用户显式 false 不被覆盖。运行时单纯读取缺省 YAML 不会执行这一写入默认的操作，也不会连带打开其他模块。

SimpleApplication 不自动补全或生成 `web` 节点，不执行上述 Web 专用密钥和 Redis 别名关系检查。显式提供的 Web 配置仍按字段类型解析；这不等于安装浏览器中间件。其他根配置和已安装 App 配置仍正常生成。

### 账户页面地址

站点自己的账户页面在哪里，只在这里配置一次。值必须是站内路径：以 `/` 开头，不带域名、查询串或 `#` 片段，不以 `//` 开头；加载配置时拒绝其他写法。

| 配置 | 默认与含义 |
| --- | --- |
| `web.account.login_url` | `/login`；登录页与登录提交。需要登录的请求在未登录时被送到这里 |
| `web.account.logout_url` | `/logout`；退出并回到登录页 |
| `web.account.login_redirect_url` | `/`；登录后没有安全的 `next` 时去的地方，已登录的人打开登录页也去这里 |
| `web.account.password_reset_url` | 未设置；设置后登录页显示"忘记密码"链接指向这里，找回密码流程要装在这个地址 |
| `web.account.profile_url` | `/user-session`；当前用户自己的页面，改自己密码的地址在它下面 |
| `web.account.user_events_url` | `/user-events`；当前用户的服务端事件流（会话结束、通知），只在 `web.sse.enabled` 时安装 |
| `web.account.users_url` | `/users`；用户管理列表，每个账户的页面在它下面 |
| `i18n.preference_url` | `/preferences/language`；切换语言后浏览器把选择 POST 到这里，登录与否都可以 |

读取它们的地方：`login_required` 等装饰器、表格/图表/下拉的数据接口、SSE 与通知接口在没有显式传 `login_url` 时，于请求时读 `web.account.login_url`；模板全局 `account_urls(request)` 把这些地址交给项目模板；`i18n compile-frontend` 把 `i18n.preference_url` 写进生成的 `generated.ts`（`languagePreferencePath`）。登录、个人页、用户管理三个流程不自己读设置，由服务把这些值传进去，见[账户页面的现成流程](web.md#账户页面的现成流程)。内置 Admin 的页面都在 `app_settings.admin.prefix` 下，不读这一组。

## 配置变更的操作边界

修改配置模型或安装 App 后，先执行目标服务的 `settings sync/check`，检查 YAML，再重启服务。

不要在请求里修改全局 Settings 来切换租户、语言或服务；请求级状态有自己的对象。不要在生产提供任意 reset；不同配置需要独立进程。

配置验证只说明数据符合当前模型及明确校验关系。数据库能否连接、表是否已迁移、Redis 是否可用、静态资源是否已构建，需要在对应操作阶段验证，不能把 `Settings OK` 当成完整部署验收。

## 运行期可变配置

上面的 YAML Settings 在启动时校验并发布一次，运行期间不变。需要**不重启就能改**的值——维护开关、公告文案、按频道调整的参数、设备名单——放在 `oldman.conf.containers` 的容器里。它们不经过 Settings 校验，也不出现在 `settings check/sync` 中。

| | `YamlStore` | `RedisStore` | `RedisSet` |
| --- | --- | --- | --- |
| 存在哪里 | 一个 YAML 文件 | 一个 Redis 键 | 一个 Redis 集合 |
| 多个进程看到的 | 各进程缓存一份，按间隔检查文件 | 同一份，每次读取都访问 Redis | 同一份，每次操作都访问 Redis |
| 值的形状 | schema 声明的结构 | schema 声明的结构 | `str` 或 `int` 成员 |
| 适合 | 运维会手工编辑、改动允许几秒后生效的结构化配置 | 要立即对所有进程生效的开关和小值 | 请求路径上判断成员的名单、随机取一个的代理池 |

下面的代码是 **API 参考**。EPG Demo 侧栏“动态配置”下的两个页面实际演示了它们，操作说明见 [Demo 页面与源码对照](../users/demo-examples.md#动态配置)。

### schema、读取与保存

`YamlStore` 和 `RedisStore` 的值由一个 `MsgspecModel` 子类声明：字段、类型和默认值。文件或键不存在时取默认值，所以**每个字段都要有默认值**，否则构造时抛 `TypeError`。依赖 Settings 的默认值用 `default_factory`，在取默认值时才读取。

```python
import msgspec

from oldman.serializers import MsgspecModel


class ChannelOverride(MsgspecModel):
    limit: int = 1
    enabled: bool = True


class ChannelOverrides(MsgspecModel):
    channels: dict[str, ChannelOverride] = {}
    proxies: list[str] = msgspec.field(default_factory=list)
```

| 方法 | 行为 |
| --- | --- |
| `get()` | 当前值 |
| `save(value)` | 按 schema 校验后整体写入 |
| `update(**changes)` | 读出当前值，改几个顶层字段，再交给 `save()`，返回保存的值 |

```python
value = await overrides.get()
value.channels["sports"] = ChannelOverride(limit=5)
await overrides.save(value)

await flags.update(maintenance=True, banner="维护中")
```

- msgspec 的 Struct 在构造和赋值时不检查类型；赋错类型由 pyright、Pyrefly 在静态检查时报出。运行时，读取按 schema 解码，`save`、`update` 写入前再校验一次：类型不对抛 `msgspec.ValidationError`，`update` 的字段名写错抛 `TypeError`，两种情况都什么也不写。`update` 返回校验后、真正保存的值（传了日期字符串的字段，返回值里已经是 `datetime`），与之后 `get()` 读到的一样。
- 同一个实例上的 `update` 排队进行，前一个保存完下一个才读，并发修改不同字段不会互相覆盖。所以一份配置在一个进程里只用一个实例：放在模块级，或者像下面带 Redis 别名的例子那样由 `@cache` 的函数返回。多个进程（`web.workers` 大于 1 时每个 worker 各有一个实例）：`YamlStore.update` 不管 `check_interval`，先看一次文件是否被别人改过，从文件里此刻的值改起，所以别的进程几秒前保存的修改不会被冲掉；只有真正同时写的那一刻，后写的覆盖先写的。需要多方频繁修改时，由一个进程负责写入。
- 整体读、整体写：`update` 只改顶层字段，改 `channels` 里的一项用 `get()`、赋值、`save()`。

### YamlStore

```python
from functools import cache
from pathlib import Path

import oldman.conf as conf
from oldman.conf.containers import YamlStore


class ChannelOverridesStore(YamlStore[ChannelOverrides]):
    def __init__(self, path: Path) -> None:
        super().__init__(ChannelOverrides, path, check_interval=5.0)
        self.proxy_index = 0

    def on_file_changed(self, old: ChannelOverrides, new: ChannelOverrides) -> None:
        # 文件被外部修改后调用：在这里重置由配置派生的状态
        self.proxy_index = 0

    async def next_proxy(self) -> str | None:
        proxies = (await self.get()).proxies
        if not proxies:
            return None
        proxy = proxies[self.proxy_index % len(proxies)]
        self.proxy_index += 1
        return proxy


@cache
def channel_overrides() -> ChannelOverridesStore:
    """每个文件、每个进程一个实例。路径取自 settings，所以第一次调用要在 bootstrap 之后。"""
    return ChannelOverridesStore(conf.settings.core.data_dir / "channel_overrides.yaml")
```

不需要钩子时不必写子类，直接 `YamlStore(ChannelOverrides, path)`。

- 进程内保存解码好的值：`check_interval` 秒内不碰磁盘；到期 stat 一次，文件变了才重新解析。
- `get()` 返回的是**共享对象**：改了就 `save`；只想临时换个值用，先 `msgspec.structs.replace()` 出一份副本再改，否则下一次保存会把临时改动写进文件。
- 文件不存在时，把 schema 的默认值写成文件。
- `on_file_changed(old, new)` 只在读到**外部修改**（包括删除文件）后调用；自己的 `save`、`update` 不调用。钩子里的异常记 ERROR，不影响读取。
- 子类由配置加工出来的缓存（例如按运行环境改过字段的对象）要在两处清空：外部修改在 `on_file_changed` 里；自己保存在覆盖的 `save` 里，调用父类之后清——`update` 经由 `save` 写入，不用另外处理。直接从 `get()` 取值的不需要缓存，值本身就在内存里。
- 外部改坏（YAML 语法错、类型不对、存成了 UTF-8 以外的编码）：不采用，保留上次的合法值并记一次 ERROR；改好后照常加载并调用钩子。第一次加载时文件就不合法，`get()` 抛出解析或校验错误。
- 保存失败（校验不通过、写入出错）时，内存按文件重新加载，不调用钩子。
- 写入先写同目录的临时文件再整体替换，读者不会看到写了一半的文件；已有文件的权限保持不变。保存时 YAML **注释不保留**。
- 类型按 YAML 的解析结果：不加引号的 `2026-09-27` 是日期，放进 `str` 字段会报错，需要字符串就加引号。
- 变化检测看 inode、纳秒修改时间和大小。原地覆盖、保留修改时间且大小不变的复制（`cp -p`）不会被察觉。

### RedisStore

```python
from functools import cache

from oldman.conf.containers import RedisStore
from oldman.providers.redis import redis_client


class SiteFlags(MsgspecModel):
    maintenance: bool = False
    banner: str = ""


# 不传 client：第一次调用时才取全局 redis_client（DEFAULT 别名），所以可以放在模块级。
site_flags = RedisStore(SiteFlags, "site_flags")


@cache
def channel_limits() -> RedisStore[ChannelOverrides]:
    # using() 当场读取 Redis 配置并校验别名是否存在，必须在服务 bootstrap 之后调用，
    # 不能放在模块级。@cache 让每个进程只有一个实例，update 才能排队。
    return RedisStore(ChannelOverrides, "channel_limits", client=redis_client.using("CACHE"))


async def in_maintenance() -> bool:
    return (await site_flags.get()).maintenance
```

- 键是 `<core.namespace>:store:<name>`，值是整个 schema 的 msgpack。名字必须是非空字符串，否则 `ValueError`。
- 不做本地缓存：每次 `get()` 读一次 Redis，别的进程写入后下一次读取即可见。每次返回的都是新解码的对象，改了直接 `save`。
- 键不存在时取默认值，不写入。存的值与 schema 对不上（例如改过字段类型）抛 `msgspec.ValidationError`，不回落默认值；schema 删掉的字段忽略，新加的字段取默认值。
- 没有过期时间。需要定时失效的值，存一个到期时间字段（如 `banner_until: datetime | None`），由读取方判断。
- Redis 不可用时，底层客户端的异常直接抛给调用方。连接由 Redis Provider 持有，容器不打开也不关闭连接；默认客户端要求服务已完成 bootstrap、Redis 别名已配置。

### RedisSet

```python
from oldman.conf.containers import RedisSet

allowed_devices = RedisSet(str, "allowed_devices")
stream_proxies = RedisSet(str, "stream_proxies")


def channel_devices(tag: str) -> RedisSet[str]:
    # 按 tag 区分的一组集合：用到时再构造
    return RedisSet(str, f"channel_devices:{tag}")


async def may_watch(device_id: str) -> bool:
    return await allowed_devices.contains(device_id)
```

| 方法 | 行为 |
| --- | --- |
| `add(member)` | 加入成员；集合原先没有它时返回 `True` |
| `remove(member)` | 移除成员；集合原先有它时返回 `True` |
| `contains(member)` | 是否有这个成员 |
| `members()` | 全部成员，读出整个集合 |
| `random()` | 随机一个成员；集合为空时返回 `None` |

- 每个操作直接落到 Redis 集合（`SADD`、`SISMEMBER`、`SRANDMEMBER`……），不把整个集合读出来。判断成员用 `contains`，不要 `members()` 之后再判断。
- 成员限 `str` 或 `int`，按精确类型检查：`int` 集合不收 `True` 或 `"7"`，抛 `TypeError`。
- 键是 `<core.namespace>:store:<name>`，与 `RedisStore` 共用：名字不能重复，否则 Redis 报 `WRONGTYPE`。
- 构造、连接和异常的规则与 `RedisStore` 相同。不提供列表和队列。

### 已废弃的 AsyncConfigDict 与 RedisSettings

两者仍可使用，构造时发出 `DeprecationWarning`；新代码用上面的容器。

| 旧写法 | 新写法 |
| --- | --- |
| `AsyncConfigDict` 子类，`get_empty_data()` | `YamlStore[Schema]`，默认值写在 schema 的字段上 |
| `get_data()` 返回的 dict，以及子类里把 dict 解码成对象的缓存 | `get()` 直接返回解码好的对象，这类缓存可以删掉 |
| `on_file_changed(old_data, new_data)` | `on_file_changed(old, new)`，同样只在外部修改后调用 |
| `save_data(data)` | `save(value)`、`update(**changes)` |
| `get_data_sync()` | 无，在异步代码里用 `get()` |
| `RedisSettings` 的 `get_value`、`set_value` | `RedisStore` 的字段，`get()`、`update()` |
| `RedisSettings` 的集合方法 | `RedisSet` |
| `RedisSettings` 的列表方法、`set_value(..., ttl=)` | 不提供 |
