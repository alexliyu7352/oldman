# 部署与运行

本章部署的是使用 Oldman 的应用，不是把框架源码仓库当业务工程启动。先完成对应教程，准备自己的权限和数据规则。Linux 是当前运行目标；具体驱动、软件版本和依赖锁以项目取得的发行版本为准。

## 部署前明确四件事

1. **运行哪个服务**：EPG Demo的 `services/web.py` 对应 `./run.sh web start`；一个命令只运行指定服务。下文沿用这个真实入口，应用使用其他文件名时对应替换。不同服务使用不同 YAML，不在一个进程里切换配置。
2. **谁管理数据库结构**：同一数据库由一个项目负责迁移；其他项目不能各自修改同一套迁移状态。部署只执行已审阅的迁移文件，不在服务器临时 makemigrations。
3. **数据放哪里**：服务配置、数据库、上传文件及日志目录要持久、可写且有备份。发布代码或容器替换不能顺便清空这些目录。
4. **哪些外部连接必需**：纯 API 不一定需要 Redis；Session 和分布式 SSE 需要；Taskiq 需要开启 JetStream 的 NATS 及 Redis；外部 HTTP、远程 Storage 按业务启用。settings check 只校验配置，不证明连接可达。

## 准备运行环境和配置

应用使用自己的 Python 环境和锁文件，安装与所用文档相符的 Oldman。开发时可用 editable 源码；正式部署建议使用已验收且版本固定的产物，不把开发目录软链接当部署方案。

EPG Demo的安装入口是 `python3 scripts/bootstrap.py`，其本地源码与已发布包两条路径见[入门教程](getting-started.md)。当前Demo没有提交uv.lock或前端pnpm-lock.yaml，不能直接执行frozen安装并声称已锁定部署依赖。正式部署须在应用自己的发布流程中固定并验收依赖，不在生产主机临时升级来绕过失败。

下面两条是**应用已准备并提交对应锁文件后的安装接口**，不是当前Demo已具备的教程步骤：

```sh
uv sync --frozen
pnpm -C frontend install --frozen-lockfile
```

纯API或后台应用不需要前端安装。源码关联的开发项目没有锁定发行来源时，先完成该项目的依赖发布准备，不要直接运行上述命令切换依赖来源。

新环境没有实际 YAML 时，先从已审阅的同名 `.example.yaml` 初始化，再编辑真实连接和密钥，检查后再启动。已有 YAML 需要补新字段时用 sync；先备份再核对差异，不能用 init 覆盖。

```sh
./run.sh web settings init
# 编辑 data/web_settings.yaml 后再检查
./run.sh web settings check
```

Web 安全根密钥在 init/sync 时生成并写入，不在 worker 启动时随机变化。所有 worker 必须读同一份服务配置。不要把真实 YAML、密码、Session Cookie 或通知私有内容提交到公共仓库。

HTTPS 部署至少核对以下已有字段：

```yaml
web:
  debug: false
  auto_reload: false
  listen_host: 127.0.0.1
  listen_port: 18080
  domain: https://dashboard.example.com
  fallback_error_format: auto
  session:
    cookie_secure: true
    cookie_httponly: true
    cookie_samesite: Lax
```

这是合并到已有配置的片段，域名必须替换；不能因此删除 session.enabled、Redis 等其他字段。开发机 HTTP 下不要开启 Secure Cookie 后又误判登录无效。

## 数据库和静态资源

数据库迁移前做可恢复备份，并核对当前连接。首次使用或内部状态恢复可能要求交互，不把首次初始化伪装成完全无人值守部署。

```sh
./run.sh db status
./run.sh db migrate
./run.sh db status
```

部署进程必须携带全部已注册 App 的迁移文件，不能只复制 models.py。禁止在每个 Sanic worker 启动时各自迁移。fixture 仅用于预设数据，不是数据库备份；业务数据恢复不能依赖 dumpdata 替代完整备份。

业务 Dashboard 在应用前端工程执行自己的安装与构建，再从应用根收集资源。例如使用教程脚本时：

```sh
pnpm -C frontend build
./run.sh web static collect
```

纯内置 Admin 只需要发行包中现成的 Admin 产物与 static collect；纯 API 无浏览器资产时不需要这一步。生产页面不能指向 Vite 开发服务器。

收集目录由 `web.static.root` 指定；公开 URL 由 `web.static.url` 指定，两者不是一回事。代理提供静态文件时必须映射同一个收集目录。升级后检查 HTML 引用的带 hash 文件是否实际存在，避免先删旧资源却仍有旧页面引用。

