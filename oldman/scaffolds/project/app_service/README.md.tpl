# {{ project_name }}

给 coding agent 的说明在 [AGENTS.md](AGENTS.md)（Claude Code 经 `CLAUDE.md` 读到同一份），让 agent 开工前读完。

基于 Oldman `SimpleApplication` 的后台服务项目，不启动 HTTP 服务。入口是 `services/{{ service_name }}.py`，配置是 `data/{{ service_name }}_settings.yaml`。

在本项目根目录执行：

```sh
uv sync
./run.sh {{ service_name }} settings sync
./run.sh {{ service_name }} settings check
./run.sh {{ service_name }} start
```

`.python-version` 指定 Python 3.13（框架推荐的版本），`uv sync` 按它选解释器，本机没有时 uv 会自动下载；要用其他受支持的版本（3.12–3.14）就改这个文件。

生成的 `main()` 是一个示例循环：每 10 秒（`INTERVAL_SECONDS`）记一行日志，一直运行到 `./run.sh {{ service_name }} stop` 或 Ctrl+C。把循环体换成自己的业务；停止时 `main()` 在等待处被取消，循环后面的代码不会执行，要释放的资源在 `before_stop()` 或 `after_stop()` 里释放。

`run.sh` 只执行本项目虚拟环境中的 `oldman`，不自动运行所有服务。长时间运行时可以 Ctrl+C 停止，或另开终端使用 `./run.sh {{ service_name }} stop`。

增加可复用 App：

```sh
./run.sh startapp tasks
```

交互选择需要的 App 模板并填写显示名称，然后将实际包路径 `apps.tasks` 加入当前服务 YAML，再执行 `settings sync`。SimpleApplication 可以加载 App 模型和命令，不导入其 Web views。

需要数据库时，先填写 `database.url`、声明并注册模型，再执行 `./run.sh db makemigrations` 与 `./run.sh db migrate`。没有数据库业务时不要为了启动服务执行迁移。

普通一次性管理操作优先写成 App 的 `Command`，无需额外长期服务。完整接线见 [创建服务指南](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/agents/create-service.md)。

`uv sync` 需要声明的发行包可用。使用框架源码时，在本项目自己的 `.venv` 中 editable 安装，具体命令见[本地 Python 源码安装](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/agents/create-service.md#using-a-local-framework-checkout-instead-of-the-published-package)。真实 YAML 密钥和连接信息不提交到公开仓库。
