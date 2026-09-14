# 配置、App 与服务

三者分工很简单：**服务决定启动什么，App 提供功能，配置文件决定这个服务使用哪些功能和值。**

本文以 EPG Demo 为例：[services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py) 提供 Web 服务，[apps/examples/apps.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/apps.py) 注册功能示例，[data/web_settings.example.yaml](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/web_settings.example.yaml) 保存该服务的公开初始配置。以下命令都在 Demo 根目录执行；安装前置见[入门教程](getting-started.md)。

## 服务与配置文件

当前 Demo 的实际入口是：

```text
services/web.py → ./run.sh web start → data/web_settings.yaml
services/task_worker.py → ./run.sh task_worker start → data/task_worker_settings.yaml
services/task_scheduler.py → ./run.sh task_scheduler start → data/task_scheduler_settings.yaml
services/nats_a.py → ./run.sh nats_a start → data/nats_a_settings.yaml
services/nats_b.py → ./run.sh nats_b start → data/nats_b_settings.yaml
```

`WebService` 是 Python 类名，`web` 才是由文件名得到的命令名。修改 `SERVICE_NAME` 只改变可读名称，不改变命令和配置文件名；无需填写 `SERVICE_ID`。

服务文件名支持小写字母、数字与下划线，必须以字母开头。文件放在 `services/` 的直接下一层，不使用嵌套目录发现服务。同一个文件定义一个直接继承 `WebApplication`、`SimpleApplication`、`TaskiqWorkerApplication` 或 `TaskiqSchedulerApplication` 的具体类。