## 启动、停止与进程托管

```sh
./run.sh web start
```

这是前台进程。`run.sh` 只是选择项目环境并原样传参数，不自动拉起其他服务、Redis、数据库或前端构建。

普通终端可 Ctrl+C；另一个终端的 `./run.sh web stop` 根据 PID 文件发出终止信号。该命令返回不等于所有资源已经关闭，仍要观察日志、进程和监听端口。不要删除真实运行进程的 PID 文件来“强制修好”。

生产可用系统进程管理器托管同一个前台命令，明确配置：工作目录为应用根、运行用户有数据目录权限、启动命令为项目 `.venv/bin/oldman web start`、退出信号及合理的停止超时。托管器负责重启服务主进程；不要再套另一套主进程守护。Taskiq内部监督它自己的执行子进程是另一层职责，不因此删除它的保活机制。

`prepare_server()` 决定如何把 workers 等设置交给 Sanic。增加 worker 前检查数据库池、每 worker 的后台任务、内存缓存和 SSE 订阅数；不要以为进程内对象自动共享。

## 分布式任务服务

Taskiq Worker/Scheduler 另见[任务部署与停止](distributed-tasks.md#7-停止排错与范围)：分别以前台命令运行，单 namespace 一个 Scheduler，多个 Worker 服务可以消费相同或不同队列。JetStream 文件目录和动态计划 Redis 需要持久化策略；结果默认 24 小时自动清理。Taskiq 的 stop 与普通服务不同，会等待并在总期限后强停核验过的整个进程组；无需第二个 kill 命令。systemd 是可选的外层托管，停止时通过托管器操作，避免 Restart 策略重新拉起。

## 反向代理与长连接

- 只允许可信代理访问内部监听端口。代理覆盖客户端传入的真实 IP header，不能直接相信互联网请求自带的 X-Real-IP。
- TLS、可信转发头和公开域名须一致，否则安全 Cookie、重定向和 CSRF 来源检查可能出错。
- SSE 路径需要持续转发、不缓冲事件，并给连接留出足够空闲超时；心跳不能穿过一个一直缓存响应的代理。
- WebSocket 路径还要正确转发 Upgrade。SSE 与 WebSocket 不是同一种代理协议。
- 静态目录可以公开；附件目录不能一概公开。框架默认 media 路由不替你验证下载权限，私有附件应使用受保护视图。

框架不会根据一份代理示例自动验证你的公网边界。上线前从实际外网路径验证登录、Cookie、上传、SSE/WS，而不只在服务器 curl 回环地址。

## 关闭责任和故障观察

资源由持有它的服务负责收尾。当前 Demo 的 WebService 在 `before_server_stop()` 调用基类后关闭 db_manager；它的 HTTP 示例客户端在 `after_server_stop()` 关闭，并用 finally 保留基类的缓存/Redis 收尾。两个方法都在可 await 的服务生命周期中，不在每个请求结束时销毁进程级连接池。SimpleApplication 使用自己的 before_stop/after_stop；HTTP/NATS 连接、定时任务和订阅也不能依靠框架猜测后自动关闭。实际方法见 [HTTP 客户端](../developers/http-client.md#创建初始化关闭)，完整关系见[生命周期](../developers/applications.md)及[后台参考](../developers/background.md)。

默认健康扩展或“端口已打开”不能证明数据库、Redis和第三方接口可用。部署检查按应用实际需要做一次只读数据库请求、一次登录/退出及一条代表性业务操作；不要为探活不断写业务数据。

| 故障 | 先检查 |
| --- | --- |
| 启动后首个数据库请求才失败 | 数据库延迟连接，核对 URL、驱动、权限与迁移状态 |
| 登录后仍匿名 | Cookie Secure/domain/path、代理协议、Session Redis；不要替换成内存会话 |
| 页面有样式但新组件没有 | 应用构建与图标扫描是否包含对应源码，是否 collect 了本次产物 |
| CSRF 403 | 请求令牌、页面是否过期、密钥是否被重新生成、来源是否一致 |
| SSE 在线但收不到 | 发布和订阅的 Redis alias/channel_prefix、用户绑定、代理缓冲、浏览器控制台 |
| 停止过程报错 | 先看第一个资源关闭异常，区分业务任务、连接池与服务器最终退出 |

文档示例通过不等于业务已达到生产条件。备份恢复演练、容量评估、监控告警、权限审核和应用自己的失败路径仍须由部署者完成。
