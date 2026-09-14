# {{ project_name }}

这是普通 Python CLI 脚本项目，入口是 `main.py`，不创建 Oldman 服务、服务配置或 Web 运行时。

在本项目根目录执行：

```sh
uv sync
uv run python main.py
```

预期输出 `{{ project_name }} is ready.`。业务逻辑写在 `main()` 或项目自己的模块中。

`uv sync` 需要 `pyproject.toml` 声明的 Oldman 发行版本可用；源码开发可使用独立环境中的 editable 安装，见 [源码安装说明](https://github.com/alexliyu7352/oldman/blob/master/docs/agents/create-service.md#新项目使用本地-python-源码)。这时用该环境的 Python 执行 `main.py`，不要无意间切换回包索引来源。

该模板没有 `run.sh`、`services/` 或数据库配置。如果需要按服务加载 Settings、App 或 ORM 模型，应创建 service/API/Web/Dashboard 类型项目，并把一次性管理功能写成 App 命令，而不是在这个脚本里另造初始化流程。