以后增加服务可使用 `startservice`，具体接口见[CLI 参考](../developers/cli.md#项目级命令)。该命令只创建入口文件，不自动创建配置。Web/Taskiq三服务的共享 namespace、连接和不同 App 清单见[分布式任务教程](distributed-tasks.md)；两个Simple接收服务见[通信教程](service-communication.md)。这五个服务仍使用同一种根 Settings 类型，各自初始化配置不等于启动全部服务。

不同服务在不同进程运行，各自拥有当前 Settings 实例。一个进程不能先初始化某个服务配置，再切换到另一个服务继续运行。

## 创建、检查与补全配置

| 命令 | 用途 | 是否写文件 |
| --- | --- | --- |
| `./run.sh web settings init` | 配置不存在时创建；已存在则报错 | 是 |
| `./run.sh web settings sync` | 保留现有值及注释，补齐缺失的字段和必要密钥 | 是 |
| `./run.sh web settings check` | 校验当前配置并输出诊断 | 否 |
| `./run.sh web start` | 读取配置并启动服务 | 不自动改写 YAML |

Demo 已提供 `data/web_settings.example.yaml`。当本机 `data/web_settings.yaml` 不存在时，运行 `./run.sh web settings init`，框架会读取这份示例、补全默认字段并生成本机密钥；不必先复制 YAML。若已经按 Demo README 复制或初始化过文件，就使用 `sync`，不要再覆盖本机配置。普通项目没有同名示例文件时，App 列表默认是空的。

这适合公开项目：提交不含真实密码和密钥的 example，使用者第一次运行 `settings init` 得到本机配置。框架不会扫描所有业务目录、猜测它们都应该被本服务安装。

`sync` 不会用新的默认值覆盖你已经填写的值。比如已写 `messages.enabled: false`，它不会因为你安装 Admin 而改成 true；移动项目后，它也不会自动修正已经持久化的绝对路径。应当检查并编辑 `core`、`logging`、`process`、静态目录及 Storage 路径。

运行配置是 YAML。普通业务配置值不从 `.env` 或同名环境变量覆盖读取。CLI 语言、工程目录发现等工具自己的环境参数是另一回事，不能据此推断业务 Settings 支持环境变量注入。

## 安装 App

每个服务的 YAML 都有自己的列表。下面是 Demo 示例 YAML 的完整 App 清单和 App 设置部分，不是整个配置文件：

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

其中 `oldman.auth` 的 label 是 `auth`，提供认证基础能力和 User 选择配置；Demo 的 `apps.auth` 的 label 是 `epg_auth`，提供具体 `OldmanUser` 与登录视图。这是两个不同的 App，`app_settings.auth.user_model` 指向后者定义的类。不要把 Python 包路径、label 和模型类名混为一谈。

`oldman.apps.admin` 提供共享设置与用户管理命令。将它加入清单不等于挂载 `/admin`；EPG Demo 使用自己的 Dashboard，独立 Admin 站点见[Admin 教程](admin.md)。

一个 App 必须可被当前 Python 环境导入，并且具有 `<包路径>.apps` 模块，模块里导出一个名为 `app` 的 `AppConfig` 对象。

第三方 App 也是同样的用法：先安装其 Python 包，再将它文档给出的实际导入包路径写入列表。Python 发行包名称和导入路径可能不同，不要根据 pip 名称猜路径。

实际的 [apps/examples/apps.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/apps.py) 完整内容如下：

```python
"""Dashboard examples application metadata."""

from oldman.apps import AppConfig
from oldman.i18n import gettext_lazy as _

from .settings import ExamplesSettings


class ExamplesAppConfig(AppConfig[ExamplesSettings]):
    """Own the Dashboard's reusable example data and views."""

    label = "examples"
    display_name = _("Dashboard Examples")
    icon = "ri-flask-line"
    settings_model = ExamplesSettings


app = ExamplesAppConfig()

__all__ = ["ExamplesAppConfig", "app"]
```

`label` 是当前服务内唯一的稳定标识，用在 App 配置、模型归属和迁移分支中；`display_name` 是给人看的名称；`icon` 是单个受支持图标 class。显示名称可以翻译，不要把稳定 label 当展示文案。

模块名默认是 `models`、`views`、`commands`、`tasks`、`events` 和 `migrations`。没有某类功能时，可以不创建相应模块；不需要把默认模块名改成 `None`，也不用造空的代理实现。只有 Worker/Scheduler 自动加载 tasks，Web 发布方按需显式导入。events 只由启用Core接收的普通Web/Simple服务加载，命令和Shell不自动启动订阅。

目录与加载约束详见 [AppConfig 参考](../developers/applications.md#appconfig)。

## App 自己的配置

可复用 App 的设置放在 App 自己的 Pydantic 类中。上面的 ExamplesSettings 来自 Demo 同包 [settings.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/settings.py)，定义 HTTP 示例实际使用的 http_base_url，默认 https://httpbin.org。`AppConfig[ExamplesSettings]` 与 `settings_model = ExamplesSettings` 同时声明静态类型和运行时配置类型；服务配置的 `app_settings.examples.http_base_url` 绑定到它的 app.settings。本例拒绝非 HTTP(S)、凭据、query 和 fragment，地址只能由可信部署配置提供。

实际消费者是 [http_example.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/http_example.py) 的 run_http_example：从该 App 导入 app，在函数运行时读取 app.settings.http_base_url，不在元数据导入时提前读取。完整配置和操作见[HTTP 示例](cache-and-http.md#运行后端-http-示例)。只有确实需要设置的 App 才声明模型，不要求所有 App 创建空配置类。

Demo 也使用内置 Auth 和 Admin 的强类型配置，下面以登录策略说明另一条实际读取路径。

Admin 的配置声明在框架 [AdminSettings](../../oldman/apps/admin/settings.py)，注册在框架 [AdminAppConfig](../../oldman/apps/admin/apps.py)。这两份代码属于 Demo 安装的框架包，不需要复制到 Demo：

- `AdminSettings.require_superuser` 是布尔字段，默认 false。
- `AdminAppConfig[AdminSettings]` 声明静态类型，`settings_model = AdminSettings` 指定运行时创建的配置类。
- YAML 的 `app_settings.admin.require_superuser` 绑定到该 App 的 `app.settings.require_superuser`。
- 业务通过 `from oldman.apps.admin.apps import app as admin_app` 读取，IDE 能推断配置类型。

Demo 的 [apps/auth/services.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/auth/services.py) 有实际消费者。下面是完整的 `authenticate_user()` 函数节选；同文件已导入 `OldmanUser` 和 `admin_app`，并定义了用只读数据库 Session 查询的 `get_user_by_username()`。不要只复制函数而漏掉这些依赖：

```python
async def authenticate_user(username: str, password: str) -> OldmanUser | None:
    """校验用户名密码并返回可登录的后台用户。"""
    user = await get_user_by_username(username)
    if not user or not user.is_active:
        return None
    if not user.is_staff:
        return None
    if admin_app.settings.require_superuser and not user.is_superuser:
        return None
    if not user.check_password(password):
        return None
    return user
```

该 Demo 将 Admin 的这项策略用于自己的 Dashboard 登录：false 表示允许正常的 active staff 用户；true 则还要求 superuser。无论此开关如何，停用用户、非 staff 和密码错误都会被拒绝。它不是“关闭全部权限校验”的开关。

两个不同服务安装同一个带设置的 App 时，可以在各自 YAML 中填写不同值；共享业务代码保持同一导入入口，不需要判断自己在哪个服务中。只有在配置已初始化且 App 已安装时才能读取；正常 CLI 会完成初始化，IDE 见 [Shell 与 bootstrap](../developers/applications.md#python-shell-与-ide)。

未安装的 App 不生成配置；YAML 却写了它的 `app_settings` 时会报错。安装了有配置模型的 App 但没填写具体值时，使用该模型默认值；缺少无默认值的必填字段时校验失败。

不要写 `settings.admin`、`settings.app_settings` 或 `settings.for_app(...)`。App 与根 Settings 是两个强类型对象空间，只是保存到同一个 YAML。编写 App 配置模型的方法见[App Settings 参考](../developers/configuration.md#app-settings)。

## 项目公共配置

整个项目只有一个根类型。Demo 的 [config/schemas.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/config/schemas.py) 在 `DefaultSettings` 上声明了数据库、Web、i18n 和 Storage 的项目默认配置；不是为每个服务各写一套 `ApiSettings`、`WebSettings`。具体类与默认函数见[根 Settings 参考](../developers/configuration.md#根-settings)。

业务导入入口是 [config/settings.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/config/settings.py)，完整内容如下：

```python
"""Runtime settings instance for the Oldman application."""

from typing import cast

import oldman.conf as conf
from config.schemas import Settings

settings = cast(Settings, conf.settings)
```

`cast()` 只告诉静态分析器“这是项目的 Settings”，不会读取 YAML，也不会创建另一份配置。业务使用 `from config.settings import settings`；不要复制到 `app.ctx.settings`。

只有确实属于项目公共设置的字段才增加到根类；可复用 App 独有字段应留在该 App 的配置模型。每个服务共享类型、分别读取自己的 YAML 值。

更改模型后，对需要的服务运行 `settings sync` 并检查配置，再重启服务。运行中的 Settings 不会因为你修改磁盘 YAML 自动热切换。

## Web 相关开关

Session、SSE 与 Cookie messages 是分别启用的能力。框架默认关闭；Demo 的示例 YAML 则明确将三者都开启，不能把框架默认值当成 Demo 当前设置。

Demo 配置了：

| 设置 | Demo 值 | 用途 |
| --- | --- | --- |
| `web.session.enabled` / `redis_alias` | true / `SESSION` | 浏览器会话 |
| `web.session.expiry` / `cookie_name` | 86400 / `oldman_session_id` | 一天有效期与 Cookie 名称 |
| `web.messages.enabled` | true | Cookie 一次性页面提示 |
| `web.sse.enabled` / `redis_alias` | true / `SSE` | 分布式 SSE |
| `web.sse.channel_prefix` | `oldman_epg_dashboard` | Pub/Sub 频道前缀 |
| `redis.SESSION.redis_url` | `redis://127.0.0.1:6379/5` | Demo 会话数据 |
| `redis.SSE.redis_url` | `redis://127.0.0.1:6379/6` | Demo SSE 连接 |

应以本机 YAML 为准，不为试教程而覆盖已有 Redis URL。项目与环境的 SSE 隔离依赖频道前缀，不能以为换 Redis 数据库编号就能隔离 Pub/Sub。

- Session 使用配置的 Redis 连接，不能用进程内字典替代多 worker 的会话。
- 分布式 SSE 使用 Redis Pub/Sub；本地直接输出 SSE 的用途与之不同。
- Cookie messages 不依赖 Redis；它用于页面间的一次性提示。
- Web 服务安装 Admin 且尚未显式填写 messages 开关时，`init/sync` 会补为 true。这不会自动开启 Session、安装 Auth 或安装 Admin 路由。

SimpleApplication 的 `init/sync` 不会自动生成整个 `web` 节点；如果你主动写了该节点，现有内容保留。它不会启动 Web 路由或浏览器会话中间件。后台代码需要显式使用其中某项设置时，仍由相应模块的用法决定初始化，不能把“有配置”等同于“能力已经启动”。

配置字段、实际默认值及调试路径选项见[配置参考](../developers/configuration.md)。
