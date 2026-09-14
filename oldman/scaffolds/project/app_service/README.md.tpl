# {{ project_name }}

基于 Oldman `SimpleApplication` 的后台服务项目，不启动 HTTP 服务。入口是 `services/{{ service_name }}.py`，配置是 `data/{{ service_name }}_settings.yaml`。

在本项目根目录执行：

```sh
uv sync
./run.sh {{ service_name }} settings sync
./run.sh {{ service_name }} settings check
./run.sh {{ service_name }} start
```

生成的 `main()` 没有业务逻辑，会立即返回并退出。这是可填写的服务骨架，不是已经开始轮询的 Worker。业务异步流程写入 `main()`，必要的异步资源在生命周期中初始化和关闭。

`run.sh` 只执行本项目虚拟环境中的 `oldman`，不自动运行所有服务。长时间运行时可以 Ctrl+C 停止，或另开终端使用 `./run.sh {{ service_name }} stop`。

增加可复用 App：

```sh
./run.sh startapp tasks
```

交互选择需要的 App 模板并填写显示名称，然后将实际包路径 `apps.tasks` 加入当前服务 YAML，再执行 `settings sync`。SimpleApplication 可以加载 App 模型和命令，不导入其 Web views。

需要数据库时，先填写 `database.url`、声明并注册模型，再执行 `./run.sh db makemigrations` 与 `./run.sh db migrate`。没有数据库业务时不要为了启动服务执行迁移。

普通一次性管理操作优先写成 App 的 `Command`，无需额外长期服务。完整接线见 [创建服务指南](https://github.com/alexliyu7352/oldman/blob/master/docs/agents/create-service.md)。

`uv sync` 需要声明的发行包可用。使用框架源码时，在本项目自己的 `.venv` 中 editable 安装，具体命令见[本地 Python 源码安装](https://github.com/alexliyu7352/oldman/blob/master/docs/agents/create-service.md#新项目使用本地-python-源码)。真实 YAML 密钥和连接信息不提交到公开仓库。
