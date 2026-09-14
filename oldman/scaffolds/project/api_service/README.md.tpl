# {{ project_name }}

基于 Oldman 的 API 项目。服务入口是 `services/{{ service_name }}.py`，配置是 `data/{{ service_name }}_settings.yaml`。

## 安装和配置

在本项目根目录执行：

```sh
uv sync
./run.sh {{ service_name }} settings sync
./run.sh {{ service_name }} settings check
```

以上安装需要 `pyproject.toml` 中的 Oldman 版本在包索引可用。使用框架源码开发时，改用自己的 `.venv` 和 editable 安装，见 [服务创建指南](https://github.com/alexliyu7352/oldman/blob/master/docs/agents/create-service.md#新项目的命令流程)。

脚手架已经生成最小 YAML，因此先用 `sync` 补字段及密钥。只有文件不存在时才用 `settings init`。真实配置包含秘密，不提交到公开仓库。

## 添加 API

```sh
./run.sh startapp tasks
```

交互选择 `api`，填写显示名称。将 `apps.tasks` 加入当前服务 YAML 的 `apps` 列表，然后运行：

```sh
./run.sh {{ service_name }} settings sync
./run.sh {{ service_name }} start
```

脚手架提供 `/tasks` 示例路由，默认服务端口为 17998。根路径 `/` 没有默认路由。测试前在 YAML 将 `web.listen_host` 设为 `127.0.0.1`，避免将未认证示例开放到网络。

`run.sh` 只执行本项目虚拟环境里的 `oldman`，不代为迁移或选择服务。Ctrl+C 停止前台服务，或另开终端运行 `./run.sh {{ service_name }} stop`。

## 使用数据库时

先填写真实的 `database.url`，注册声明模型的 App，再运行：

```sh
./run.sh db makemigrations
./run.sh db migrate
```

前者交互生成 App 的迁移文件，后者执行；服务启动不自动建表。未使用数据库时不用运行这些命令。完整步骤见 [Demo 数据教程](https://github.com/alexliyu7352/oldman/blob/master/docs/users/tutorial-tasks.md)。

项目翻译命令在项目根执行：`./run.sh i18n extract`、`./run.sh i18n init <locale>`、`./run.sh i18n update`、`./run.sh i18n compile`。
