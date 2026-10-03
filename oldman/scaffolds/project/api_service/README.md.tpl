# {{ project_name }}

给 coding agent 的说明在 [AGENTS.md](AGENTS.md)（Claude Code 经 `CLAUDE.md` 读到同一份），让 agent 开工前读完。

基于 Oldman 的 API 项目。服务入口是 `services/{{ service_name }}.py`，配置是 `data/{{ service_name }}_settings.yaml`。

## 安装和配置

在本项目根目录执行：

```sh
uv sync
./run.sh {{ service_name }} settings sync
./run.sh {{ service_name }} settings check
```

`.python-version` 指定 Python 3.13（框架推荐的版本），`uv sync` 按它选解释器，本机没有时 uv 会自动下载；要用其他受支持的版本（3.12–3.14）就改这个文件。

以上安装需要 `pyproject.toml` 中的 Oldman 版本在包索引可用。使用框架源码开发时，改用自己的 `.venv` 和 editable 安装，见 [服务创建指南](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/agents/create-service.md#starting-a-new-project)。

脚手架已经生成最小 YAML，因此先用 `sync` 补字段及密钥。只有文件不存在时才用 `settings init`。真实配置包含秘密，不提交到公开仓库。

## 启动和试用

```sh
./run.sh {{ service_name }} start
```

默认端口 17998。测试前在 YAML 将 `web.listen_host` 设为 `127.0.0.1`，不把服务开放到网络。另开终端试三个接口，凭据在 `data/{{ service_name }}_settings.yaml` 的 `web.auth` 里，是生成项目时随机产生的：

```sh
curl http://127.0.0.1:17998/
curl -H "X-API-Key: <web.auth.api_keys.example.secret>" http://127.0.0.1:17998/api/caller
curl -u "ops:<web.auth.http_basic.accounts.ops>" http://127.0.0.1:17998/api/ops
curl -i http://127.0.0.1:17998/api/caller    # 不带凭据：401
```

三个接口在 `apps/home/views.py`，都不需要数据库和 Session：`/` 是健康检查，不要求认证；`/api/caller` 只认 API key（请求头 `X-API-Key`），返回 key 在配置里的名字；`/api/ops` 只认 HTTP Basic，返回账号名。加调用方、换 key 改 YAML 的 `web.auth`；用不到的接口直接删，三个都不要就从 `apps` 列表里去掉 `apps.home`。按来源网段放行（IP 白名单）要按部署网络配置，见[调用方认证](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/web.md#服务与内部工具调用方认证)。

## 添加 API

```sh
./run.sh startapp tasks
```

交互选择 `api`，填写显示名称。将 `apps.tasks` 加入当前服务 YAML 的 `apps` 列表，然后运行：

```sh
./run.sh {{ service_name }} settings sync
./run.sh {{ service_name }} start
```

脚手架提供 `/tasks` 示例路由。

`run.sh` 只执行本项目虚拟环境里的 `oldman`，不代为迁移或选择服务。Ctrl+C 停止前台服务，或另开终端运行 `./run.sh {{ service_name }} stop`。

## 使用数据库时

先填写真实的 `database.url`，注册声明模型的 App，再运行：

```sh
./run.sh db makemigrations
./run.sh db migrate
```

前者交互生成 App 的迁移文件，后者执行；服务启动不自动建表。未使用数据库时不用运行这些命令。完整步骤见 [Demo 数据教程](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/users/tutorial-tasks.md)。

项目翻译命令在项目根执行：`./run.sh i18n extract`、`./run.sh i18n init <locale>`、`./run.sh i18n update`、`./run.sh i18n compile`。
